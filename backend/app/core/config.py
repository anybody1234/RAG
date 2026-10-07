import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
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
    # Trần chi phí API (USD), chặn trước mỗi lời gọi (app/core/costs.py): trong một ngày, và cộng dồn cả dự án.
    # Trần dự án đặt theo số dư tài khoản (07/10/2026: còn $3.26, chừa $0.45 cho khoản đã tiêu trước khi có ledger).
    daily_cost_limit_usd: float = 0.50
    project_cost_limit_usd: float = 2.80
    # Ledger chi phí. Mặc định ở thư mục của user, để mọi checkout và worktree của repo dùng chung một trần.
    cost_ledger_path: Path = Path.home() / ".rag-chatbot" / "costs.sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_secret(name: str) -> str:
    """Giá trị của biến môi trường `name`, hoặc của dòng `name=` trong .env. Dùng cho key mà tên biến nằm trong
    config (ví dụ `eval.judge_api_key_env` của provider judge), nên không khai báo trước được trong Settings."""
    value = os.environ.get(name) or dotenv_values(REPO_ROOT / ".env").get(name)
    if not value:
        raise KeyError(f"chưa đặt {name} trong biến môi trường hoặc .env")
    return value
