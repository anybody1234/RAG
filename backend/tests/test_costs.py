import asyncio
import sqlite3
from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx
import openai
import pytest
from fakes import FakeChatCompletions, FakeResponses, FakeStreamResponses, fake_usage

from app.core.costs import BudgetedClient, BudgetExceededError, CostLedger
from app.core.rag_config import ModelPrice

PRICES = {
    "gpt-6.1-sol": ModelPrice(input=2.0, cached_input=0.1, cache_write=2.5, output=10.0),
    "text-embedding-3-large": ModelPrice(input=0.13),
}


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1000), data=[])


def make_client(tmp_path, limit: float, responses=None, day: date = date(2026, 10, 7)):
    ledger = CostLedger(limit, tmp_path / "costs.sqlite", today=lambda: day)
    inner = SimpleNamespace(responses=responses or FakeResponses({"ok": True}), embeddings=FakeEmbeddings())
    return BudgetedClient(inner, ledger, PRICES), inner, ledger


@pytest.mark.asyncio
async def test_call_is_refused_before_it_is_sent(tmp_path):
    # Mức tối đa: 2000 token ra × $10/1M = $0.02, vượt trần $0.01.
    client, inner, ledger = make_client(tmp_path, limit=0.01)
    with pytest.raises(BudgetExceededError, match="vượt trần"):
        await client.responses.create(model="gpt-6.1-sol", input="Câu hỏi?", max_output_tokens=2000)
    assert inner.responses.calls == [] and ledger.spent_today() == 0


@pytest.mark.asyncio
async def test_actual_cost_is_recorded_and_adds_up_across_ledgers(tmp_path):
    client, _, ledger = make_client(tmp_path, limit=1.0)
    await client.responses.create(model="gpt-6.1-sol", input="Câu hỏi?", max_output_tokens=500)
    # FakeResponses trả 100 token vào, 20 token ra.
    assert ledger.spent_today() == pytest.approx(PRICES["gpt-6.1-sol"].cost(100, 20))
    await client.embeddings.create(model="text-embedding-3-large", input=["a", "b"])
    assert ledger.spent_today() == pytest.approx(PRICES["gpt-6.1-sol"].cost(100, 20) + 1000 * 0.13 / 1e6)
    # Lần chạy sau trong cùng ngày đọc lại được chi phí đã tiêu; ngày khác thì bắt đầu từ 0.
    assert CostLedger(1.0, tmp_path / "costs.sqlite", today=lambda: date(2026, 10, 7)).spent_today() > 0
    assert CostLedger(1.0, tmp_path / "costs.sqlite", today=lambda: date(2026, 10, 8)).spent_today() == 0


@pytest.mark.asyncio
async def test_spent_today_counts_against_the_limit(tmp_path):
    client, _, ledger = make_client(tmp_path, limit=0.03)
    ledger.settle(0.0, 0.025, "gpt-6.1-sol")  # đã tiêu từ lần chạy trước
    with pytest.raises(BudgetExceededError):
        await client.responses.create(model="gpt-6.1-sol", input="x", max_output_tokens=1000)


@pytest.mark.asyncio
async def test_stream_cost_is_recorded_when_the_stream_ends(tmp_path):
    responses = FakeStreamResponses(["a", "b"], usage=fake_usage(1000, 100, cached=500))
    client, _, ledger = make_client(tmp_path, limit=1.0, responses=responses)
    events = await client.responses.create(model="gpt-6.1-sol", input="x", max_output_tokens=500, stream=True)
    assert ledger.spent_today() == 0  # chưa đọc hết stream
    assert [e.type async for e in events][-1] == "response.completed"
    assert ledger.spent_today() == pytest.approx(PRICES["gpt-6.1-sol"].cost(1000, 100, cached_tokens=500))


@pytest.mark.asyncio
async def test_flex_tier_uses_its_own_price(tmp_path):
    prices = PRICES | {"gpt-6.1-sol@flex": ModelPrice(input=1.0, cached_input=0.05, cache_write=1.25, output=5.0)}
    ledger = CostLedger(1.0, tmp_path / "costs.sqlite", today=lambda: date(2026, 10, 7))
    client = BudgetedClient(SimpleNamespace(responses=FakeResponses({"ok": True}), embeddings=None), ledger, prices)
    await client.responses.create(model="gpt-6.1-sol", input="x", max_output_tokens=100, service_tier="flex")
    assert ledger.spent_today() == pytest.approx(prices["gpt-6.1-sol@flex"].cost(100, 20))
    # Tier không có giá riêng thì báo lỗi, không lặng lẽ tính theo giá standard.
    with pytest.raises(KeyError, match="gpt-6.1-sol@priority"):
        await client.responses.create(model="gpt-6.1-sol", input="x", service_tier="priority")


@pytest.mark.asyncio
async def test_unknown_model_has_no_price(tmp_path):
    client, _, _ = make_client(tmp_path, limit=1.0)
    with pytest.raises(KeyError):
        await client.responses.create(model="gpt-unknown", input="x")


@pytest.mark.asyncio
async def test_project_limit_counts_every_day(tmp_path):
    path = tmp_path / "costs.sqlite"
    CostLedger(10.0, path, today=lambda: date(2026, 10, 6)).settle(0.0, 2.79, "gpt-6.1-sol")
    ledger = CostLedger(10.0, path, project_limit_usd=2.80, today=lambda: date(2026, 10, 7))
    assert (ledger.spent_today(), ledger.spent_total()) == (0.0, pytest.approx(2.79))
    client = BudgetedClient(SimpleNamespace(responses=FakeResponses({"ok": True}), embeddings=None), ledger, PRICES)
    with pytest.raises(BudgetExceededError, match="PROJECT_COST_LIMIT_USD"):
        await client.responses.create(model="gpt-6.1-sol", input="x", max_output_tokens=2000)


def request_error(status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return openai.APIStatusError("lỗi", response=httpx.Response(status, request=request), body=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "charged"), [
    (request_error(429), False),  # provider từ chối request: không tính tiền
    (request_error(400), False),
    (request_error(500), True),  # lỗi sau khi request đã gửi đi: ghi mức tối đa đã giữ chỗ
    (openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses")), True),
    (asyncio.CancelledError(), True),  # huỷ do quá hạn (bước viết lại câu hỏi)
])
async def test_failed_call_records_zero_only_when_the_provider_refused(tmp_path, error, charged):
    client, _, ledger = make_client(tmp_path, limit=1.0, responses=FakeResponses(error=error))
    with pytest.raises(type(error)):
        await client.responses.create(model="gpt-6.1-sol", input="Câu hỏi?", max_output_tokens=500)
    worst = PRICES["gpt-6.1-sol"].cost(0, 500)  # mức tối đa gồm cả token vào ước tính
    assert (ledger.spent_today() > worst) is charged
    assert ledger._pending == 0


@pytest.mark.asyncio
async def test_chat_completions_are_budgeted_and_counted_per_provider(tmp_path):
    prices = PRICES | {"gemini-3.8-flash": ModelPrice(input=0.0)}
    ledger = CostLedger(1.0, tmp_path / "costs.sqlite")
    chat = FakeChatCompletions()
    inner = SimpleNamespace(responses=None, embeddings=None, chat=SimpleNamespace(completions=chat))
    client = BudgetedClient(inner, ledger, prices, provider="gemini")
    await client.chat.completions.create(model="gemini-3.8-flash", messages=[{"role": "user", "content": "x"}],
                                         max_completion_tokens=100)
    assert ledger.spent_today() == 0
    assert ledger.usage_since("gemini", "gemini-3.8-flash", datetime(2000, 1, 1, tzinfo=UTC)) == (1, 1200)
    assert ledger.usage_since("openai", "gemini-3.8-flash", datetime(2000, 1, 1, tzinfo=UTC)) == (0, 0)


def test_old_ledger_table_gets_new_columns(tmp_path):
    path = tmp_path / "costs.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE costs (day TEXT, at TEXT, model TEXT, cost_usd REAL)")
    db.execute("INSERT INTO costs VALUES ('2026-10-07', '2026-10-07T19:00:00+07:00', 'gpt-6-luna', 0.001)")
    db.commit()
    db.close()
    ledger = CostLedger(1.0, path)
    assert ledger.spent_total() == pytest.approx(0.001)
    ledger.settle(0.0, 0.0, "gemini-3.8-flash", "gemini", 10, 5)
    assert ledger.usage_since("gemini", "gemini-3.8-flash", datetime(2000, 1, 1, tzinfo=UTC)) == (1, 15)
