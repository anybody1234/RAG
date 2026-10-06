from app.core.rag_config import load_rag_config


def test_repo_rag_config_is_valid():
    config = load_rag_config()
    assert config.config_version
    assert config.retrieval.top_k <= config.retrieval.prefetch_limit
    assert 0 <= config.chunking.overlap_ratio < 1
