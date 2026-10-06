"""Index + truy vấn trên Qdrant chạy trong bộ nhớ (local mode của qdrant-client), không cần Docker."""

import hashlib
from types import SimpleNamespace

import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from app.core.rag_config import RetrievalConfig
from app.ingestion.models import Chunk
from app.retrieval.embedding import Embedder
from app.retrieval.index import (
    SPARSE,
    IndexMismatchError,
    check_collection,
    embedding_text,
    ensure_collection,
    index_document,
    point_id,
    user_filter,
)
from app.retrieval.search import Retriever
from app.retrieval.sparse import SparseEncoder

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

COLLECTION = "test"
KEYWORDS = ("thử việc", "lương", "nghỉ")
SIGNATURE = {
    "chunking": {"max_tokens": 800, "overlap_ratio": 0.1},
    "embedding": {"model": "fake", "dimensions": len(KEYWORDS) + 1},
    "sparse": {"k1": 1.2, "b": 0.75, "avg_doc_len": 10.0},
    "embed_title": False,
}


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


def retrieval_config(**overrides) -> RetrievalConfig:
    values = {"mode": "hybrid", "prefetch_limit": 10, "rrf_k": 60, "dense_weight": 1.0, "sparse_weight": 1.0,
              "top_k": 2, "reranker": "none"}
    return RetrievalConfig(**(values | overrides))


@pytest_asyncio.fixture
async def setup():
    client = AsyncQdrantClient(location=":memory:")
    embedder = Embedder(SimpleNamespace(embeddings=KeywordEmbeddings()), "fake", len(KEYWORDS) + 1, 0.02)
    encoder = SparseEncoder(1.2, 0.75, 10)
    await ensure_collection(client, COLLECTION, SIGNATURE)
    retriever = Retriever(client, COLLECTION, embedder, encoder, retrieval_config())
    yield client, embedder, encoder, retriever
    await client.close()


async def count(client: AsyncQdrantClient) -> int:
    return (await client.count(COLLECTION, exact=True)).count


def test_embedding_text_can_carry_document_title():
    chunk = make_chunks("blld", TEXTS[:1])[0]
    assert embedding_text(chunk, with_title=False) == chunk.text
    assert embedding_text(chunk, with_title=True) == f"Bộ luật Lao động | Điều 1\n{chunk.text}"
    with_so_hieu = chunk.model_copy(update={"so_hieu": "45/2019/QH14"})
    assert embedding_text(with_so_hieu, with_title=True).startswith("Bộ luật Lao động (45/2019/QH14) | Điều 1\n")


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


@pytest.mark.asyncio
async def test_collection_signature_must_match(setup):
    client, *_ = setup
    assert await ensure_collection(client, COLLECTION, SIGNATURE) is False
    other = SIGNATURE | {"chunking": {"max_tokens": 400, "overlap_ratio": 0.1}}
    with pytest.raises(IndexMismatchError):
        await ensure_collection(client, COLLECTION, other)
    with pytest.raises(IndexMismatchError):
        await check_collection(client, "chua-co", SIGNATURE)
    assert await ensure_collection(client, COLLECTION, other, recreate=True) is True
    await check_collection(client, COLLECTION, other)


@pytest.mark.asyncio
async def test_translated_query_retrieves_documents_in_the_other_language(setup):
    """Câu tiếng Việt không chung từ nào với văn bản tiếng Anh; câu dịch tìm được nhờ nhánh sparse của nó."""
    client, embedder, encoder, retriever = setup
    english = ["Article 1. Probation shall not exceed 60 days", "Article 2. Wages are paid monthly",
               "Article 3. Annual leave of 12 days"]
    await index_document(client, COLLECTION, make_chunks("en", english), "system", embedder, encoder)
    vectors = await retriever.encode(["Thử việc tối đa bao lâu?", "maximum probation period"], [1.0, 0.5])
    assert len(vectors.dense) == len(vectors.sparse) == 2
    hits, _ = await retriever.search_vectors(vectors, "system", "hybrid", limit=3)
    assert hits[0].payload["chunk_id"] == "en:0000"
    only_vietnamese = await retriever.encode(["Thử việc tối đa bao lâu?"], dense=False)
    assert (await retriever.search_vectors(only_vietnamese, "system", "sparse", limit=3))[0] == []


@pytest.mark.asyncio
async def test_zero_weight_drops_a_branch(setup):
    client, embedder, encoder, _ = setup
    await index_document(client, COLLECTION, make_chunks("blld", TEXTS), "system", embedder, encoder)
    dense_only = Retriever(client, COLLECTION, embedder, encoder, retrieval_config(sparse_weight=0.0))
    hybrid = await dense_only.search("Nghỉ hằng năm", "system", mode="hybrid", limit=3)
    dense = await dense_only.search("Nghỉ hằng năm", "system", mode="dense", limit=3)
    assert [(h.id, h.score) for h in hybrid.hits] == [(h.id, h.score) for h in dense.hits]
