import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.core.config import REPO_ROOT

RAG_CONFIG_PATH = REPO_ROOT / "config" / "rag.toml"

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]
RetrievalMode = Literal["dense", "sparse", "hybrid"]
# Tier xử lý của OpenAI. "flex" rẻ bằng nửa nhưng chậm hơn và có thể trả 429 khi thiếu tài nguyên, nên chỉ dùng
# cho việc không đo latency (judge), không dùng cho bước trả lời.
ServiceTier = Literal["default", "flex"]


def price_key(model: str, service_tier: str | None = None) -> str:
    """Khoá trong [prices]: "<model>" cho tier mặc định, "<model>@flex" cho tier flex."""
    return f"{model}@{service_tier}" if service_tier and service_tier not in ("default", "auto") else model


class _Section(BaseModel):
    # Sai tên khoá (trong file hoặc trong --set) thì báo lỗi thay vì lặng lẽ bỏ qua.
    model_config = ConfigDict(extra="forbid")


class ChunkingConfig(_Section):
    max_tokens: int
    overlap_ratio: float


class EmbeddingConfig(_Section):
    model: str
    dimensions: int


class SparseConfig(_Section):
    k1: float
    b: float
    avg_doc_len: float


class QueryConfig(_Section):
    model: str
    reasoning_effort: ReasoningEffort
    prompt_version: str
    rewrite: Literal["none", "concat", "llm"]
    rewrite_timeout_ms: int
    translate: bool
    translation_weight: float


class RetrievalConfig(_Section):
    mode: RetrievalMode
    prefetch_limit: int
    rrf_k: int
    dense_weight: float
    sparse_weight: float
    top_k: int
    reranker: Literal["none", "llm"]


class RerankConfig(_Section):
    model: str
    reasoning_effort: ReasoningEffort
    prompt_version: str
    candidates: int
    max_chunk_tokens: int


class IndexConfig(_Section):
    collection_prefix: str
    embed_title: bool


class GenerationConfig(_Section):
    answer_model: str
    answer_reasoning_effort: ReasoningEffort
    prompt_version: str
    max_output_tokens: int


class EvalConfig(_Section):
    judge_model: str
    judge_reasoning_effort: ReasoningEffort
    judge_prompt_version: str
    judge_max_output_tokens: int
    judge_service_tier: ServiceTier


class ModelPrice(_Section):
    """USD cho 1M token. Token đầu vào chia 3 loại: thường (`input`), đọc từ prompt cache (`cached_input`) và
    ghi vào prompt cache (`cache_write`). Thiếu giá của loại nào thì tính bằng giá `input`."""

    input: float
    output: float = 0.0
    cached_input: float | None = None
    cache_write: float | None = None

    def cost(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0, cache_write_tokens: int = 0) -> float:
        """`input_tokens` là tổng token đầu vào, đã gồm token đọc và ghi cache (giống `usage` của API)."""
        ordinary = input_tokens - cached_tokens - cache_write_tokens
        cached_price = self.input if self.cached_input is None else self.cached_input
        write_price = self.input if self.cache_write is None else self.cache_write
        return (
            ordinary * self.input + cached_tokens * cached_price + cache_write_tokens * write_price
            + output_tokens * self.output
        ) / 1e6


class RagConfig(_Section):
    """Toàn bộ siêu tham số RAG. `config_version` được ghi vào mọi trace và mọi kết quả eval."""

    config_version: str
    chunking: ChunkingConfig
    embedding: EmbeddingConfig
    sparse: SparseConfig
    query: QueryConfig
    retrieval: RetrievalConfig
    rerank: RerankConfig
    index: IndexConfig
    generation: GenerationConfig
    eval: EvalConfig
    prices: dict[str, ModelPrice]

    @property
    def collection_name(self) -> str:
        """Model và số chiều nằm trong tên collection: đổi model embedding thì index sang collection mới."""
        return f"{self.index.collection_prefix}_{self.embedding.model}_{self.embedding.dimensions}"

    def index_signature(self) -> dict[str, Any]:
        """Các tham số quyết định nội dung index. Hai config có cùng chữ ký thì dùng chung được một collection."""
        return {
            "chunking": self.chunking.model_dump(),
            "embedding": self.embedding.model_dump(),
            "sparse": self.sparse.model_dump(),
            "embed_title": self.index.embed_title,
        }

    def price(self, model: str, service_tier: str | None = None) -> ModelPrice:
        key = price_key(model, service_tier)
        if key not in self.prices:
            raise KeyError(f"chưa có giá của {key} trong [prices] của config/rag.toml")
        return self.prices[key]


def apply_overrides(data: dict[str, Any], overrides: list[str]) -> None:
    """Ghi đè giá trị theo dạng "retrieval.rrf_k=20". Giá trị đọc theo cú pháp TOML, không hợp lệ thì là chuỗi."""
    for override in overrides:
        key, sep, raw = override.partition("=")
        if not sep or not key:
            raise ValueError(f"override phải có dạng khoá=giá_trị: {override!r}")
        try:
            value = tomllib.loads(f"v = {raw}")["v"]
        except tomllib.TOMLDecodeError:
            value = raw
        *parents, last = key.strip().split(".")
        node = data
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value


def load_rag_config(path: Path = RAG_CONFIG_PATH, overrides: list[str] | None = None) -> RagConfig:
    """Đọc config. Thí nghiệm ghi đè giá trị bằng `overrides` thì phải đặt `config_version` riêng, để kết quả
    eval không bị lưu nhầm dưới version của config gốc."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    if overrides:
        base_version = data["config_version"]
        apply_overrides(data, overrides)
        changed = [o for o in overrides if not o.startswith(("config_version=", "prices."))]
        if changed and data["config_version"] == base_version:
            raise ValueError(f"thí nghiệm đổi {changed} nên phải đặt config_version mới (--set config_version=...)")
    return RagConfig.model_validate(data)


@lru_cache
def get_rag_config() -> RagConfig:
    return load_rag_config()
