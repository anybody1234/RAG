"""Sinh câu trả lời bằng LLM qua Responses API, streaming, đo TTFT và đếm token/chi phí.

TTFT ở đây là thời gian từ lúc gửi request tới token đầu tiên của câu trả lời (`response.output_text.delta`),
nên gồm cả thời gian suy luận (reasoning) của model. TTFT mà user thấy còn cộng thêm viết lại câu hỏi và
retrieval.
"""

import time
import unicodedata
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import openai
from openai import AsyncOpenAI

from app.core.language import Language, detect_language
from app.core.rag_config import GenerationConfig, ModelPrice
from app.generation.citations import CitationCheck, check_citations, is_abstention
from app.generation.prompts import answer_instructions, format_documents, strip_citations
from app.retrieval.llm import EXPLICIT_CACHE, LlmUsage, usage_from_response

Role = Literal["user", "assistant"]
Status = Literal["completed", "incomplete", "failed"]


@dataclass
class AnswerDelta:
    text: str


@dataclass
class AnswerResult:
    text: str
    language: Language
    model: str
    reasoning_effort: str
    prompt_version: str
    status: Status
    usage: LlmUsage = field(default_factory=LlmUsage)
    # None khi model không trả token câu trả lời nào.
    ttft_ms: float | None = None
    latency_ms: float = 0.0
    # Lý do response dừng sớm (ví dụ "max_output_tokens"), hoặc tên lỗi khi gọi API thất bại.
    error: str | None = None
    # Trích dẫn [n] đã kiểm tra và map sang văn bản/Điều/trang, kèm cảnh báo Điều bị sửa đổi. Nằm trong sự kiện
    # cuối của stream, để trace và payload trả về (SSE) đều có.
    citations: CitationCheck = field(default_factory=CitationCheck)
    abstained: bool = False


AnswerEvent = AnswerDelta | AnswerResult


def build_input(
    question: str, payloads: Sequence[dict[str, Any]], history: Sequence[tuple[Role, str]]
) -> list[dict[str, str]]:
    """Lịch sử hội thoại là các message trước; context và câu hỏi nằm trong message cuối của user."""
    messages = [
        {"role": role, "content": strip_citations(content) if role == "assistant" else content}
        for role, content in history
    ]
    messages.append({"role": "user", "content": f"{format_documents(payloads)}\n\n<question>{question}</question>"})
    return messages


class AnswerGenerator:
    def __init__(self, client: AsyncOpenAI, config: GenerationConfig, price: ModelPrice):
        answer_instructions(config.prompt_version, "vi")  # prompt_version sai thì báo lỗi ngay
        self.client, self.config, self.price = client, config, price

    async def stream(
        self,
        question: str,
        payloads: Sequence[dict[str, Any]],
        history: Sequence[tuple[Role, str]] = (),
        language: Language | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        """Trả từng đoạn text (`AnswerDelta`), cuối cùng là `AnswerResult`. Lỗi API không ném ra ngoài mà nằm
        trong `AnswerResult.error`, kèm phần text đã nhận được."""
        question = unicodedata.normalize("NFC", question).strip()
        language = language or detect_language(question)
        result = AnswerResult(
            text="", language=language, model=self.config.answer_model,
            reasoning_effort=self.config.answer_reasoning_effort, prompt_version=self.config.prompt_version,
            status="failed",
        )
        parts: list[str] = []
        start = time.perf_counter()
        try:
            events = await self.client.responses.create(
                model=self.config.answer_model,
                instructions=answer_instructions(self.config.prompt_version, language),
                input=build_input(question, payloads, history),  # type: ignore[arg-type]
                reasoning={"effort": self.config.answer_reasoning_effort},
                max_output_tokens=self.config.max_output_tokens,
                prompt_cache_options=EXPLICIT_CACHE,
                store=False,
                stream=True,
            )
            async for event in events:
                if event.type == "response.output_text.delta":
                    if result.ttft_ms is None:
                        result.ttft_ms = (time.perf_counter() - start) * 1000
                    parts.append(event.delta)
                    yield AnswerDelta(event.delta)
                elif event.type in ("response.completed", "response.incomplete", "response.failed"):
                    response = event.response
                    result.status = "failed" if event.type == "response.failed" else response.status or "completed"
                    result.usage = usage_from_response(response.usage, self.price)
                    if response.incomplete_details:
                        result.error = response.incomplete_details.reason
                    elif response.error:
                        result.error = response.error.code
                elif event.type == "error":
                    result.status, result.error = "failed", event.code or "error"
        except openai.OpenAIError as exc:
            result.status, result.error = "failed", type(exc).__name__
        result.latency_ms = (time.perf_counter() - start) * 1000
        result.text = "".join(parts)
        result.citations = check_citations(result.text, payloads, language)
        result.abstained = is_abstention(result.text)
        if not result.usage.calls:
            result.usage.calls = 1
        yield result

    async def generate(
        self,
        question: str,
        payloads: Sequence[dict[str, Any]],
        history: Sequence[tuple[Role, str]] = (),
        language: Language | None = None,
    ) -> AnswerResult:
        async for event in self.stream(question, payloads, history, language):
            if isinstance(event, AnswerResult):
                return event
        raise AssertionError("stream kết thúc mà không có AnswerResult")
