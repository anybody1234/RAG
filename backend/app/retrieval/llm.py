"""Gọi LLM qua Responses API với đầu ra JSON theo schema, đếm token và chi phí."""

import json
import time
from dataclasses import dataclass
from typing import Any, Self

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.rag_config import ModelPrice, ReasoningEffort

# Bước viết lại câu hỏi và rerank nằm trên đường trả lời: hỏng thì bỏ qua bước đó, không chờ lâu.
LLM_TIMEOUT_SECONDS = 15
LLM_MAX_RETRIES = 1


@dataclass
class LlmUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __iadd__(self, other: "LlmUsage") -> Self:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd += other.cost_usd
        return self


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
    """Một lần gọi, đầu ra là object JSON có đúng các trường trong `properties` (strict schema).

    Token suy luận (reasoning) được tính vào token đầu ra, giống cách OpenAI tính tiền.
    """
    start = time.perf_counter()
    response = await client.responses.create(
        model=model,
        instructions=instructions,
        input=input_text,
        reasoning={"effort": reasoning_effort},
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
    tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
    usage = LlmUsage(
        calls=1,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cost_usd=(tokens_in * price.input + tokens_out * price.output) / 1e6,
    )
    return LlmResult(parse_json_object(response.output_text), usage, latency_ms)


def parse_json_object(text: str) -> dict[str, Any]:
    """Object JSON đầu tiên trong text. Dù bật strict schema, gpt-6-luna đôi khi vẫn trả thêm ký tự rác sau
    object (gặp 2/200 lần khi rerank, ví dụ '{"ranking":[1,2]} ngood{...}'), nên bỏ phần sau object."""
    data, _ = json.JSONDecoder().raw_decode(text.lstrip())
    if not isinstance(data, dict):
        raise json.JSONDecodeError("đầu ra không phải object JSON", text, 0)
    return data


def build_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=get_settings().openai_api_key.get_secret_value(),
        max_retries=LLM_MAX_RETRIES,
        timeout=LLM_TIMEOUT_SECONDS,
    )
