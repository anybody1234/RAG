"""Trần chi phí API, chặn TRƯỚC khi gọi: trần theo ngày (`DAILY_COST_LIMIT_USD`) và trần cả dự án
(`PROJECT_COST_LIMIT_USD`, tổng mọi dòng trong ledger).

`BudgetedClient` bọc client của SDK `openai`. Trước mỗi lời gọi `responses.create`, `chat.completions.create` hoặc
`embeddings.create`, nó ước tính chi phí tối đa của lời gọi đó: token đầu vào (đếm bằng tokenizer, tính theo giá
input chưa cache) cộng số token đầu ra tối đa. Nếu chi phí đã tiêu cộng mức tối đa này vượt một trong hai trần thì
ném `BudgetExceededError` và không gửi request. Sau lời gọi, chi phí thật (theo `usage`) được ghi vào `CostLedger`.

Lời gọi lỗi: provider từ chối request (HTTP 4xx, gồm 429) thì không tính tiền, ghi $0. Mọi trường hợp khác (timeout,
huỷ do quá hạn, mất kết nối, lỗi 5xx, stream đứt giữa chừng) không biết provider đã sinh bao nhiêu token, nên ghi
mức tối đa đã giữ chỗ: ghi dư an toàn hơn ghi thiếu khi ngân sách sát.

Ledger là file SQLite (`COST_LEDGER_PATH`, mặc định ở thư mục của user để mọi checkout và worktree dùng chung), nên
chi phí cộng dồn qua mọi lần chạy script. Mỗi dòng ghi cả provider và số token, nên cũng dùng để đếm quota theo ngày
của provider miễn phí (`usage_since`). Ledger chỉ biết các lời gọi đi qua `BudgetedClient`; lời gọi từ nơi khác
dùng chung API key thì không tính được.
"""

import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import openai
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.rag_config import ModelPrice, price_key
from app.ingestion.tokens import TokenCounter

# Lời gọi không đặt số token đầu ra tối đa (viết lại câu hỏi, rerank: đầu ra JSON ngắn) thì giả định chừng này.
DEFAULT_MAX_OUTPUT_TOKENS = 4096
# Tokenizer cl100k_base (fallback của TokenCounter) đếm tiếng Việt nhiều token hơn tokenizer của GPT mới, nên ước
# tính đầu vào thường dư. Nhân thêm hệ số cho phần khung message mà tokenizer không thấy.
INPUT_MARGIN = 1.1
_TERMINAL_EVENTS = ("response.completed", "response.incomplete", "response.failed")


class BudgetExceededError(RuntimeError):
    """Lời gọi có thể làm chi phí vượt trần. Không kế thừa OpenAIError, để không bị bắt như lỗi API."""


QuotaReset = Literal["utc", "local", "pacific"]


def _pacific_utc_offset(now_utc: datetime) -> timedelta:
    """Giờ Pacific (Mỹ): UTC−7 từ Chủ nhật thứ hai của tháng 3 (2:00) tới Chủ nhật đầu tháng 11 (2:00), còn lại
    UTC−8. Tự tính để không phụ thuộc gói tzdata (Windows không có sẵn cơ sở dữ liệu múi giờ)."""
    year = now_utc.year
    march_8, november_1 = date(year, 3, 8), date(year, 11, 1)
    dst_start = datetime.combine(march_8 + timedelta(days=(6 - march_8.weekday()) % 7), datetime.min.time(), UTC)
    dst_end = datetime.combine(november_1 + timedelta(days=(6 - november_1.weekday()) % 7), datetime.min.time(), UTC)
    in_dst = dst_start + timedelta(hours=10) <= now_utc < dst_end + timedelta(hours=9)
    return timedelta(hours=-7 if in_dst else -8)


def quota_window_start(reset: QuotaReset, now_utc: datetime | None = None) -> datetime:
    """Thời điểm (UTC) bắt đầu "ngày" quota hiện tại của provider."""
    now_utc = now_utc or datetime.now(UTC)
    if reset == "utc":
        offset = timedelta(0)
    elif reset == "pacific":
        offset = _pacific_utc_offset(now_utc)
    else:
        offset = now_utc.astimezone().utcoffset() or timedelta(0)
    local = now_utc + offset
    return datetime.combine(local.date(), datetime.min.time(), UTC) - offset


class CostLedger:
    """SQLite: mỗi lời gọi API (kể cả lời gọi lỗi) là một dòng, có chi phí, provider, model và số token."""

    def __init__(
        self,
        limit_usd: float,
        path: Path,
        project_limit_usd: float | None = None,
        today: Callable[[], date] = date.today,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.limit_usd, self.project_limit_usd, self.path, self._today = limit_usd, project_limit_usd, path, today
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS costs (day TEXT, at TEXT, model TEXT, cost_usd REAL)")
        # Cột thêm sau (07/10/2026); dòng cũ là lời gọi OpenAI, không có token và mốc thời gian dạng số.
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(costs)")}
        for column, kind in (("provider", "TEXT DEFAULT 'openai'"), ("input_tokens", "INTEGER DEFAULT 0"),
                             ("output_tokens", "INTEGER DEFAULT 0"), ("ts", "REAL")):
            if column not in existing:
                self._db.execute(f"ALTER TABLE costs ADD COLUMN {column} {kind}")
        self._db.commit()
        # Mức tối đa của các lời gọi đang chạy trong process này (gọi song song).
        self._pending = 0.0

    def spent_today(self) -> float:
        row = self._db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM costs WHERE day = ?", [self._today().isoformat()])
        return float(row.fetchone()[0])

    def spent_total(self) -> float:
        return float(self._db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM costs").fetchone()[0])

    def reserve(self, worst_case_usd: float, model: str) -> None:
        spent = self.spent_today()
        if spent + self._pending + worst_case_usd > self.limit_usd:
            raise BudgetExceededError(
                f"đã tiêu ${spent:.4f} hôm nay; lời gọi {model} có thể tốn tới ${worst_case_usd:.4f}, vượt trần "
                f"${self.limit_usd:.2f}/ngày (DAILY_COST_LIMIT_USD)"
            )
        total = self.spent_total()
        if self.project_limit_usd is not None and total + self._pending + worst_case_usd > self.project_limit_usd:
            raise BudgetExceededError(
                f"dự án đã tiêu ${total:.4f}; lời gọi {model} có thể tốn tới ${worst_case_usd:.4f}, vượt trần "
                f"${self.project_limit_usd:.2f} của cả dự án (PROJECT_COST_LIMIT_USD)"
            )
        self._pending += worst_case_usd

    def settle(
        self,
        reserved_usd: float,
        cost_usd: float,
        model: str,
        provider: str = "openai",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self._pending = max(0.0, self._pending - reserved_usd)
        now = datetime.now().astimezone()
        with self._db:
            self._db.execute(
                "INSERT INTO costs (day, at, model, cost_usd, provider, input_tokens, output_tokens, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [self._today().isoformat(), now.isoformat(timespec="seconds"), model, cost_usd, provider,
                 input_tokens, output_tokens, now.timestamp()],
            )

    def usage_since(self, provider: str, model: str, since: datetime) -> tuple[int, int]:
        """(số request, số token vào + ra) của một model ở một provider từ thời điểm `since`. Request lỗi cũng
        được đếm, vì provider có thể tính chúng vào quota."""
        row = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens + output_tokens), 0) FROM costs "
            "WHERE provider = ? AND model = ? AND ts >= ?",
            [provider, model, since.timestamp()],
        ).fetchone()
        return int(row[0]), int(row[1])


def cost_on_error(exc: BaseException, reserved_usd: float) -> float:
    """Chi phí ghi vào ledger khi lời gọi ném lỗi: $0 nếu provider từ chối request (4xx), còn lại ghi mức tối đa."""
    if isinstance(exc, openai.APIStatusError) and 400 <= exc.status_code < 500:
        return 0.0
    return reserved_usd


def _price(prices: dict[str, ModelPrice], model: str, service_tier: str | None = None) -> ModelPrice:
    key = price_key(model, service_tier)
    if key not in prices:
        raise KeyError(f"chưa có giá của {key} trong [prices] của config/rag.toml")
    return prices[key]


def _count_input(model: str, *parts: Any) -> int:
    text = "\n".join(p if isinstance(p, str) else json.dumps(p, ensure_ascii=False) for p in parts if p is not None)
    return int(TokenCounter(model)(text) * INPUT_MARGIN) + 50


class _Budgeted:
    """Phần chung: giữ chỗ trước khi gọi, ghi chi phí sau khi gọi."""

    def __init__(self, inner: Any, ledger: CostLedger, prices: dict[str, ModelPrice], provider: str):
        self._inner, self._ledger, self._prices, self._provider = inner, ledger, prices, provider

    async def _call(self, kwargs: dict[str, Any], worst: float, model: str) -> Any:
        self._ledger.reserve(worst, model)
        try:
            return await self._inner.create(**kwargs)
        except BaseException as exc:  # gồm cả CancelledError khi bị huỷ do quá hạn
            self._ledger.settle(worst, cost_on_error(exc, worst), model, self._provider)
            raise

    def _settle(self, worst: float, usage: Any, model: str) -> None:
        self._ledger.settle(worst, usage.cost_usd, model, self._provider, usage.input_tokens, usage.output_tokens)


class _Responses(_Budgeted):
    async def create(self, **kwargs: Any) -> Any:
        model = kwargs["model"]
        price = _price(self._prices, model, kwargs.get("service_tier"))
        input_tokens = _count_input(model, kwargs.get("instructions"), kwargs.get("input"))
        worst = price.cost(input_tokens, kwargs.get("max_output_tokens") or DEFAULT_MAX_OUTPUT_TOKENS)
        response = await self._call(kwargs, worst, model)
        if kwargs.get("stream"):
            return self._settle_stream(response, worst, model, price)
        self._settle(worst, _usage(getattr(response, "usage", None), price, chat=False), model)
        return response

    async def _settle_stream(self, events: Any, worst: float, model: str, price: ModelPrice) -> AsyncIterator[Any]:
        usage = None
        try:
            async for event in events:
                if event.type in _TERMINAL_EVENTS:
                    usage = _usage(getattr(event.response, "usage", None), price, chat=False)
                yield event
        finally:
            if usage is None:
                # Stream đứt trước sự kiện kết thúc: không biết chi phí thật, ghi mức tối đa.
                self._ledger.settle(worst, worst, model, self._provider)
            else:
                self._settle(worst, usage, model)


class _ChatCompletions(_Budgeted):
    async def create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            raise ValueError("BudgetedClient chưa hỗ trợ chat.completions có stream")
        model = kwargs["model"]
        price = _price(self._prices, model, kwargs.get("service_tier"))
        max_output = kwargs.get("max_completion_tokens") or kwargs.get("max_tokens") or DEFAULT_MAX_OUTPUT_TOKENS
        worst = price.cost(_count_input(model, kwargs.get("messages")), max_output)
        response = await self._call(kwargs, worst, model)
        self._settle(worst, _usage(getattr(response, "usage", None), price, chat=True), model)
        return response


class _Embeddings(_Budgeted):
    async def create(self, **kwargs: Any) -> Any:
        model = kwargs["model"]
        price = _price(self._prices, model)
        worst = price.cost(_count_input(model, kwargs.get("input")), 0)
        response = await self._call(kwargs, worst, model)
        tokens = response.usage.prompt_tokens
        self._ledger.settle(worst, price.cost(tokens, 0), model, self._provider, tokens, 0)
        return response


def _usage(usage: Any, price: ModelPrice, chat: bool) -> Any:
    """`LlmUsage` của một response; provider không trả usage thì token và chi phí bằng 0."""
    # Import trong hàm: app.retrieval.llm import module này để bọc client.
    from app.retrieval.llm import usage_from_chat, usage_from_response

    return usage_from_chat(usage, price) if chat else usage_from_response(usage, price)


class BudgetedClient:
    """Bọc client của SDK openai (OpenAI hoặc endpoint tương thích): `responses`, `chat.completions` và
    `embeddings` đi qua trần chi phí, đó là mọi API pipeline dùng. `provider` được ghi vào ledger."""

    def __init__(self, client: Any, ledger: CostLedger, prices: dict[str, ModelPrice], provider: str = "openai"):
        self.ledger = ledger
        self.responses = _Responses(client.responses, ledger, prices, provider)
        self.embeddings = _Embeddings(client.embeddings, ledger, prices, provider)
        chat = getattr(client, "chat", None)
        self.chat = (
            SimpleNamespace(completions=_ChatCompletions(chat.completions, ledger, prices, provider)) if chat else None
        )


@lru_cache
def get_cost_ledger() -> CostLedger:
    settings = get_settings()
    return CostLedger(settings.daily_cost_limit_usd, settings.cost_ledger_path, settings.project_cost_limit_usd)


def budgeted(client: AsyncOpenAI, prices: dict[str, ModelPrice], provider: str = "openai") -> AsyncOpenAI:
    """Bọc client bằng trần chi phí. Kiểu trả về giữ là AsyncOpenAI cho nơi gọi, dù wrapper chỉ có `responses`,
    `chat.completions` và `embeddings`."""
    return cast(AsyncOpenAI, BudgetedClient(client, get_cost_ledger(), prices, provider))
