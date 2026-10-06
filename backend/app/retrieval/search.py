"""Truy vấn Qdrant theo 3 chế độ: dense, sparse (BM25) và hybrid (prefetch dense + sparse, gộp RRF).

Mọi truy vấn đều lọc `user_id` ngay trong Qdrant. IDF của nhánh sparse cũng chỉ tính trên kho của user đó,
để tài liệu của user khác không làm lệch trọng số.
"""

import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.core.rag_config import RetrievalConfig, RetrievalMode
from app.retrieval.embedding import Embedder, EmbeddingUsage
from app.retrieval.index import DENSE, SPARSE, user_filter
from app.retrieval.sparse import SparseEncoder


@dataclass
class QueryVectors:
    dense: list[float] | None
    sparse: models.SparseVector | None
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

    async def encode(self, query: str, dense: bool = True, sparse: bool = True) -> QueryVectors:
        query = unicodedata.normalize("NFC", query)
        vectors = QueryVectors(dense=None, sparse=None, usage=EmbeddingUsage())
        if dense:
            start = time.perf_counter()
            vectors.dense, vectors.usage = await self.embedder.embed_query(query)
            vectors.embed_ms = _elapsed_ms(start)
        if sparse:
            start = time.perf_counter()
            vectors.sparse = self.encoder.encode_query(query)
            vectors.sparse_ms = _elapsed_ms(start)
        return vectors

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
        sparse_params = models.SearchParams(idf=models.IdfCorpusParams(corpus=flt))
        start = time.perf_counter()
        if mode == "dense":
            assert vectors.dense is not None
            response = await self.client.query_points(
                self.collection, query=vectors.dense, using=DENSE, query_filter=flt, limit=limit,
                with_payload=with_payload,
            )
        elif mode == "sparse":
            assert vectors.sparse is not None
            response = await self.client.query_points(
                self.collection, query=vectors.sparse, using=SPARSE, query_filter=flt, limit=limit,
                search_params=sparse_params, with_payload=with_payload,
            )
        else:
            assert vectors.dense is not None and vectors.sparse is not None
            prefetch_limit = max(self.config.prefetch_limit, limit)
            response = await self.client.query_points(
                self.collection,
                prefetch=[
                    models.Prefetch(query=vectors.dense, using=DENSE, filter=flt, limit=prefetch_limit),
                    models.Prefetch(
                        query=vectors.sparse, using=SPARSE, filter=flt, limit=prefetch_limit, params=sparse_params
                    ),
                ],
                query=models.RrfQuery(rrf=models.Rrf(k=self.config.rrf_k)),
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
        mode = mode or self.config.mode
        vectors = await self.encode(query, dense=mode != "sparse", sparse=mode != "dense")
        hits, search_ms = await self.search_vectors(vectors, user_id, mode, limit or self.config.top_k)
        timings = {"embed": vectors.embed_ms, "sparse": vectors.sparse_ms, "search": search_ms}
        timings["total"] = sum(timings.values())
        return SearchResult(mode=mode, hits=hits, usage=vectors.usage, timings_ms=timings)
