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

Model của judge chạy qua một endpoint tương thích OpenAI theo hồ sơ `[judges.<tên>]` (Responses API hoặc Chat
Completions), có giới hạn request/token theo phút, đếm quota theo ngày trong ledger chi phí, và retry khi gặp 429.
Hết quota ngày thì ném `QuotaExhaustedError` để nơi gọi dừng gọn và chấm tiếp vào hôm sau.
"""

import asyncio
import json
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import openai
from openai import AsyncOpenAI

from app.core.config import REPO_ROOT, get_secret
from app.core.costs import BudgetedClient, CostLedger, get_cost_ledger, quota_window_start
from app.core.rag_config import JudgeProfile, ModelPrice, price_key
from app.generation.prompts import format_documents, strip_citations
from app.ingestion.tokens import TokenCounter
from app.retrieval.llm import (
    CACHE_BREAKPOINT,
    EXPLICIT_CACHE,
    LlmUsage,
    parse_json_object,
    usage_from_chat,
    usage_from_response,
)

JUDGES_DIR = REPO_ROOT / "eval" / "judges"
# Prompt ngắn hơn chừng này token thì OpenAI không ghi cache, nên không đặt điểm cache.
MIN_CACHEABLE_TOKENS = 1024
# Retry khi gặp 429 theo phút. Provider bảo chờ lâu hơn MAX_RETRY_WAIT_SECONDS thì coi như hết quota.
MAX_ATTEMPTS = 6
MAX_RETRY_WAIT_SECONDS = 180
# Timeout/5xx/mất kết nối liên tiếp chừng này lần thì coi provider đang hỏng (07/10: Gemini 3.8 treo khi quá tải).
MAX_CONSECUTIVE_FAILURES = 2

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


class JudgeUnavailableError(RuntimeError):
    """Không chấm tiếp được trong lần chạy này; nơi gọi dừng chấm, chấm nốt sau bằng --rejudge-missing. Không kế
    thừa OpenAIError, để không bị ghi như lỗi chấm một câu."""


class QuotaExhaustedError(JudgeUnavailableError):
    """Hết quota theo ngày của provider judge."""


class ProviderDownError(JudgeUnavailableError):
    """Provider judge lỗi (timeout, 5xx, mất kết nối) nhiều lần liên tiếp, ví dụ khi model quá tải."""


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
    # Model id do API trả về (có thể cụ thể hơn tên trong config).
    model: str | None = None
    usage: LlmUsage = field(default_factory=LlmUsage)
    # Thời gian gọi API (gồm các lần retry), không gồm thời gian chờ giới hạn rpm/tpm và chờ trước khi retry (wait_ms).
    latency_ms: float = 0.0
    wait_ms: float = 0.0
    error: str | None = None

    def scores(self) -> dict[str, float | None]:
        if self.error:
            return dict.fromkeys(METRICS)
        return judgment_scores(self.claims, self.correctness, self.relevancy)

    def record(self) -> dict[str, Any]:
        """Dạng JSON ghi vào kết quả eval."""
        return {
            "scores": self.scores(),
            "correctness": self.correctness,
            "relevancy": self.relevancy,
            "explanation": self.explanation,
            "claims": [vars(claim) for claim in self.claims],
            "model": self.model,
            "usage": vars(self.usage),
            "latency_ms": round(self.latency_ms, 1),
            "wait_ms": round(self.wait_ms, 1),
            "error": self.error,
        }


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
    model: str | None = None


class JudgeModel(Protocol):
    """Phần gọi model của judge. Logic chấm (prompt, cách tính điểm) không phụ thuộc provider."""

    name: str

    async def complete(self, instructions: str, case_text: str, schema: dict[str, Any], cache_case: bool) -> ModelReply:
        """Một lần chấm, đầu ra là JSON theo `schema`. Lỗi gọi API ném `openai.OpenAIError`; hết quota ngày ném
        `QuotaExhaustedError`."""
        ...


class RateLimiter:
    """Giới hạn request và token trong mỗi cửa sổ 60 giây (0 = không giới hạn). Token là ước tính."""

    def __init__(self, rpm: int, tpm: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.rpm, self.tpm, self._clock, self._sleep = rpm, tpm, clock, sleep
        self._events: deque[tuple[float, int]] = deque()

    async def acquire(self, tokens: int) -> None:
        while True:
            now = self._clock()
            while self._events and now - self._events[0][0] >= 60:
                self._events.popleft()
            used = sum(t for _, t in self._events)
            fits_rpm = not self.rpm or len(self._events) < self.rpm
            # Một request lớn hơn cả tpm vẫn được gửi khi cửa sổ trống, để không chờ mãi.
            fits_tpm = not self.tpm or not self._events or used + tokens <= self.tpm
            if fits_rpm and fits_tpm:
                self._events.append((now, tokens))
                return
            await self._sleep(60 - (now - self._events[0][0]) + 0.1)


class QuotaTracker:
    """Quota theo ngày của provider, đếm từ ledger (mọi lời gọi qua `BudgetedClient` đều có một dòng)."""

    def __init__(self, ledger: CostLedger, profile: JudgeProfile, now: Callable[[], datetime] | None = None):
        self.ledger, self.profile, self._now = ledger, profile, now

    def used(self) -> tuple[int, int]:
        since = quota_window_start(self.profile.quota_reset, self._now() if self._now else None)
        return self.ledger.usage_since(self.profile.provider, self.profile.model, since)

    def remaining(self) -> tuple[int | None, int | None]:
        """(request còn lại, token còn lại) trong ngày quota hiện tại; None nếu provider không giới hạn."""
        requests, tokens = self.used()
        return (
            self.profile.rpd - requests if self.profile.rpd else None,
            self.profile.tpd - tokens if self.profile.tpd else None,
        )

    def check(self, tokens: int) -> None:
        requests_left, tokens_left = self.remaining()
        if requests_left is not None and requests_left <= 0:
            raise QuotaExhaustedError(f"{self.profile.provider}/{self.profile.model}: đã dùng hết {self.profile.rpd} "
                                      "request trong ngày quota")
        if tokens_left is not None and tokens_left < tokens:
            raise QuotaExhaustedError(f"{self.profile.provider}/{self.profile.model}: còn {tokens_left} token trong "
                                      f"ngày quota, lời gọi cần khoảng {tokens}")


_DAILY_LIMIT = re.compile(r"per ?day|PerDay|\bRPD\b|\bTPD\b", re.IGNORECASE)
_RETRY_DELAY = re.compile(r"retryDelay\W+(\d+(?:\.\d+)?)s|try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _error_text(exc: openai.APIStatusError) -> str:
    return f"{exc.message} {json.dumps(exc.body, ensure_ascii=False) if exc.body is not None else ''}"


def is_daily_quota(exc: openai.APIStatusError) -> bool:
    """429 do hết quota theo ngày (Gemini: quotaId ...PerDay...; Groq: "requests per day (RPD)", "TPD")."""
    return bool(_DAILY_LIMIT.search(_error_text(exc)))


def retry_delay(exc: openai.APIStatusError) -> float | None:
    """Số giây provider bảo chờ: header Retry-After, `retryDelay` của Gemini, hoặc "try again in 7.6s" của Groq."""
    header = exc.response.headers.get("retry-after") if exc.response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    if m := _RETRY_DELAY.search(_error_text(exc)):
        if m.group(1):
            return float(m.group(1))
        return float(m.group(2) or 0) * 60 + float(m.group(3))
    return None


class OpenAICompatJudgeModel:
    """Endpoint tương thích OpenAI: Responses API (OpenAI) hoặc Chat Completions (Gemini, Groq...).

    Với Responses API: prompt cố định nằm trong message developer và chỉ được đặt điểm cache khi dài ≥
    `MIN_CACHEABLE_TOKENS`; `cache_case` đặt thêm điểm cache ở cuối case cho các lần chấm lặp lại.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        profile: JudgeProfile,
        price: ModelPrice,
        quota: QuotaTracker | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ):
        self.client, self.profile, self.price, self.quota, self._sleep = client, profile, price, quota, sleep
        self.limiter = limiter or RateLimiter(profile.rpm, profile.tpm, sleep=sleep)
        self.name = f"{profile.provider}/{profile.model}"
        self._count = TokenCounter(profile.model)
        # Số lời gọi liên tiếp bị timeout/5xx/mất kết nối, đếm qua các câu; về 0 khi có một lời gọi thành công.
        self.failures = 0
        # Thời gian (ms) lần `complete` gần nhất phải chờ giới hạn rpm/tpm và chờ trước khi retry, không tính gọi API.
        self.last_wait_ms = 0.0

    def build_input(self, instructions: str, case_text: str, cache_case: bool) -> list[dict[str, Any]]:
        fixed: dict[str, Any] = {"type": "input_text", "text": instructions}
        if self._count(instructions) >= MIN_CACHEABLE_TOKENS:
            fixed["prompt_cache_breakpoint"] = CACHE_BREAKPOINT
        body: dict[str, Any] = {"type": "input_text", "text": case_text}
        if cache_case:
            body["prompt_cache_breakpoint"] = CACHE_BREAKPOINT
        return [{"role": "developer", "content": [fixed]}, {"role": "user", "content": [body]}]

    def _common(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.profile.model}
        if self.profile.service_tier != "default":
            kwargs["service_tier"] = self.profile.service_tier
        return kwargs

    async def _responses(self, instructions: str, case_text: str, schema: dict[str, Any], cache_case: bool) -> ModelReply:
        kwargs = self._common()
        if self.profile.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.profile.reasoning_effort}
        response = await self.client.responses.create(
            input=self.build_input(instructions, case_text, cache_case),  # type: ignore[arg-type]
            max_output_tokens=self.profile.max_output_tokens,
            prompt_cache_options=EXPLICIT_CACHE,
            text={"format": {"type": "json_schema", "name": "judgment", "strict": True, "schema": schema}},
            store=False,
            **kwargs,
        )
        usage = usage_from_response(response.usage, self.price)
        model = getattr(response, "model", None)
        if getattr(response, "status", "completed") != "completed":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            return ModelReply("", usage, incomplete=str(reason), model=model)
        return ModelReply(response.output_text, usage, model=model)

    async def _chat(self, instructions: str, case_text: str, schema: dict[str, Any]) -> ModelReply:
        kwargs = self._common()
        if self.profile.reasoning_effort:
            kwargs["reasoning_effort"] = self.profile.reasoning_effort
        response = await self.client.chat.completions.create(
            messages=[{"role": "system", "content": instructions}, {"role": "user", "content": case_text}],
            response_format={"type": "json_schema", "json_schema": {"name": "judgment", "strict": True, "schema": schema}},
            max_completion_tokens=self.profile.max_output_tokens,
            **kwargs,
        )
        usage = usage_from_chat(response.usage, self.price)
        choice = response.choices[0] if response.choices else None
        text = (choice.message.content or "") if choice else ""
        finish = getattr(choice, "finish_reason", None)
        incomplete = finish if finish in ("length", "content_filter") or choice is None else None
        return ModelReply(text, usage, incomplete=incomplete, model=getattr(response, "model", None))

    async def _wait(self, awaitable: Awaitable[Any]) -> None:
        start = time.perf_counter()
        await awaitable
        self.last_wait_ms += (time.perf_counter() - start) * 1000

    async def complete(self, instructions: str, case_text: str, schema: dict[str, Any], cache_case: bool) -> ModelReply:
        # Ước tính cho giới hạn tpm và quota token ngày: token vào đếm bằng tokenizer, cộng token ra thường gặp (không
        # phải max_output_tokens, vì gần như không lời gọi nào dùng hết).
        tokens = self._count(instructions) + self._count(case_text) + self.profile.output_tokens_estimate
        last: Exception | None = None
        self.last_wait_ms = 0.0
        for attempt in range(MAX_ATTEMPTS):
            if self.quota:
                self.quota.check(tokens)
            await self._wait(self.limiter.acquire(tokens))
            try:
                if self.profile.api == "responses":
                    reply = await self._responses(instructions, case_text, schema, cache_case)
                else:
                    reply = await self._chat(instructions, case_text, schema)
                self.failures = 0
                return reply
            except openai.RateLimitError as exc:
                if is_daily_quota(exc):
                    raise QuotaExhaustedError(f"{self.name}: hết quota theo ngày ({exc.message[:200]})") from exc
                delay = retry_delay(exc) or min(60.0, 5.0 * 2**attempt)
                if delay > MAX_RETRY_WAIT_SECONDS:
                    raise QuotaExhaustedError(f"{self.name}: provider bảo chờ {delay:.0f} s") from exc
                last = exc
            except (openai.APIConnectionError, openai.InternalServerError) as exc:
                # Timeout, mất kết nối, 5xx: mỗi lần thử đều trừ quota ngày, nên chỉ retry 1 lần; lỗi liên tiếp (tính
                # cả qua các câu) tới MAX_CONSECUTIVE_FAILURES thì coi provider đang hỏng và dừng chấm.
                self.failures += 1
                if self.failures >= MAX_CONSECUTIVE_FAILURES:
                    raise ProviderDownError(
                        f"{self.name}: {self.failures} lỗi liên tiếp, lần cuối {type(exc).__name__}"
                    ) from exc
                delay, last = 5.0, exc
            await self._wait(self._sleep(delay + 0.5))
        assert last is not None
        raise last


class Judge:
    def __init__(self, model: JudgeModel, prompt_version: str, judges_dir: Path = JUDGES_DIR):
        path = judges_dir / f"{prompt_version}.md"
        if not path.exists():
            raise ValueError(f"không có prompt judge {path}")
        self.model, self.prompt_version = model, prompt_version
        self.instructions = path.read_text(encoding="utf-8").strip()

    async def judge(self, case: JudgeCase, cache_case: bool = False) -> Judgment:
        """Lỗi API hoặc đầu ra hỏng nằm trong `Judgment.error`. Hết quota ngày thì ném `QuotaExhaustedError`."""
        start = time.perf_counter()
        judgment = Judgment()
        try:
            reply = await self.model.complete(self.instructions, format_case(case), JUDGMENT_SCHEMA, cache_case)
            judgment.usage, judgment.model = reply.usage, reply.model
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
        judgment.wait_ms = getattr(self.model, "last_wait_ms", 0.0)
        judgment.latency_ms = (time.perf_counter() - start) * 1000 - judgment.wait_ms
        return judgment


def judge_identity(name: str, profile: JudgeProfile, prompt_version: str) -> dict[str, Any]:
    """Định danh judge ghi vào kết quả eval; hai lần chấm chỉ gộp được khi định danh trùng nhau."""
    return {"profile": name, "provider": profile.provider, "model": profile.model, "api": profile.api,
            "base_url": profile.base_url, "reasoning_effort": profile.reasoning_effort,
            "service_tier": profile.service_tier, "prompt_version": prompt_version}


def build_judge(
    profile: JudgeProfile, prompt_version: str, prices: dict[str, ModelPrice], ledger: CostLedger | None = None
) -> Judge:
    """Judge theo hồ sơ: client qua trần chi phí (ghi provider vào ledger), đếm quota theo ngày từ ledger. SDK không
    tự retry (`max_retries=0`): retry nằm trong `OpenAICompatJudgeModel` để tôn trọng giới hạn của provider."""
    key = price_key(profile.model, profile.service_tier)
    if key not in prices:
        raise KeyError(f"chưa có giá của {key} trong [prices] của config/rag.toml (provider miễn phí: ghi 0)")
    client = AsyncOpenAI(
        api_key=get_secret(profile.api_key_env), base_url=profile.base_url, max_retries=0,
        timeout=profile.timeout_seconds,
    )
    ledger = ledger or get_cost_ledger()
    wrapped = cast(AsyncOpenAI, BudgetedClient(client, ledger, prices, profile.provider))
    model = OpenAICompatJudgeModel(wrapped, profile, prices[key], QuotaTracker(ledger, profile))
    return Judge(model, prompt_version)
