"""Truy vấn Qdrant theo 3 chế độ: dense, sparse (BM25) và hybrid (prefetch dense + sparse, gộp RRF).

Một câu hỏi có thể có nhiều câu truy xuất (câu gốc và câu dịch, xem `query.py`). Mỗi câu truy xuất tạo một
nhánh cho mỗi loại vector; các nhánh được gộp bằng RRF có trọng số của Qdrant:
    score = Σ 1 / (k + hạng/w − 1),  w = trọng số câu truy xuất × trọng số loại vector (dense_weight, sparse_weight).
Với w = 1 là RRF thường: hạng 1 được 1/k điểm. w = 2 thì hạng 2 của nhánh đó ngang hạng 1 của nhánh w = 1.
Chỉ có một nhánh thì truy vấn thẳng, không gộp.

Mọi truy vấn đều lọc `user_id` ngay trong Qdrant. IDF của nhánh sparse cũng chỉ tính trên kho của user đó,
để tài liệu của user khác không làm lệch trọng số.
"""

import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.core.rag_config import RetrievalConfig, RetrievalMode
from app.retrieval.embedding import Embedder, EmbeddingUsage
from app.retrieval.index import DENSE, SPARSE, user_filter
from app.retrieval.sparse import SparseEncoder


@dataclass
class QueryVectors:
    texts: list[str]
    # Trọng số RRF của từng câu truy xuất, cùng thứ tự với `texts`.
    weights: list[float]
    dense: list[list[float]] | None
    sparse: list[models.SparseVector] | None
    usage: EmbeddingUsage
    embed_ms: float = 0.0
    sparse_ms: float = 0.0


@dataclass
class Hit:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    mode: RetrievalMode
    hits: list[Hit]
    usage: EmbeddingUsage
    # embed, sparse, search và total (tổng các bước), đơn vị ms.
    timings_ms: dict[str, float]


@dataclass
class _Branch:
    query: list[float] | models.SparseVector
    using: str
    weight: float
    params: models.SearchParams | None = None


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


class Retriever:
    def __init__(
        self,
        client: AsyncQdrantClient,
        collection: str,
        embedder: Embedder,
        encoder: SparseEncoder,
        config: RetrievalConfig,
    ):
        self.client, self.collection = client, collection
        self.embedder, self.encoder, self.config = embedder, encoder, config

    async def encode(
        self,
        queries: Sequence[str],
        weights: Sequence[float] | None = None,
        dense: bool = True,
        sparse: bool = True,
    ) -> QueryVectors:
        """Vector của các câu truy xuất. Mọi câu được embed trong cùng một request."""
        texts = [unicodedata.normalize("NFC", query) for query in queries]
        vectors = QueryVectors(
            texts=texts, weights=list(weights or [1.0] * len(texts)), dense=None, sparse=None, usage=EmbeddingUsage()
        )
        if dense:
            start = time.perf_counter()
            vectors.dense, vectors.usage = await self.embedder.embed_queries(texts)
            vectors.embed_ms = _elapsed_ms(start)
        if sparse:
            start = time.perf_counter()
            vectors.sparse = [self.encoder.encode_query(text) for text in texts]
            vectors.sparse_ms = _elapsed_ms(start)
        return vectors

    def _branches(self, vectors: QueryVectors, mode: RetrievalMode, flt: models.Filter) -> list[_Branch]:
        branches = []
        if mode != "sparse":
            assert vectors.dense is not None
            branches += [
                _Branch(vector, DENSE, weight * self.config.dense_weight)
                for vector, weight in zip(vectors.dense, vectors.weights, strict=True)
            ]
        if mode != "dense":
            assert vectors.sparse is not None
            params = models.SearchParams(idf=models.IdfCorpusParams(corpus=flt))
            branches += [
                _Branch(vector, SPARSE, weight * self.config.sparse_weight, params)
                for vector, weight in zip(vectors.sparse, vectors.weights, strict=True)
                if vector.indices  # câu không có term nào (chỉ có dấu câu) thì bỏ nhánh sparse
            ]
        return [branch for branch in branches if branch.weight > 0]

    async def search_vectors(
        self,
        vectors: QueryVectors,
        user_id: str,
        mode: RetrievalMode,
        limit: int,
        with_payload: bool | list[str] = True,
    ) -> tuple[list[Hit], float]:
        """Trả về các chunk xếp hạng giảm dần và thời gian truy vấn Qdrant (ms)."""
        flt = user_filter(user_id)
        branches = self._branches(vectors, mode, flt)
        start = time.perf_counter()
        if not branches:
            return [], 0.0
        if len(branches) == 1:
            branch = branches[0]
            response = await self.client.query_points(
                self.collection, query=branch.query, using=branch.using, query_filter=flt,
                search_params=branch.params, limit=limit, with_payload=with_payload,
            )
        else:
            prefetch_limit = max(self.config.prefetch_limit, limit)
            weights = [branch.weight for branch in branches]
            response = await self.client.query_points(
                self.collection,
                prefetch=[
                    models.Prefetch(
                        query=branch.query, using=branch.using, filter=flt, limit=prefetch_limit, params=branch.params
                    )
                    for branch in branches
                ],
                query=models.RrfQuery(rrf=models.Rrf(
                    k=self.config.rrf_k,
                    # Trọng số đều thì không gửi, giữ đúng RRF gốc của Qdrant.
                    weights=None if len(set(weights)) == 1 else weights,
                )),
                query_filter=flt,
                limit=limit,
                with_payload=with_payload,
            )
        search_ms = _elapsed_ms(start)
        hits = [Hit(id=str(point.id), score=point.score, payload=point.payload or {}) for point in response.points]
        return hits, search_ms

    async def search(
        self, query: str, user_id: str, mode: RetrievalMode | None = None, limit: int | None = None
    ) -> SearchResult:
        """Truy xuất bằng một câu, không gọi LLM."""
        mode = mode or self.config.mode
        vectors = await self.encode([query], dense=mode != "sparse", sparse=mode != "dense")
        hits, search_ms = await self.search_vectors(vectors, user_id, mode, limit or self.config.top_k)
        timings = {"embed": vectors.embed_ms, "sparse": vectors.sparse_ms, "search": search_ms}
        timings["total"] = sum(timings.values())
        return SearchResult(mode=mode, hits=hits, usage=vectors.usage, timings_ms=timings)
