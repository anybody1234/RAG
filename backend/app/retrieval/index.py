"""Collection Qdrant: dense + sparse trong cùng collection, payload có user_id để lọc ngay trong Qdrant."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.ingestion.models import Chunk
from app.retrieval.embedding import Embedder, EmbeddingUsage
from app.retrieval.sparse import SparseEncoder

DENSE = "dense"
SPARSE = "sparse"
# Văn bản luật của bộ dev được index dưới user này.
SYSTEM_USER_ID = "system"
_POINT_NAMESPACE = uuid.UUID("6f1c8a52-3d4e-4b7a-9c1f-2a5e8d7b0c43")
_UPSERT_BATCH = 64


def point_id(user_id: str, doc_id: str, content_hash: str) -> str:
    """ID ổn định theo nội dung: index lại cùng chunk thì ghi đè đúng point cũ, không sinh bản trùng."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{user_id}:{doc_id}:{content_hash}"))


def embedding_text(chunk: Chunk, with_title: bool) -> str:
    """Text đem embed và mã hoá sparse. `with_title` thêm tên văn bản, số hiệu và heading_path lên đầu."""
    if not with_title:
        return chunk.text
    name = f"{chunk.title} ({chunk.so_hieu})" if chunk.so_hieu else chunk.title
    return f"{name} | {chunk.heading_path}\n{chunk.text}"


def user_filter(user_id: str) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))])


class IndexMismatchError(RuntimeError):
    """Collection chưa có, hoặc được index bằng tham số khác config hiện tại."""


async def check_collection(client: AsyncQdrantClient, name: str, signature: dict[str, Any]) -> None:
    """Báo lỗi khi collection chưa có hoặc chữ ký index (`RagConfig.index_signature()`) không khớp."""
    if not await client.collection_exists(name):
        raise IndexMismatchError(f"chưa có collection {name}: chạy python scripts/index.py với cùng config")
    stored = ((await client.get_collection(name)).config.metadata or {}).get("index_signature")
    if stored != signature:
        raise IndexMismatchError(
            f"collection {name} được index với {stored}, config hiện tại là {signature}. "
            "Đổi index.collection_prefix cho thí nghiệm, hoặc index lại với --recreate."
        )


async def ensure_collection(
    client: AsyncQdrantClient, name: str, signature: dict[str, Any], recreate: bool = False
) -> bool:
    """Tạo collection nếu chưa có (hoặc xoá rồi tạo lại khi `recreate`). Trả về True khi vừa tạo.

    Chữ ký index được lưu trong metadata của collection; collection đã có mà khác chữ ký thì báo lỗi, để một
    thí nghiệm không ghi đè lên index của thí nghiệm khác.
    """
    if await client.collection_exists(name):
        if not recreate:
            await check_collection(client, name, signature)
            return False
        await client.delete_collection(name)
    await client.create_collection(
        name,
        vectors_config={
            DENSE: models.VectorParams(size=signature["embedding"]["dimensions"], distance=models.Distance.COSINE)
        },
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        metadata={"index_signature": signature},
    )
    await client.create_payload_index(
        name, "user_id", models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True)
    )
    await client.create_payload_index(name, "doc_id", models.PayloadSchemaType.KEYWORD)
    return True


@dataclass
class IndexReport:
    chunks: int
    removed: int
    usage: EmbeddingUsage


def _document_filter(user_id: str, doc_id: str) -> models.Filter:
    return models.Filter(must=[
        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
    ])


async def index_document(
    client: AsyncQdrantClient,
    collection: str,
    chunks: Sequence[Chunk],
    user_id: str,
    embedder: Embedder,
    encoder: SparseEncoder,
    embed_title: bool = False,
) -> IndexReport:
    """Embed và upsert mọi chunk của một văn bản, rồi xoá các point cũ của văn bản không còn trong lần này.

    Chạy lại với cùng chunk thì kết quả không đổi (idempotent); embedding lấy từ cache nên không tốn tiền.
    """
    doc_ids = {chunk.doc_id for chunk in chunks}
    if len(doc_ids) != 1:
        raise ValueError(f"cần chunk của đúng một văn bản, nhận được {sorted(doc_ids)}")
    doc_id = doc_ids.pop()
    texts = [embedding_text(chunk, embed_title) for chunk in chunks]
    dense, usage = await embedder.embed_documents(texts)
    points = [
        models.PointStruct(
            id=point_id(user_id, doc_id, chunk.content_hash),
            vector={DENSE: vector, SPARSE: encoder.encode_document(text)},
            payload=chunk.model_dump(mode="json") | {"user_id": user_id},
        )
        for chunk, text, vector in zip(chunks, texts, dense, strict=True)
    ]
    for start in range(0, len(points), _UPSERT_BATCH):
        await client.upsert(collection, points[start : start + _UPSERT_BATCH])

    stale = models.Filter(
        must=_document_filter(user_id, doc_id).must,
        must_not=[models.HasIdCondition(has_id=[point.id for point in points])],
    )
    removed = (await client.count(collection, count_filter=stale, exact=True)).count
    if removed:
        await client.delete(collection, models.FilterSelector(filter=stale))
    return IndexReport(chunks=len(points), removed=removed, usage=usage)
