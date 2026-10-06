from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Cấu hình môi trường, đọc từ biến môi trường hoặc file .env ở gốc repo."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: SecretStr = SecretStr("")
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_base_url: str = "https://cloud.langfuse.com"

    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr("")
    daily_cost_limit_usd: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
