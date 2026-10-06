import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.config import REPO_ROOT

RAG_CONFIG_PATH = REPO_ROOT / "config" / "rag.toml"

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


class ChunkingConfig(BaseModel):
    max_tokens: int
    overlap_ratio: float


class EmbeddingConfig(BaseModel):
    model: str
    dimensions: int


class RetrievalConfig(BaseModel):
    mode: Literal["dense", "sparse", "hybrid"]
    prefetch_limit: int
    top_k: int
    reranker: Literal["none", "llm"]


class GenerationConfig(BaseModel):
    answer_model: str
    answer_reasoning_effort: ReasoningEffort
    rewrite_model: str
    prompt_version: str


class EvalConfig(BaseModel):
    judge_model: str
    judge_reasoning_effort: ReasoningEffort


class RagConfig(BaseModel):
    """Toàn bộ siêu tham số RAG. `config_version` được ghi vào mọi trace và mọi kết quả eval."""

    config_version: str
    chunking: ChunkingConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    generation: GenerationConfig
    eval: EvalConfig


def load_rag_config(path: Path = RAG_CONFIG_PATH) -> RagConfig:
    with path.open("rb") as f:
        return RagConfig.model_validate(tomllib.load(f))


@lru_cache
def get_rag_config() -> RagConfig:
    return load_rag_config()
