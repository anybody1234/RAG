from types import SimpleNamespace

import httpx
import openai
import pytest
from fakes import FakeResponses

from app.core.rag_config import ModelPrice, QueryConfig
from app.retrieval.query import QueryPlan, QueryProcessor

PRICE = ModelPrice(input=0.10, output=0.50)


def make_processor(
    rewrite: str, translate: bool, timeout_ms: int = 0, **fake
) -> tuple[QueryProcessor, FakeResponses]:
    responses = FakeResponses(**fake)
    config = QueryConfig(
        model="gpt-6-luna", reasoning_effort="none", prompt_version="query-v1",
        rewrite=rewrite, rewrite_timeout_ms=timeout_ms, translate=translate, translation_weight=0.5,
    )
    return QueryProcessor(SimpleNamespace(responses=responses), config, PRICE), responses


HISTORY = [("user", "Người lao động được nghỉ phép năm bao nhiêu ngày?"), ("assistant", "12 ngày làm việc.")]


@pytest.mark.asyncio
async def test_no_call_when_nothing_to_do():
    processor, responses = make_processor(rewrite="none", translate=False)
    plan = await processor.process("Thời gian thử việc tối đa?", HISTORY)
    assert (plan.standalone, plan.translation, plan.language, responses.calls) == (
        "Thời gian thử việc tối đa?", None, "vi", []
    )
    # Bật rewrite nhưng là lượt đầu (không có lịch sử) thì cũng không gọi.
    processor, responses = make_processor(rewrite="llm", translate=False)
    await processor.process("Thời gian thử việc tối đa?")
    assert responses.calls == []


@pytest.mark.asyncio
async def test_translate_only_asks_for_the_other_language():
    processor, responses = make_processor(rewrite="none", translate=True, data={"translation": "Maximum probation?"})
    plan = await processor.process("Thời gian thử việc tối đa?", HISTORY)
    call = responses.calls[0]
    assert "English" in call["instructions"] and "standalone" not in call["instructions"]
    assert "<history>" not in call["input"]  # không viết lại thì không gửi lịch sử
    assert list(call["text"]["format"]["schema"]["properties"]) == ["translation"]
    assert call["store"] is False and call["reasoning"] == {"effort": "none"}
    assert (plan.standalone, plan.translation) == ("Thời gian thử việc tối đa?", "Maximum probation?")
    assert plan.usage.cost_usd == pytest.approx((100 * 0.10 + 20 * 0.50) / 1e6)
    assert plan.queries(0.5) == [("Thời gian thử việc tối đa?", 1.0), ("Maximum probation?", 0.5)]


@pytest.mark.asyncio
async def test_english_question_is_translated_to_vietnamese():
    processor, responses = make_processor(rewrite="none", translate=True, data={"translation": "Thời gian thử việc?"})
    await processor.process("What is the maximum probation period?")
    assert "into Vietnamese" in responses.calls[0]["instructions"]


@pytest.mark.asyncio
async def test_rewrite_and_translate_in_one_call():
    data = {"standalone": "Làm công việc nặng nhọc được nghỉ phép năm bao nhiêu ngày?",
            "translation": "How many days of annual leave for heavy work?"}
    processor, responses = make_processor(rewrite="llm", translate=True, data=data)
    plan = await processor.process("Còn nếu làm công việc nặng nhọc thì sao?", HISTORY)
    assert len(responses.calls) == 1
    assert "<history>" in responses.calls[0]["input"] and "12 ngày làm việc." in responses.calls[0]["input"]
    assert set(responses.calls[0]["text"]["format"]["schema"]["properties"]) == {"standalone", "translation"}
    assert (plan.standalone, plan.translation) == (data["standalone"], data["translation"])
    assert plan.question == "Còn nếu làm công việc nặng nhọc thì sao?"


FOLLOW_UP = "Còn nếu làm công việc nặng nhọc thì sao?"
CONCAT = "Người lao động được nghỉ phép năm bao nhiêu ngày?\nCòn nếu làm công việc nặng nhọc thì sao?"


@pytest.mark.asyncio
async def test_concat_joins_previous_user_question_without_llm():
    processor, responses = make_processor(rewrite="concat", translate=False)
    plan = await processor.process(FOLLOW_UP, HISTORY)
    assert (plan.standalone, plan.method, plan.latency_ms, responses.calls) == (CONCAT, "concat", 0.0, [])
    # Lượt đầu không có gì để ghép.
    assert (await processor.process(FOLLOW_UP)).standalone == FOLLOW_UP


@pytest.mark.asyncio
async def test_llm_error_falls_back_to_concat():
    error = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    processor, _ = make_processor(rewrite="llm", translate=True, error=error)
    plan = await processor.process(FOLLOW_UP, HISTORY)
    assert (plan.standalone, plan.translation, plan.method, plan.error) == (
        CONCAT, None, "concat_fallback", "APITimeoutError"
    )
    assert plan.queries(0.5) == [(CONCAT, 1.0)]


@pytest.mark.asyncio
async def test_rewrite_over_the_deadline_falls_back_to_concat():
    processor, _ = make_processor(rewrite="llm", translate=False, timeout_ms=50, data={"standalone": "x"}, delay=1.0)
    plan = await processor.process(FOLLOW_UP, HISTORY)
    assert (plan.standalone, plan.method, plan.error) == (CONCAT, "concat_fallback", "timeout")
    # Latency dừng ở hạn, không chờ model trả lời.
    assert 50 <= plan.latency_ms < 500
    # Trả lời kịp hạn thì dùng câu LLM viết lại.
    processor, _ = make_processor(rewrite="llm", translate=False, timeout_ms=1000, data={"standalone": "Câu độc lập?"})
    plan = await processor.process(FOLLOW_UP, HISTORY)
    assert (plan.standalone, plan.method, plan.error) == ("Câu độc lập?", "llm", None)


@pytest.mark.asyncio
async def test_empty_rewrite_falls_back_to_concat():
    processor, _ = make_processor(rewrite="llm", translate=False, data={"standalone": "  "})
    plan = await processor.process(FOLLOW_UP, HISTORY)
    assert (plan.standalone, plan.method) == (CONCAT, "concat_fallback")


def test_translation_equal_to_question_is_not_queried_twice():
    plan = QueryPlan(question="GDPR", language="en", standalone="GDPR", translation="GDPR")
    assert plan.queries(1.0) == [("GDPR", 1.0)]


def test_unknown_prompt_version_is_rejected():
    config = QueryConfig(model="m", reasoning_effort="none", prompt_version="query-v9", rewrite="llm",
                         rewrite_timeout_ms=0, translate=True, translation_weight=1.0)
    with pytest.raises(ValueError):
        QueryProcessor(SimpleNamespace(responses=FakeResponses()), config, PRICE)
