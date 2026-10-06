"""Kiểm tra môi trường dev: biến trong .env, OpenAI, Langfuse và các service Docker.

Chạy từ thư mục gốc của repo:
    python scripts/check_env.py

Không in giá trị key ra màn hình. Mọi lời gọi API ở đây đều miễn phí
(models.retrieve của OpenAI, auth_check của Langfuse).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import openai
from langfuse import Langfuse

from app.core.config import REPO_ROOT, get_settings
from app.core.rag_config import get_rag_config
from app.main import DEPENDENCY_CHECKS, _run_check

failures = 0


def report(ok: bool, name: str, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"  [{'OK' if ok else 'LỖI'}] {name}{f': {detail}' if detail else ''}")


def check_env_file() -> None:
    print(".env")
    settings = get_settings()
    report((REPO_ROOT / ".env").exists(), "file .env", "" if (REPO_ROOT / ".env").exists() else "chưa có, copy từ .env.example")
    required = {
        "OPENAI_API_KEY": settings.openai_api_key.get_secret_value(),
        "LANGFUSE_PUBLIC_KEY": settings.langfuse_public_key,
        "LANGFUSE_SECRET_KEY": settings.langfuse_secret_key.get_secret_value(),
        "JWT_SECRET": settings.jwt_secret.get_secret_value(),
    }
    for name, value in required.items():
        report(bool(value), name, "đã điền" if value else "còn trống")


def check_openai() -> None:
    print("OpenAI (các model trong config/rag.toml)")
    key = get_settings().openai_api_key.get_secret_value()
    if not key:
        report(False, "bỏ qua", "OPENAI_API_KEY còn trống")
        return
    config = get_rag_config()
    models = {
        config.generation.answer_model,
        config.query.model,
        config.rerank.model,
        config.eval.judge_model,
        config.embedding.model,
    }
    client = openai.OpenAI(api_key=key, timeout=20, max_retries=1)
    for model in sorted(models):
        try:
            client.models.retrieve(model)
        except openai.AuthenticationError:
            report(False, model, "key không hợp lệ")
            return
        except openai.NotFoundError:
            report(False, model, "key không có quyền dùng model này hoặc tên model sai")
        except openai.OpenAIError as exc:
            report(False, model, type(exc).__name__)
        else:
            report(True, model)


def check_langfuse() -> None:
    print("Langfuse")
    settings = get_settings()
    secret = settings.langfuse_secret_key.get_secret_value()
    if not (settings.langfuse_public_key and secret):
        report(False, "bỏ qua", "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY còn trống")
        return
    client = Langfuse(public_key=settings.langfuse_public_key, secret_key=secret, base_url=settings.langfuse_base_url)
    try:
        ok = client.auth_check()
    except Exception as exc:  # noqa: BLE001 - báo lỗi thay vì dừng script
        report(False, settings.langfuse_base_url, type(exc).__name__)
    else:
        report(ok, settings.langfuse_base_url, "" if ok else "sai key hoặc sai vùng (EU/US)")
    finally:
        client.shutdown()


async def check_services() -> None:
    print("Service (docker compose up -d)")
    results = await asyncio.gather(*(_run_check(check) for check in DEPENDENCY_CHECKS.values()))
    for name, result in zip(DEPENDENCY_CHECKS, results, strict=True):
        report(result == "ok", name, "" if result == "ok" else result)


def main() -> int:
    check_env_file()
    check_openai()
    check_langfuse()
    asyncio.run(check_services())
    print(f"\n{'Tất cả đều ổn.' if failures == 0 else f'{failures} mục chưa đạt.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
