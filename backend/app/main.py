import asyncio
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.rag_config import get_rag_config

CHECK_TIMEOUT_SECONDS = 3

app = FastAPI(title="RAG Chatbot")


async def check_postgres() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def check_qdrant() -> None:
    client = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=CHECK_TIMEOUT_SECONDS)
    try:
        await client.get_collections()
    finally:
        await client.close()


async def check_redis() -> None:
    client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=CHECK_TIMEOUT_SECONDS)
    try:
        await client.ping()
    finally:
        await client.aclose()


DEPENDENCY_CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "postgres": check_postgres,
    "qdrant": check_qdrant,
    "redis": check_redis,
}


async def _run_check(check: Callable[[], Awaitable[None]]) -> str:
    try:
        await asyncio.wait_for(check(), CHECK_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - health check báo lỗi thay vì ném ra
        return f"error: {type(exc).__name__}"
    return "ok"


@app.get("/api/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok", "config_version": get_rag_config().config_version}


@app.get("/api/health/ready")
async def ready() -> JSONResponse:
    results = await asyncio.gather(*(_run_check(check) for check in DEPENDENCY_CHECKS.values()))
    services = dict(zip(DEPENDENCY_CHECKS, results, strict=True))
    healthy = all(result == "ok" for result in services.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "services": services},
    )
