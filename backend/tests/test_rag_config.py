import pytest
from pydantic import ValidationError

from app.core.rag_config import load_rag_config


def test_repo_rag_config_is_valid():
    config = load_rag_config()
    assert config.config_version
    assert config.retrieval.top_k <= config.retrieval.prefetch_limit
    assert 0 <= config.chunking.overlap_ratio < 1


def test_collection_name_carries_embedding_model_and_dimensions():
    config = load_rag_config()
    assert config.collection_name.endswith(f"_{config.embedding.model}_{config.embedding.dimensions}")
    assert config.price(config.embedding.model).input > 0


def test_overrides_need_their_own_config_version():
    with pytest.raises(ValueError, match="config_version"):
        load_rag_config(overrides=["retrieval.rrf_k=20"])
    config = load_rag_config(overrides=["config_version=v-test", "retrieval.rrf_k=20", "query.translate=true"])
    assert (config.config_version, config.retrieval.rrf_k, config.query.translate) == ("v-test", 20, True)
    # Giá không ảnh hưởng kết quả RAG nên đổi giá không cần version mới.
    assert load_rag_config(overrides=["prices.gpt-6-luna.input=0.2"]).price("gpt-6-luna").input == 0.2


def test_override_with_unknown_key_is_rejected():
    with pytest.raises(ValidationError):
        load_rag_config(overrides=["config_version=v-test", "retrieval.rrfk=20"])
    with pytest.raises(ValueError):
        load_rag_config(overrides=["retrieval.rrf_k"])


def test_index_signature_ignores_query_time_settings():
    base = load_rag_config()
    query_time = load_rag_config(overrides=["config_version=v-test", "retrieval.rrf_k=2", "query.translate=true"])
    chunking = load_rag_config(overrides=["config_version=v-test", "chunking.max_tokens=400"])
    assert base.index_signature() == query_time.index_signature() != chunking.index_signature()
