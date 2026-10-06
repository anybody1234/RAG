"""Gọi OpenAI embeddings: gửi theo batch, cache theo hash nội dung, đếm token và chi phí.

Retry dùng cơ chế có sẵn của SDK `openai` (`max_retries`): thử lại với backoff khi gặp 408/409/429/5xx,
timeout hoặc lỗi kết nối, và tôn trọng header Retry-After.
"""

import hashlib
import sqlite3
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from openai import AsyncOpenAI

from app.core.config import REPO_ROOT, get_settings
from app.core.rag_config import RagConfig
from app.ingestion.tokens import TokenCounter

CACHE_PATH = REPO_ROOT / "data" / "cache" / "embeddings.sqlite"
# Giới hạn của API: 2048 input và 300k token mỗi request. Để dư cho an toàn.
MAX_BATCH_INPUTS = 256
MAX_BATCH_TOKENS = 200_000
MAX_RETRIES = 5
TIMEOUT_SECONDS = 60


@dataclass
class EmbeddingUsage:
    requests: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    # Số text lấy từ cache, không gọi API.
    cached: int = 0

    def __iadd__(self, other: "EmbeddingUsage") -> Self:
        self.requests += other.requests
        self.tokens += other.tokens
        self.cost_usd += other.cost_usd
        self.cached += other.cached
        return self


def content_hash(text: str) -> str:
    """Giống `Chunk.content_hash`."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_batches(token_counts: Sequence[int], max_inputs: int, max_tokens: int) -> list[range]:
    """Chia các input liền nhau thành batch không quá `max_inputs` input và `max_tokens` token."""
    batches: list[range] = []
    start = size = 0
    for i, count in enumerate(token_counts):
        if i > start and (i - start >= max_inputs or size + count > max_tokens):
            batches.append(range(start, i))
            start, size = i, 0
        size += count
    if start < len(token_counts):
        batches.append(range(start, len(token_counts)))
    return batches


class EmbeddingCache:
    """SQLite: (model, số chiều, sha256 của text) -> vector float32."""

    def __init__(self, path: Path = CACHE_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS embeddings (model TEXT, dimensions INTEGER, hash TEXT, vector BLOB, "
            "PRIMARY KEY (model, dimensions, hash))"
        )

    def get_many(self, model: str, dimensions: int, hashes: Sequence[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        unique = list(dict.fromkeys(hashes))
        for start in range(0, len(unique), 500):
            part = unique[start : start + 500]
            rows = self._db.execute(
                f"SELECT hash, vector FROM embeddings WHERE model = ? AND dimensions = ? "
                f"AND hash IN ({','.join('?' * len(part))})",
                [model, dimensions, *part],
            )
            for key, blob in rows:
                vector = array("f")
                vector.frombytes(blob)
                found[key] = vector.tolist()
        return found

    def put_many(self, model: str, dimensions: int, vectors: dict[str, list[float]]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?)",
                [(model, dimensions, key, array("f", vector).tobytes()) for key, vector in vectors.items()],
            )

    def close(self) -> None:
        self._db.close()


class Embedder:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        dimensions: int,
        price_per_1m_tokens: float,
        cache: EmbeddingCache | None = None,
    ):
        self.client, self.model, self.dimensions = client, model, dimensions
        self.price_per_1m_tokens = price_per_1m_tokens
        self.cache = cache
        self._count_tokens = TokenCounter(model)

    async def _call(self, texts: list[str]) -> tuple[list[list[float]], EmbeddingUsage]:
        response = await self.client.embeddings.create(input=texts, model=self.model, dimensions=self.dimensions)
        tokens = response.usage.prompt_tokens
        usage = EmbeddingUsage(requests=1, tokens=tokens, cost_usd=tokens * self.price_per_1m_tokens / 1e6)
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)], usage

    async def embed_documents(self, texts: Sequence[str]) -> tuple[list[list[float]], EmbeddingUsage]:
        """Embed nhiều text. Text đã có trong cache (cùng model, số chiều, nội dung) thì không gọi API."""
        hashes = [content_hash(text) for text in texts]
        known = self.cache.get_many(self.model, self.dimensions, hashes) if self.cache else {}
        usage = EmbeddingUsage(cached=sum(key in known for key in hashes))
        # Text trùng nhau chỉ gửi một lần.
        missing = {key: text for key, text in zip(hashes, texts, strict=True) if key not in known}
        keys, pending = list(missing), list(missing.values())
        batches = make_batches([self._count_tokens(text) for text in pending], MAX_BATCH_INPUTS, MAX_BATCH_TOKENS)
        for batch in batches:
            vectors, batch_usage = await self._call([pending[i] for i in batch])
            new = {keys[i]: vector for i, vector in zip(batch, vectors, strict=True)}
            if self.cache:
                self.cache.put_many(self.model, self.dimensions, new)
            known |= new
            usage += batch_usage
        return [known[key] for key in hashes], usage

    async def embed_queries(self, texts: Sequence[str]) -> tuple[list[list[float]], EmbeddingUsage]:
        """Embed các câu truy xuất của một câu hỏi (câu gốc, câu dịch) trong một request.

        Không dùng cache, để latency đo được là latency thật của lần gọi API.
        """
        if not texts or not all(text.strip() for text in texts):
            raise ValueError("câu hỏi rỗng")
        return await self._call(list(texts))


def build_embedder(config: RagConfig, cache: EmbeddingCache | None = None) -> Embedder:
    client = AsyncOpenAI(
        api_key=get_settings().openai_api_key.get_secret_value(),
        max_retries=MAX_RETRIES,
        timeout=TIMEOUT_SECONDS,
    )
    model = config.embedding.model
    return Embedder(client, model, config.embedding.dimensions, config.price(model).input, cache)
