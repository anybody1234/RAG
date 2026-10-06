from types import SimpleNamespace

import httpx
import openai
import pytest
from fakes import FakeResponses

from app.core.rag_config import ModelPrice, RerankConfig
from app.retrieval.rerank import LlmReranker, apply_ranking, format_passages
from app.retrieval.search import Hit


def hits(n: int) -> list[Hit]:
    return [
        Hit(id=f"p{i}", score=1 / (i + 1),
            payload={"title": "Bộ luật Lao động", "heading_path": f"Điều {i}", "text": f"nội dung {i} " * 50})
        for i in range(n)
    ]


def ids(items: list[Hit]) -> list[str]:
    return [hit.id for hit in items]


def make_reranker(candidates: int = 4, **fake) -> tuple[LlmReranker, FakeResponses]:
    responses = FakeResponses(**fake)
    config = RerankConfig(model="gpt-6-luna", reasoning_effort="none", prompt_version="rerank-v1",
                          candidates=candidates, max_chunk_tokens=20)
    return LlmReranker(SimpleNamespace(responses=responses), config, ModelPrice(input=0.1, output=0.5)), responses


def test_apply_ranking_moves_chosen_first_and_ignores_bad_numbers():
    items = hits(5)
    assert ids(apply_ranking(items, [3, 1, 3, 9, 0, -2])) == ["p2", "p0", "p1", "p3", "p4"]
    assert ids(apply_ranking(items, [])) == ids(items)


def test_passages_are_numbered_and_truncated():
    text = format_passages(hits(2), max_tokens=10)
    assert text.startswith("[1] Bộ luật Lao động | Điều 0\n") and "\n\n[2] Bộ luật Lao động | Điều 1\n" in text
    assert text.count("nội dung") < 20 and "…" in text


@pytest.mark.asyncio
async def test_rerank_reorders_candidates_and_keeps_the_tail():
    reranker, responses = make_reranker(candidates=4, data={"ranking": [4, 2]})
    result = await reranker.rerank("Câu hỏi?", hits(6))
    assert ids(result.hits) == ["p3", "p1", "p0", "p2", "p4", "p5"]
    assert "<question>Câu hỏi?</question>" in responses.calls[0]["input"]
    assert "[4]" in responses.calls[0]["input"] and "[5]" not in responses.calls[0]["input"]
    assert result.usage.calls == 1 and result.error is None


@pytest.mark.asyncio
async def test_trailing_garbage_after_json_is_ignored():
    reranker, _ = make_reranker(raw='{"ranking":[2,1]} ngood{"ranking":[1,2]}')
    result = await reranker.rerank("Câu hỏi?", hits(3))
    assert ids(result.hits) == ["p1", "p0", "p2"] and result.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["không phải JSON", "[1, 2]"])
async def test_output_that_is_not_a_json_object_keeps_original_order(raw):
    reranker, _ = make_reranker(raw=raw)
    result = await reranker.rerank("Câu hỏi?", hits(3))
    assert ids(result.hits) == ids(hits(3)) and result.error == "JSONDecodeError"


@pytest.mark.asyncio
async def test_rerank_error_keeps_original_order():
    error = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    reranker, _ = make_reranker(error=error)
    result = await reranker.rerank("Câu hỏi?", hits(5))
    assert ids(result.hits) == ids(hits(5)) and result.error == "APITimeoutError"
