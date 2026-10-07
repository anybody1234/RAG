import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import openai
import pytest
from fakes import FakeChatCompletions, FakeResponses

from app.core.costs import CostLedger, quota_window_start
from app.core.rag_config import JudgeProfile, ModelPrice
from app.evaluation.judge import (
    Claim,
    Judge,
    JudgeCase,
    ModelReply,
    OpenAICompatJudgeModel,
    ProviderDownError,
    QuotaExhaustedError,
    QuotaTracker,
    RateLimiter,
    format_case,
    is_daily_quota,
    judgment_scores,
    parse_claims,
    retry_delay,
)
from app.retrieval.llm import LlmUsage

SOL = ModelPrice(input=2.0, cached_input=0.1, cache_write=2.5, output=10.0)
FREE = ModelPrice(input=0.0)
SOL_PROFILE = JudgeProfile(provider="openai", api="responses", api_key_env="OPENAI_API_KEY", model="gpt-6.1-sol",
                           reasoning_effort="high", max_output_tokens=16000)
GEMINI = JudgeProfile(provider="gemini", api="chat", base_url="https://example.test/openai/", api_key_env="GEMINI_API_KEY",
                      model="gemini-3.8-flash", reasoning_effort="high", max_output_tokens=8000, rpd=100,
                      quota_reset="pacific")
PAYLOADS = [
    {"chunk_id": "a", "title": "Bộ luật Lao động", "so_hieu": "45/2019/QH14", "heading_path": "Điều 25",
     "page": 11, "text": "Điều 25. Thời gian thử việc ... không quá 60 ngày ..."},
    {"chunk_id": "b", "title": "Bộ luật Lao động", "so_hieu": "45/2019/QH14", "heading_path": "Điều 24",
     "page": 11, "text": "Điều 24. Thử việc ..."},
]
CASE = JudgeCase(question="Thử việc tối đa?", reference_answer="Không quá 60 ngày.", payloads=PAYLOADS,
                 answer="Tối đa 60 ngày [1]. Phải ký hợp đồng [2].",
                 history=[("user", "Nghỉ phép?"), ("assistant", "12 ngày [3].")])
JUDGMENT = {"claims": [{"claim": "60 ngày", "cited": [1], "supported": True, "supporting_cited": [1]}],
            "correctness": "correct", "relevancy": "relevant", "explanation": "Đúng 60 ngày."}


class Sleeps:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def rate_limit(message: str, headers: dict | None = None, body: object = None) -> openai.RateLimitError:
    request = httpx.Request("POST", "https://example.test/chat/completions")
    return openai.RateLimitError(message, response=httpx.Response(429, request=request, headers=headers or {}), body=body)


def chat_model(chat: FakeChatCompletions, profile: JudgeProfile = GEMINI, **kwargs) -> OpenAICompatJudgeModel:
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    return OpenAICompatJudgeModel(client, profile, FREE, **kwargs)


def test_scores_come_from_claims():
    claims = [
        Claim("60 ngày", cited=[1], supported=True, supporting_cited=[1]),
        Claim("một lần", cited=[1, 2], supported=True, supporting_cited=[1]),
        Claim("ký hợp đồng", cited=[2], supported=False, supporting_cited=[]),
        Claim("không trích dẫn", cited=[], supported=True, supporting_cited=[]),
    ]
    assert judgment_scores(claims, "correct", "partially_relevant") == {
        "faithfulness": 3 / 4, "citation_precision": 2 / 4, "citation_recall": 2 / 4,
        "correctness": 1.0, "relevancy": 0.5,
    }
    # Chỉ từ chối, không có ý nào: không tính faithfulness và citation.
    assert judgment_scores([], "correct", "relevant") == {
        "faithfulness": None, "citation_precision": None, "citation_recall": None, "correctness": 1.0, "relevancy": 1.0,
    }


def test_parse_claims_keeps_supporting_inside_cited():
    claims = parse_claims([{"claim": "x", "cited": [1, 1, "2"], "supported": True, "supporting_cited": [1, 3]}])
    assert claims == [Claim("x", cited=[1], supported=True, supporting_cited=[1])]
    assert parse_claims(None) == []


def test_case_has_history_without_old_citations_and_numbered_documents():
    text = format_case(CASE)
    assert text.startswith("<conversation_history>\nuser: Nghỉ phép?\nassistant: 12 ngày.\n</conversation_history>")
    assert "<reference_answer>Không quá 60 ngày.</reference_answer>" in text
    assert '<document index="2"' in text and text.endswith("<answer>Tối đa 60 ngày [1]. Phải ký hợp đồng [2].</answer>")


def test_responses_api_cache_breakpoints():
    model = OpenAICompatJudgeModel(SimpleNamespace(responses=FakeResponses()), SOL_PROFILE, SOL)
    long_prompt = Judge(model, "judge-v1").instructions  # judge-v1.md dài hơn 1024 token
    developer, user = model.build_input(long_prompt, "case", cache_case=False)
    assert developer["role"] == "developer" and developer["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "prompt_cache_breakpoint" not in user["content"][0]
    assert "prompt_cache_breakpoint" in model.build_input(long_prompt, "case", cache_case=True)[1]["content"][0]
    # Prompt cố định ngắn hơn ngưỡng cache thì không đặt điểm cache.
    assert "prompt_cache_breakpoint" not in model.build_input("Grade it.", "case", cache_case=False)[0]["content"][0]


def test_unknown_prompt_version(tmp_path):
    with pytest.raises(ValueError):
        Judge(chat_model(FakeChatCompletions()), "judge-v0", judges_dir=tmp_path)


@pytest.mark.asyncio
async def test_responses_api_judge_parses_strict_json():
    responses = FakeResponses(JUDGMENT)
    judgment = await Judge(OpenAICompatJudgeModel(SimpleNamespace(responses=responses), SOL_PROFILE, SOL),
                           "judge-v1").judge(CASE)
    assert judgment.error is None and judgment.scores()["faithfulness"] == 1.0 and judgment.correctness == "correct"
    call = responses.calls[0]
    assert call["text"]["format"]["strict"] is True and call["reasoning"] == {"effort": "high"}
    assert call["prompt_cache_options"] == {"mode": "explicit"} and call["max_output_tokens"] == 16000
    assert "service_tier" not in call  # tier mặc định thì không gửi
    assert judgment.usage.cost_usd == pytest.approx(SOL.cost(100, 20))

    flex = FakeResponses(JUDGMENT)
    profile = SOL_PROFILE.model_copy(update={"service_tier": "flex"})
    await Judge(OpenAICompatJudgeModel(SimpleNamespace(responses=flex), profile, SOL), "judge-v1").judge(CASE)
    assert flex.calls[0]["service_tier"] == "flex"


@pytest.mark.asyncio
async def test_chat_completions_judge_records_model_id_and_usage():
    chat = FakeChatCompletions(json.dumps(JUDGMENT))
    judgment = await Judge(chat_model(chat), "judge-v1").judge(CASE)
    assert (judgment.error, judgment.correctness, judgment.model) == (None, "correct", "gemini-3.8-flash-001")
    assert (judgment.usage.input_tokens, judgment.usage.output_tokens, judgment.usage.reasoning_tokens) == (900, 300, 200)
    call = chat.calls[0]
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    assert call["messages"][1]["content"] == format_case(CASE)
    assert call["response_format"]["type"] == "json_schema" and call["response_format"]["json_schema"]["strict"] is True
    assert (call["model"], call["max_completion_tokens"], call["reasoning_effort"]) == ("gemini-3.8-flash", 8000, "high")
    assert judgment.record()["model"] == "gemini-3.8-flash-001"


@pytest.mark.asyncio
async def test_chat_cut_off_by_length_is_an_error():
    judgment = await Judge(chat_model(FakeChatCompletions('{"claims": [', finish_reason="length")), "judge-v1").judge(CASE)
    assert judgment.error == "incomplete:length" and set(judgment.scores().values()) == {None}


@pytest.mark.asyncio
async def test_judge_works_with_any_model_provider(tmp_path):
    class OtherProvider:
        name = "other"

        def __init__(self):
            self.calls = []

        async def complete(self, instructions, case_text, schema, cache_case):
            self.calls.append((instructions, case_text, schema["required"], cache_case))
            return ModelReply(json.dumps(JUDGMENT), LlmUsage(calls=1, cost_usd=0.0), model="other-1")

    (tmp_path / "judge-x.md").write_text("Grade the answer.", encoding="utf-8")
    provider = OtherProvider()
    judgment = await Judge(provider, "judge-x", judges_dir=tmp_path).judge(CASE, cache_case=True)
    assert judgment.correctness == "correct" and judgment.usage.calls == 1 and judgment.model == "other-1"
    instructions, case_text, required, cache_case = provider.calls[0]
    assert (instructions, required, cache_case) == ("Grade the answer.", ["claims", "correctness", "relevancy",
                                                                         "explanation"], True)
    assert case_text == format_case(CASE)


@pytest.mark.asyncio
async def test_judge_errors_give_no_scores():
    bad = await Judge(chat_model(FakeChatCompletions("not json")), "judge-v1").judge(CASE)
    assert bad.error == "JSONDecodeError" and set(bad.scores().values()) == {None}

    class Incomplete(FakeResponses):
        async def create(self, **kwargs):
            response = await super().create(**kwargs)
            response.status, response.incomplete_details = "incomplete", SimpleNamespace(reason="max_output_tokens")
            return response

    model = OpenAICompatJudgeModel(SimpleNamespace(responses=Incomplete({})), SOL_PROFILE, SOL)
    cut = await Judge(model, "judge-v1").judge(CASE)
    assert cut.error == "incomplete:max_output_tokens" and cut.usage.calls == 1


def test_retry_delay_from_header_gemini_body_and_groq_message():
    assert retry_delay(rate_limit("slow down", headers={"retry-after": "12"})) == 12.0
    gemini_body = [{"error": {"code": 429, "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                                         "retryDelay": "37s"}]}}]
    assert retry_delay(rate_limit("Resource exhausted", body=gemini_body)) == 37.0
    assert retry_delay(rate_limit("Rate limit reached ... Please try again in 1m2.5s.")) == pytest.approx(62.5)
    assert retry_delay(rate_limit("no hint")) is None


def test_daily_quota_is_recognised():
    gemini = rate_limit("Quota exceeded", body={"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}})
    groq = rate_limit("Rate limit reached for model `openai/gpt-oss-120b` on tokens per day (TPD): Limit 200000")
    per_minute = rate_limit("Rate limit reached on requests per minute (RPM): Limit 30. Please try again in 2s.")
    assert is_daily_quota(gemini) and is_daily_quota(groq) and not is_daily_quota(per_minute)


@pytest.mark.asyncio
async def test_per_minute_429_is_retried_after_the_advised_delay():
    chat = FakeChatCompletions(json.dumps(JUDGMENT), errors=[rate_limit("try again", headers={"retry-after": "7"})])
    sleeps = Sleeps()
    judgment = await Judge(chat_model(chat, sleep=sleeps), "judge-v1").judge(CASE)
    assert judgment.error is None and len(chat.calls) == 2 and sleeps.calls == [7.5]


@pytest.mark.asyncio
async def test_daily_quota_stops_without_retrying():
    chat = FakeChatCompletions(errors=[rate_limit("Quota exceeded", body={"quotaId": "GenerateRequestsPerDay"})])
    with pytest.raises(QuotaExhaustedError):
        await Judge(chat_model(chat, sleep=Sleeps()), "judge-v1").judge(CASE)
    assert len(chat.calls) == 1
    # Provider bảo chờ quá lâu cũng coi như hết quota.
    chat = FakeChatCompletions(errors=[rate_limit("wait", headers={"retry-after": "3600"})])
    with pytest.raises(QuotaExhaustedError):
        await Judge(chat_model(chat, sleep=Sleeps()), "judge-v1").judge(CASE)


def timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "https://example.test/chat/completions"))


def server_error(status: int = 503) -> openai.InternalServerError:
    request = httpx.Request("POST", "https://example.test/chat/completions")
    return openai.InternalServerError("high demand", response=httpx.Response(status, request=request), body=None)


@pytest.mark.asyncio
async def test_one_timeout_is_retried_once():
    chat = FakeChatCompletions(json.dumps(JUDGMENT), errors=[timeout_error()])
    model = chat_model(chat, sleep=Sleeps())
    judgment = await Judge(model, "judge-v1").judge(CASE)
    assert judgment.error is None and len(chat.calls) == 2 and model.failures == 0


@pytest.mark.asyncio
async def test_two_failures_in_a_row_mark_the_provider_down():
    chat = FakeChatCompletions(json.dumps(JUDGMENT), errors=[server_error(), timeout_error(), server_error()])
    with pytest.raises(ProviderDownError, match="2 lỗi liên tiếp"):
        await Judge(chat_model(chat, sleep=Sleeps()), "judge-v1").judge(CASE)
    assert len(chat.calls) == 2  # mỗi lần thử trừ quota ngày: không thử tiếp


@pytest.mark.asyncio
async def test_rate_limiter_waits_for_the_minute_window():
    now = [0.0]
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(rpm=2, tpm=1000, clock=lambda: now[0], sleep=sleep)
    await limiter.acquire(400)
    await limiter.acquire(400)
    assert sleeps == []
    await limiter.acquire(100)  # vượt rpm: chờ request đầu ra khỏi cửa sổ 60 s
    assert sleeps == [pytest.approx(60.1)]
    big = RateLimiter(rpm=0, tpm=1000, clock=lambda: now[0], sleep=sleep)
    await big.acquire(5000)  # lớn hơn cả tpm nhưng cửa sổ trống: vẫn được gửi
    assert len(sleeps) == 1


def test_quota_window_follows_pacific_time():
    # 07/10 05:00 UTC = 06/10 22:00 PDT (UTC-7): ngày quota bắt đầu 06/10 07:00 UTC.
    assert quota_window_start("pacific", datetime(2026, 10, 7, 5, tzinfo=UTC)) == datetime(2026, 10, 6, 7, tzinfo=UTC)
    # Tháng 12 là PST (UTC-8).
    assert quota_window_start("pacific", datetime(2026, 12, 1, 12, tzinfo=UTC)) == datetime(2026, 12, 1, 8, tzinfo=UTC)
    assert quota_window_start("utc", datetime(2026, 10, 7, 5, tzinfo=UTC)) == datetime(2026, 10, 7, tzinfo=UTC)


def test_quota_tracker_counts_requests_of_the_provider_from_the_ledger(tmp_path):
    ledger = CostLedger(1.0, tmp_path / "costs.sqlite")
    tracker = QuotaTracker(ledger, GEMINI.model_copy(update={"rpd": 3, "tpd": 5000}))
    for _ in range(2):
        ledger.settle(0.0, 0.0, "gemini-3.8-flash", "gemini", input_tokens=1500, output_tokens=500)
    ledger.settle(0.0, 0.001, "gpt-6-luna", "openai", input_tokens=10_000)  # provider khác không tính
    assert tracker.remaining() == (1, 1000)
    with pytest.raises(QuotaExhaustedError, match="token"):
        tracker.check(2000)
    tracker.check(500)
    ledger.settle(0.0, 0.0, "gemini-3.8-flash", "gemini")
    with pytest.raises(QuotaExhaustedError, match="request"):
        tracker.check(1)


@pytest.mark.asyncio
async def test_quota_is_checked_before_calling(tmp_path):
    ledger = CostLedger(1.0, tmp_path / "costs.sqlite")
    ledger.settle(0.0, 0.0, "gemini-3.8-flash", "gemini")
    chat = FakeChatCompletions(json.dumps(JUDGMENT))
    model = chat_model(chat, quota=QuotaTracker(ledger, GEMINI.model_copy(update={"rpd": 1})))
    with pytest.raises(QuotaExhaustedError):
        await Judge(model, "judge-v1").judge(CASE)
    assert chat.calls == []
