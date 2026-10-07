"""Trần chi phí OpenAI theo ngày (`DAILY_COST_LIMIT_USD`), chặn TRƯỚC khi gọi API.

`BudgetedClient` bọc `AsyncOpenAI`. Trước mỗi lời gọi `responses.create` hoặc `embeddings.create`, nó ước tính chi
phí tối đa của lời gọi đó: token đầu vào (đếm bằng tokenizer, tính theo giá input chưa cache) cộng
`max_output_tokens` token đầu ra. Nếu chi phí đã tiêu trong ngày cộng mức tối đa này vượt trần thì ném
`BudgetExceededError` và không gửi request. Sau lời gọi, chi phí thật (theo `usage`) được ghi vào `CostLedger`.

Ledger là file SQLite, nên chi phí cộng dồn qua mọi lần chạy script trong cùng một ngày (theo giờ máy). Ledger chỉ
biết các lời gọi đi qua `BudgetedClient`; lời gọi từ nơi khác dùng chung API key thì không tính được.
"""

import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from openai import AsyncOpenAI

from app.core.config import REPO_ROOT, get_settings
from app.core.rag_config import ModelPrice
from app.ingestion.tokens import TokenCounter

COST_LEDGER_PATH = REPO_ROOT / "data" / "cache" / "costs.sqlite"
# Lời gọi không đặt max_output_tokens (viết lại câu hỏi, rerank: đầu ra JSON ngắn) thì giả định tối đa chừng này.
DEFAULT_MAX_OUTPUT_TOKENS = 4096
# Tokenizer cl100k_base (fallback của TokenCounter) đếm tiếng Việt nhiều token hơn tokenizer của GPT mới, nên ước
# tính đầu vào thường dư. Nhân thêm hệ số cho phần khung message mà tokenizer không thấy.
INPUT_MARGIN = 1.1
_TERMINAL_EVENTS = ("response.completed", "response.incomplete", "response.failed")


class BudgetExceededError(RuntimeError):
    """Lời gọi có thể làm chi phí trong ngày vượt trần. Không kế thừa OpenAIError, để không bị bắt như lỗi API."""


class CostLedger:
    def __init__(self, limit_usd: float, path: Path = COST_LEDGER_PATH, today: Callable[[], date] = date.today):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.limit_usd, self.path, self._today = limit_usd, path, today
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS costs (day TEXT, at TEXT, model TEXT, cost_usd REAL)")
        # Mức tối đa của các lời gọi đang chạy trong process này (gọi song song).
        self._pending = 0.0

    def spent_today(self) -> float:
        row = self._db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM costs WHERE day = ?", [self._today().isoformat()])
        return float(row.fetchone()[0])

    def reserve(self, worst_case_usd: float, model: str) -> None:
        spent = self.spent_today()
        if spent + self._pending + worst_case_usd > self.limit_usd:
            raise BudgetExceededError(
                f"đã tiêu ${spent:.4f} hôm nay; lời gọi {model} có thể tốn tới ${worst_case_usd:.4f}, vượt trần "
                f"${self.limit_usd:.2f}/ngày (DAILY_COST_LIMIT_USD)"
            )
        self._pending += worst_case_usd

    def settle(self, reserved_usd: float, cost_usd: float, model: str) -> None:
        self._pending = max(0.0, self._pending - reserved_usd)
        with self._db:
            self._db.execute(
                "INSERT INTO costs VALUES (?, ?, ?, ?)",
                [self._today().isoformat(), datetime.now().astimezone().isoformat(timespec="seconds"), model, cost_usd],
            )


def _price(prices: dict[str, ModelPrice], model: str) -> ModelPrice:
    if model not in prices:
        raise KeyError(f"chưa có giá của {model} trong [prices] của config/rag.toml")
    return prices[model]


def _count_input(model: str, *parts: Any) -> int:
    text = "\n".join(p if isinstance(p, str) else json.dumps(p, ensure_ascii=False) for p in parts if p is not None)
    return int(TokenCounter(model)(text) * INPUT_MARGIN) + 50


class _Responses:
    def __init__(self, inner: Any, ledger: CostLedger, prices: dict[str, ModelPrice]):
        self._inner, self._ledger, self._prices = inner, ledger, prices

    async def create(self, **kwargs: Any) -> Any:
        model = kwargs["model"]
        price = _price(self._prices, model)
        input_tokens = _count_input(model, kwargs.get("instructions"), kwargs.get("input"))
        worst = price.cost(input_tokens, kwargs.get("max_output_tokens") or DEFAULT_MAX_OUTPUT_TOKENS)
        self._ledger.reserve(worst, model)
        try:
            response = await self._inner.create(**kwargs)
        except BaseException:
            self._ledger.settle(worst, 0.0, model)
            raise
        if kwargs.get("stream"):
            return self._settle_stream(response, worst, model, price)
        self._ledger.settle(worst, _usage_cost(getattr(response, "usage", None), price), model)
        return response

    async def _settle_stream(self, events: Any, worst: float, model: str, price: ModelPrice) -> AsyncIterator[Any]:
        cost = None
        try:
            async for event in events:
                if event.type in _TERMINAL_EVENTS:
                    cost = _usage_cost(getattr(event.response, "usage", None), price)
                yield event
        finally:
            # Stream đứt trước sự kiện kết thúc: không biết chi phí thật, ghi mức tối đa cho chắc.
            self._ledger.settle(worst, worst if cost is None else cost, model)


class _Embeddings:
    def __init__(self, inner: Any, ledger: CostLedger, prices: dict[str, ModelPrice]):
        self._inner, self._ledger, self._prices = inner, ledger, prices

    async def create(self, **kwargs: Any) -> Any:
        model = kwargs["model"]
        price = _price(self._prices, model)
        worst = price.cost(_count_input(model, kwargs.get("input")), 0)
        self._ledger.reserve(worst, model)
        try:
            response = await self._inner.create(**kwargs)
        except BaseException:
            self._ledger.settle(worst, 0.0, model)
            raise
        self._ledger.settle(worst, price.cost(response.usage.prompt_tokens, 0), model)
        return response


def _usage_cost(usage: Any, price: ModelPrice) -> float:
    # Import trong hàm: app.retrieval.llm import module này để bọc client.
    from app.retrieval.llm import usage_from_response

    return usage_from_response(usage, price).cost_usd if usage is not None else 0.0


class BudgetedClient:
    """Bọc client của SDK openai: chỉ `responses` và `embeddings` đi qua trần chi phí, đó là mọi API pipeline dùng."""

    def __init__(self, client: Any, ledger: CostLedger, prices: dict[str, ModelPrice]):
        self.ledger = ledger
        self.responses = _Responses(client.responses, ledger, prices)
        self.embeddings = _Embeddings(client.embeddings, ledger, prices)


@lru_cache
def get_cost_ledger() -> CostLedger:
    return CostLedger(get_settings().daily_cost_limit_usd)


def budgeted(client: AsyncOpenAI, prices: dict[str, ModelPrice]) -> AsyncOpenAI:
    """Bọc client bằng trần chi phí theo ngày. Kiểu trả về giữ là AsyncOpenAI cho nơi gọi, dù wrapper chỉ có
    `responses` và `embeddings`."""
    return cast(AsyncOpenAI, BudgetedClient(client, get_cost_ledger(), prices))
