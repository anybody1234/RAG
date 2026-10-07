from datetime import date
from types import SimpleNamespace

import pytest
from fakes import FakeResponses, FakeStreamResponses, fake_usage

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
async def test_unknown_model_has_no_price(tmp_path):
    client, _, _ = make_client(tmp_path, limit=1.0)
    with pytest.raises(KeyError):
        await client.responses.create(model="gpt-unknown", input="x")
