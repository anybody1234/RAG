"""Index + truy vấn trên Qdrant chạy trong bộ nhớ (local mode của qdrant-client), không cần Docker."""

import hashlib
from types import SimpleNamespace

import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from app.core.rag_config import RetrievalConfig
from app.ingestion.models import Chunk
from app.retrieval.embedding import Embedder
from app.retrieval.index import SPARSE, ensure_collection, index_document, point_id, user_filter
from app.retrieval.search import Retriever
from app.retrieval.sparse import SparseEncoder

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

COLLECTION = "test"
KEYWORDS = ("thử việc", "lương", "nghỉ")


class KeywordEmbeddings:
    """Vector giả: mỗi chiều là số lần xuất hiện của một từ khoá, thêm một chiều hằng để tránh vector 0."""

    async def create(self, input, model, dimensions):
        data = [
            SimpleNamespace(index=i, embedding=[float(text.lower().count(k)) for k in KEYWORDS] + [0.1])
            for i, text in enumerate(input)
        ]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=len(input)))


def make_chunks(doc_id: str, texts: list[str]) -> list[Chunk]:
    return [
        Chunk(
            doc_id=doc_id, title="Bộ luật Lao động", language="vi", amended_by=["71/2025/QH15"],
            chunk_id=f"{doc_id}:{i:04d}", chunk_index=i, text=text, heading_path=f"Điều {i + 1}",
            article=f"Điều {i + 1}", page=i + 1, page_end=i + 1, token_count=len(text.split()),
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for i, text in enumerate(texts)
    ]


TEXTS = [
    "Điều 1. Thời gian thử việc không quá 60 ngày",
    "Điều 2. Tiền lương trả theo tháng",
    "Điều 3. Nghỉ hằng năm 12 ngày",
]


@pytest_asyncio.fixture
async def setup():
    client = AsyncQdrantClient(location=":memory:")
    embedder = Embedder(SimpleNamespace(embeddings=KeywordEmbeddings()), "fake", len(KEYWORDS) + 1, 0.02)
    encoder = SparseEncoder(1.2, 0.75, 10)
    await ensure_collection(client, COLLECTION, len(KEYWORDS) + 1)
    config = RetrievalConfig(mode="hybrid", prefetch_limit=10, rrf_k=60, top_k=2, reranker="none")
    retriever = Retriever(client, COLLECTION, embedder, encoder, config)
    yield client, embedder, encoder, retriever
    await client.close()


async def count(client: AsyncQdrantClient) -> int:
    return (await client.count(COLLECTION, exact=True)).count


def test_point_id_is_deterministic_and_scoped_by_user():
    assert point_id("system", "doc", "abc") == point_id("system", "doc", "abc")
    assert point_id("system", "doc", "abc") != point_id("user-1", "doc", "abc")
    assert point_id("system", "doc", "abc") != point_id("system", "doc2", "abc")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid"])
async def test_every_mode_finds_the_matching_chunk(setup, mode):
    client, embedder, encoder, retriever = setup
    await index_document(client, COLLECTION, make_chunks("blld", TEXTS), "system", embedder, encoder)
    result = await retriever.search("Thử việc tối đa bao lâu?", "system", mode=mode)
    assert result.hits[0].payload["chunk_id"] == "blld:0000"
    assert len(result.hits) <= 2
    assert result.timings_ms["total"] >= result.timings_ms["search"]
    assert (result.timings_ms["embed"] > 0) == (mode != "sparse")


@pytest.mark.asyncio
async def test_payload_has_metadata_and_user(setup):
    client, embedder, encoder, retriever = setup
    await index_document(client, COLLECTION, make_chunks("blld", TEXTS), "system", embedder, encoder)
    payload = (await retriever.search("lương", "system", mode="dense")).hits[0].payload
    assert payload["user_id"] == "system"
    assert payload["amended_by"] == ["71/2025/QH15"]
    assert payload["heading_path"] == "Điều 2" and payload["page"] == 2


@pytest.mark.asyncio
async def test_users_only_see_their_own_points(setup):
    client, embedder, encoder, retriever = setup
    await index_document(client, COLLECTION, make_chunks("blld", TEXTS), "system", embedder, encoder)
    await index_document(client, COLLECTION, make_chunks("rieng", ["Quy chế lương nội bộ"]), "user-1", embedder, encoder)
    for mode in ("dense", "sparse", "hybrid"):
        system_hits = (await retriever.search("lương", "system", mode=mode, limit=10)).hits
        user_hits = (await retriever.search("lương", "user-1", mode=mode, limit=10)).hits
        assert {hit.payload["user_id"] for hit in system_hits} == {"system"}
        assert [hit.payload["chunk_id"] for hit in user_hits] == ["rieng:0000"]
    assert (await retriever.search("lương", "user-2")).hits == []


@pytest.mark.asyncio
async def test_sparse_idf_is_computed_on_the_user_corpus_only(setup):
    """User b có 20 chunk chứa "lương". Với IDF toàn collection, "lương" gần như mất trọng số với user a;
    với IDF theo kho của user a, "lương" hiếm ngang "phạt" nên chunk có nhiều "lương" đứng đầu."""
    client, embedder, encoder, retriever = setup
    await index_document(client, COLLECTION, make_chunks("a", ["lương lương lương", "phạt"]), "a", embedder, encoder)
    await index_document(
        client, COLLECTION, make_chunks("b", [f"lương mục {i}" for i in range(20)]), "b", embedder, encoder
    )
    hits = (await retriever.search("lương phạt", "a", mode="sparse")).hits
    assert [hit.payload["chunk_id"] for hit in hits] == ["a:0000", "a:0001"]

    global_idf = await client.query_points(
        COLLECTION, query=encoder.encode_query("lương phạt"), using=SPARSE, query_filter=user_filter("a"),
        with_payload=True,
    )
    assert [point.payload["chunk_id"] for point in global_idf.points] == ["a:0001", "a:0000"]


@pytest.mark.asyncio
async def test_reindexing_is_idempotent_and_removes_stale_chunks(setup):
    client, embedder, encoder, _ = setup
    first = await index_document(client, COLLECTION, make_chunks("blld", TEXTS), "system", embedder, encoder)
    again = await index_document(client, COLLECTION, make_chunks("blld", TEXTS), "system", embedder, encoder)
    assert (first.chunks, again.chunks, again.removed, await count(client)) == (3, 3, 0, 3)

    changed = TEXTS[:2] + ["Điều 3. Nghỉ hằng năm 14 ngày"]
    report = await index_document(client, COLLECTION, make_chunks("blld", changed), "system", embedder, encoder)
    assert (report.removed, await count(client)) == (1, 3)


@pytest.mark.asyncio
async def test_index_document_rejects_mixed_documents(setup):
    client, embedder, encoder, _ = setup
    chunks = make_chunks("a", TEXTS[:1]) + make_chunks("b", TEXTS[1:2])
    with pytest.raises(ValueError):
        await index_document(client, COLLECTION, chunks, "system", embedder, encoder)
