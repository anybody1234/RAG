"""LLM-judge cho câu trả lời. Prompt nằm ở eval/judges/<judge_prompt_version>.md (version hoá theo tên file).

Judge tách câu trả lời thành các ý (claim). Với mỗi ý, judge ghi các `[n]` gắn với ý đó, ý có được context ủng hộ
không, và những `[n]` nào thật sự ủng hộ ý đó. Ngoài ra judge gán nhãn correctness (so với đáp án chuẩn) và
relevancy. Metric tính trong code, không để judge tự cho điểm:
- faithfulness       = số ý được context ủng hộ / số ý
- citation_precision = số cặp (ý, [n]) mà [n] ủng hộ ý / số cặp (ý, [n])
- citation_recall    = số ý có ít nhất một [n] ủng hộ / số ý
- correctness, relevancy: nhãn 3 mức, quy ra 1 / 0.5 / 0
Câu trả lời không có ý nào (chỉ từ chối) thì faithfulness và citation recall là None, không tính vào trung bình.
Từ chối đúng/sai đếm trực tiếp bằng `is_abstention`, không qua judge.
"""

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import openai
from openai import AsyncOpenAI

from app.core.config import REPO_ROOT
from app.core.rag_config import EvalConfig, ModelPrice
from app.generation.prompts import format_documents, strip_citations
from app.ingestion.tokens import TokenCounter
from app.retrieval.llm import (
    CACHE_BREAKPOINT,
    EXPLICIT_CACHE,
    LlmUsage,
    parse_json_object,
    usage_from_response,
)

JUDGES_DIR = REPO_ROOT / "eval" / "judges"
# Prompt ngắn hơn chừng này token thì OpenAI không ghi cache, nên không đặt điểm cache.
MIN_CACHEABLE_TOKENS = 1024

Role = Literal["user", "assistant"]
LABEL_SCORES = {
    "correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0,
    "relevant": 1.0, "partially_relevant": 0.5, "irrelevant": 0.0,
}
METRICS = ("faithfulness", "citation_precision", "citation_recall", "correctness", "relevancy")

_CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "cited": {"type": "array", "items": {"type": "integer"}},
        "supported": {"type": "boolean"},
        "supporting_cited": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["claim", "cited", "supported", "supporting_cited"],
    "additionalProperties": False,
}
JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": _CLAIM_SCHEMA},
        "correctness": {"type": "string", "enum": ["correct", "partially_correct", "incorrect"]},
        "relevancy": {"type": "string", "enum": ["relevant", "partially_relevant", "irrelevant"]},
        "explanation": {"type": "string"},
    },
    "required": ["claims", "correctness", "relevancy", "explanation"],
    "additionalProperties": False,
}


@dataclass
class JudgeCase:
    question: str
    reference_answer: str
    # Chunk đúng như đã đưa cho model trả lời, cùng thứ tự đánh số [n].
    payloads: Sequence[dict[str, Any]]
    answer: str
    history: Sequence[tuple[Role, str]] = ()


@dataclass
class Claim:
    claim: str
    cited: list[int]
    supported: bool
    supporting_cited: list[int]


@dataclass
class Judgment:
    claims: list[Claim] = field(default_factory=list)
    correctness: str | None = None
    relevancy: str | None = None
    explanation: str = ""
    usage: LlmUsage = field(default_factory=LlmUsage)
    latency_ms: float = 0.0
    error: str | None = None

    def scores(self) -> dict[str, float | None]:
        if self.error:
            return dict.fromkeys(METRICS)
        return judgment_scores(self.claims, self.correctness, self.relevancy)


def judgment_scores(claims: Sequence[Claim], correctness: str | None, relevancy: str | None) -> dict[str, float | None]:
    n = len(claims)
    pairs = sum(len(c.cited) for c in claims)
    return {
        "faithfulness": sum(c.supported for c in claims) / n if n else None,
        "citation_precision": sum(len(c.supporting_cited) for c in claims) / pairs if pairs else None,
        "citation_recall": sum(bool(c.supporting_cited) for c in claims) / n if n else None,
        "correctness": LABEL_SCORES.get(correctness or ""),
        "relevancy": LABEL_SCORES.get(relevancy or ""),
    }


def parse_claims(raw: Any) -> list[Claim]:
    """Chỉ giữ số nguyên; `supporting_cited` phải nằm trong `cited` (judge đôi khi ghi số không gắn với ý đó)."""
    claims = []
    for item in raw if isinstance(raw, list) else []:
        cited = list(dict.fromkeys(n for n in item.get("cited", []) if isinstance(n, int)))
        supporting = [n for n in dict.fromkeys(item.get("supporting_cited", [])) if n in cited]
        claims.append(Claim(str(item.get("claim", "")), cited, bool(item.get("supported")), supporting))
    return claims


def format_case(case: JudgeCase) -> str:
    parts = []
    if case.history:
        turns = [f"{role}: {strip_citations(text) if role == 'assistant' else text}" for role, text in case.history]
        parts.append("<conversation_history>\n" + "\n".join(turns) + "\n</conversation_history>")
    parts += [
        f"<question>{case.question}</question>",
        f"<reference_answer>{case.reference_answer}</reference_answer>",
        format_documents(case.payloads),
        f"<answer>{case.answer}</answer>",
    ]
    return "\n\n".join(parts)


@dataclass
class ModelReply:
    text: str
    usage: LlmUsage
    # Lý do model dừng trước khi trả xong (ví dụ "max_output_tokens"); None khi trả đủ.
    incomplete: str | None = None


class JudgeModel(Protocol):
    """Phần gọi model của judge. Logic chấm (prompt, cách tính điểm) không phụ thuộc provider, nên đổi provider
    (OpenAI, OpenRouter, Batch API...) chỉ cần một cài đặt khác của interface này."""

    name: str

    async def complete(self, instructions: str, case_text: str, schema: dict[str, Any], cache_case: bool) -> ModelReply:
        """Một lần chấm, đầu ra là JSON theo `schema`. Lỗi gọi API ném `openai.OpenAIError`."""
        ...


class OpenAIJudgeModel:
    """Responses API của OpenAI, đầu ra JSON strict, có prompt cache.

    - Prompt cố định nằm trong message developer (top-level `instructions` không nhận điểm cache), và chỉ được đặt
      điểm cache khi dài ≥ `MIN_CACHEABLE_TOKENS`.
    - `cache_case`: đặt thêm điểm cache ở cuối case, để các lần chấm lặp lại cùng câu trả lời đọc cả prompt từ
      cache. Chỉ bật khi sẽ chấm lại; chấm một lần thì ghi cache chỉ tốn thêm 25%.
    """

    def __init__(self, client: AsyncOpenAI, config: EvalConfig, price: ModelPrice):
        self.client, self.config, self.price = client, config, price
        self.name = f"{config.judge_model}:{config.judge_reasoning_effort}@{config.judge_service_tier}"

    def build_input(self, instructions: str, case_text: str, cache_case: bool) -> list[dict[str, Any]]:
        fixed: dict[str, Any] = {"type": "input_text", "text": instructions}
        if TokenCounter(self.config.judge_model)(instructions) >= MIN_CACHEABLE_TOKENS:
            fixed["prompt_cache_breakpoint"] = CACHE_BREAKPOINT
        body: dict[str, Any] = {"type": "input_text", "text": case_text}
        if cache_case:
            body["prompt_cache_breakpoint"] = CACHE_BREAKPOINT
        return [{"role": "developer", "content": [fixed]}, {"role": "user", "content": [body]}]

    async def complete(self, instructions: str, case_text: str, schema: dict[str, Any], cache_case: bool) -> ModelReply:
        tier: dict[str, Any] = (
            {"service_tier": self.config.judge_service_tier} if self.config.judge_service_tier != "default" else {}
        )
        response = await self.client.responses.create(
            model=self.config.judge_model,
            input=self.build_input(instructions, case_text, cache_case),  # type: ignore[arg-type]
            reasoning={"effort": self.config.judge_reasoning_effort},
            max_output_tokens=self.config.judge_max_output_tokens,
            prompt_cache_options=EXPLICIT_CACHE,
            text={"format": {"type": "json_schema", "name": "judgment", "strict": True, "schema": schema}},
            store=False,
            **tier,
        )
        usage = usage_from_response(response.usage, self.price)
        if getattr(response, "status", "completed") != "completed":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            return ModelReply("", usage, incomplete=str(reason))
        return ModelReply(response.output_text, usage)


class Judge:
    def __init__(self, model: JudgeModel, prompt_version: str, judges_dir: Path = JUDGES_DIR):
        path = judges_dir / f"{prompt_version}.md"
        if not path.exists():
            raise ValueError(f"không có prompt judge {path}")
        self.model, self.prompt_version = model, prompt_version
        self.instructions = path.read_text(encoding="utf-8").strip()

    async def judge(self, case: JudgeCase, cache_case: bool = False) -> Judgment:
        start = time.perf_counter()
        judgment = Judgment()
        try:
            reply = await self.model.complete(self.instructions, format_case(case), JUDGMENT_SCHEMA, cache_case)
            judgment.usage = reply.usage
            if reply.incomplete:
                judgment.error = f"incomplete:{reply.incomplete}"
            else:
                data = parse_json_object(reply.text)
                judgment.claims = parse_claims(data.get("claims"))
                judgment.correctness = data.get("correctness")
                judgment.relevancy = data.get("relevancy")
                judgment.explanation = str(data.get("explanation", ""))
        except (openai.OpenAIError, json.JSONDecodeError) as exc:
            judgment.error = type(exc).__name__
            judgment.usage.calls = judgment.usage.calls or 1
        judgment.latency_ms = (time.perf_counter() - start) * 1000
        return judgment


def build_judge(client: AsyncOpenAI, config: EvalConfig, price: ModelPrice) -> Judge:
    """Judge theo `[eval]` của config. Hiện chỉ có provider OpenAI."""
    return Judge(OpenAIJudgeModel(client, config, price), config.judge_prompt_version)
