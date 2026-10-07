"""Gọi LLM qua Responses API với đầu ra JSON theo schema, đếm token và chi phí."""

import json
import time
from dataclasses import dataclass
from typing import Any, Self

from openai import AsyncOpenAI
from openai.types.responses.response_create_params import PromptCacheOptions
from openai.types.responses.response_input_text_param import PromptCacheBreakpoint

from app.core.config import get_settings
from app.core.costs import budgeted
from app.core.rag_config import ModelPrice, ReasoningEffort, get_rag_config

# Bước viết lại câu hỏi và rerank nằm trên đường trả lời: hỏng thì bỏ qua bước đó, không chờ lâu.
LLM_TIMEOUT_SECONDS = 15
LLM_MAX_RETRIES = 1


# Từ GPT-5.6, mặc định (mode "implicit") OpenAI tự đặt một điểm ghi cache ở cuối prompt từ 1024 token trở lên,
# và token ghi cache tính 1.25 lần giá input. Prompt có context khác nhau mỗi lần (rerank, trả lời) thì không bao
# giờ đọc lại được, nên dùng mode "explicit": chỉ ghi cache ở những điểm đánh dấu `prompt_cache_breakpoint`.
EXPLICIT_CACHE: PromptCacheOptions = {"mode": "explicit"}
CACHE_BREAKPOINT: PromptCacheBreakpoint = {"mode": "explicit"}


@dataclass
class LlmUsage:
    calls: int = 0
    # Tổng token đầu vào, đã gồm token đọc cache (`cached_input_tokens`) và ghi cache (`cache_write_tokens`).
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    # Đã gồm token suy luận (`reasoning_tokens`), giống cách OpenAI tính tiền.
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    def __iadd__(self, other: "LlmUsage") -> Self:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.cost_usd += other.cost_usd
        return self


def usage_from_response(usage: Any, price: ModelPrice) -> LlmUsage:
    """`usage` của một response (Responses API). API không trả usage thì chỉ đếm lần gọi."""
    if usage is None:
        return LlmUsage(calls=1)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    cached = getattr(input_details, "cached_tokens", 0) or 0
    written = getattr(input_details, "cache_write_tokens", 0) or 0
    return LlmUsage(
        calls=1,
        input_tokens=usage.input_tokens,
        cached_input_tokens=cached,
        cache_write_tokens=written,
        output_tokens=usage.output_tokens,
        reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0,
        cost_usd=price.cost(usage.input_tokens, usage.output_tokens, cached, written),
    )


@dataclass
class LlmResult:
    data: dict[str, Any]
    usage: LlmUsage
    latency_ms: float


async def complete_json(
    client: AsyncOpenAI,
    model: str,
    reasoning_effort: ReasoningEffort,
    price: ModelPrice,
    instructions: str,
    input_text: str,
    schema_name: str,
    properties: dict[str, Any],
) -> LlmResult:
    """Một lần gọi, đầu ra là object JSON có đúng các trường trong `properties` (strict schema)."""
    start = time.perf_counter()
    response = await client.responses.create(
        model=model,
        instructions=instructions,
        input=input_text,
        reasoning={"effort": reasoning_effort},
        prompt_cache_options=EXPLICIT_CACHE,
        text={"format": {
            "type": "json_schema",
            "name": schema_name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        }},
        store=False,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    return LlmResult(parse_json_object(response.output_text), usage_from_response(response.usage, price), latency_ms)


def parse_json_object(text: str) -> dict[str, Any]:
    """Object JSON đầu tiên trong text. Dù bật strict schema, gpt-6-luna đôi khi vẫn trả thêm ký tự rác sau
    object (gặp 2/200 lần khi rerank, ví dụ '{"ranking":[1,2]} ngood{...}'), nên bỏ phần sau object."""
    data, _ = json.JSONDecoder().raw_decode(text.lstrip())
    if not isinstance(data, dict):
        raise json.JSONDecodeError("đầu ra không phải object JSON", text, 0)
    return data


def build_llm_client(timeout: float = LLM_TIMEOUT_SECONDS, max_retries: int = LLM_MAX_RETRIES) -> AsyncOpenAI:
    """Client đi qua trần chi phí theo ngày (`app.core.costs`), giá lấy từ `[prices]` của config/rag.toml."""
    client = AsyncOpenAI(
        api_key=get_settings().openai_api_key.get_secret_value(),
        max_retries=max_retries,
        timeout=timeout,
    )
    return budgeted(client, get_rag_config().prices)
