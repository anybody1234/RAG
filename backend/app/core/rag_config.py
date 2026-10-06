import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.config import REPO_ROOT

RAG_CONFIG_PATH = REPO_ROOT / "config" / "rag.toml"

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]
RetrievalMode = Literal["dense", "sparse", "hybrid"]


class ChunkingConfig(BaseModel):
    max_tokens: int
    overlap_ratio: float


class EmbeddingConfig(BaseModel):
    model: str
    dimensions: int


class SparseConfig(BaseModel):
    k1: float
    b: float
    avg_doc_len: float


class RetrievalConfig(BaseModel):
    mode: RetrievalMode
    prefetch_limit: int
    rrf_k: int
    top_k: int
    reranker: Literal["none", "llm"]


class IndexConfig(BaseModel):
    collection_prefix: str


class GenerationConfig(BaseModel):
    answer_model: str
    answer_reasoning_effort: ReasoningEffort
    rewrite_model: str
    prompt_version: str


class EvalConfig(BaseModel):
    judge_model: str
    judge_reasoning_effort: ReasoningEffort


class ModelPrice(BaseModel):
    """USD cho 1M token."""

    input: float
    output: float = 0.0


class RagConfig(BaseModel):
    """Toàn bộ siêu tham số RAG. `config_version` được ghi vào mọi trace và mọi kết quả eval."""

    config_version: str
    chunking: ChunkingConfig
    embedding: EmbeddingConfig
    sparse: SparseConfig
    retrieval: RetrievalConfig
    index: IndexConfig
    generation: GenerationConfig
    eval: EvalConfig
    prices: dict[str, ModelPrice]

    @property
    def collection_name(self) -> str:
        """Model và số chiều nằm trong tên collection: đổi model embedding thì index sang collection mới."""
        return f"{self.index.collection_prefix}_{self.embedding.model}_{self.embedding.dimensions}"

    def price(self, model: str) -> ModelPrice:
        if model not in self.prices:
            raise KeyError(f"chưa có giá của {model} trong [prices] của config/rag.toml")
        return self.prices[model]


def load_rag_config(path: Path = RAG_CONFIG_PATH) -> RagConfig:
    with path.open("rb") as f:
        return RagConfig.model_validate(tomllib.load(f))


@lru_cache
def get_rag_config() -> RagConfig:
    return load_rag_config()
