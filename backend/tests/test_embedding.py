from types import SimpleNamespace

import pytest

from app.retrieval.embedding import Embedder, EmbeddingCache, make_batches


class FakeEmbeddings:
    """Giả lập `client.embeddings` của SDK openai: vector = [độ dài text, số lần gọi], mỗi text 10 token."""

    def __init__(self):
        self.calls: list[list[str]] = []

    async def create(self, input, model, dimensions):
        self.calls.append(list(input))
        data = [SimpleNamespace(index=i, embedding=[float(len(text)), 0.5]) for i, text in enumerate(input)]
        # Trả ngược thứ tự để kiểm tra Embedder sắp lại theo `index`.
        return SimpleNamespace(data=data[::-1], usage=SimpleNamespace(prompt_tokens=10 * len(input)))


def make_embedder(cache: EmbeddingCache | None = None) -> tuple[Embedder, FakeEmbeddings]:
    fake = FakeEmbeddings()
    client = SimpleNamespace(embeddings=fake)
    return Embedder(client, "text-embedding-3-small", 2, price_per_1m_tokens=0.02, cache=cache), fake


def test_make_batches_respects_input_and_token_limits():
    assert make_batches([1, 1, 1, 1, 1], max_inputs=2, max_tokens=100) == [range(2), range(2, 4), range(4, 5)]
    assert make_batches([60, 30, 20, 90], max_inputs=10, max_tokens=100) == [range(2), range(2, 3), range(3, 4)]
    # Một input vượt ngân sách token vẫn được gửi, trong batch riêng.
    assert make_batches([150, 10], max_inputs=10, max_tokens=100) == [range(1), range(1, 2)]
    assert make_batches([], max_inputs=10, max_tokens=100) == []


@pytest.mark.asyncio
async def test_embed_documents_keeps_order_and_counts_cost():
    embedder, _ = make_embedder()
    vectors, usage = await embedder.embed_documents(["a", "bbb", "cc"])
    assert vectors == [[1.0, 0.5], [3.0, 0.5], [2.0, 0.5]]
    assert (usage.requests, usage.tokens, usage.cached) == (1, 30, 0)
    assert usage.cost_usd == pytest.approx(30 * 0.02 / 1e6)


@pytest.mark.asyncio
async def test_duplicate_texts_are_sent_once():
    embedder, fake = make_embedder()
    vectors, _ = await embedder.embed_documents(["x", "yy", "x"])
    assert fake.calls == [["x", "yy"]]
    assert vectors[0] == vectors[2]


@pytest.mark.asyncio
async def test_cache_skips_api_for_known_content(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.sqlite")
    embedder, fake = make_embedder(cache)
    first, _ = await embedder.embed_documents(["một", "hai"])
    second, usage = await embedder.embed_documents(["hai", "ba", "một"])
    assert fake.calls == [["một", "hai"], ["ba"]]
    assert (usage.cached, usage.tokens) == (2, 10)
    assert second == [first[1], [2.0, 0.5], first[0]]
    cache.close()


@pytest.mark.asyncio
async def test_cache_is_keyed_by_model_and_dimensions(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.sqlite")
    cache.put_many("model-a", 2, {"h": [0.25, 0.5]})
    assert cache.get_many("model-a", 2, ["h", "missing"]) == {"h": [0.25, 0.5]}
    assert cache.get_many("model-a", 3, ["h"]) == {}
    assert cache.get_many("model-b", 2, ["h"]) == {}
    cache.close()


@pytest.mark.asyncio
async def test_embed_query_never_uses_cache(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.sqlite")
    embedder, fake = make_embedder(cache)
    await embedder.embed_query("câu hỏi")
    await embedder.embed_query("câu hỏi")
    assert len(fake.calls) == 2
    with pytest.raises(ValueError):
        await embedder.embed_query("  ")
    cache.close()
