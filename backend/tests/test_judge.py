import json
from types import SimpleNamespace

import pytest
from fakes import FakeResponses

from app.core.rag_config import EvalConfig, ModelPrice
from app.evaluation.judge import (
    Claim,
    Judge,
    JudgeCase,
    ModelReply,
    OpenAIJudgeModel,
    build_judge,
    format_case,
    judgment_scores,
    parse_claims,
)
from app.retrieval.llm import LlmUsage

SOL = ModelPrice(input=2.0, cached_input=0.1, cache_write=2.5, output=10.0)
CONFIG = EvalConfig(judge_model="gpt-6.1-sol", judge_reasoning_effort="high", judge_prompt_version="judge-v1",
                    judge_max_output_tokens=16000, judge_service_tier="default")
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


def test_openai_cache_breakpoints():
    model = OpenAIJudgeModel(SimpleNamespace(responses=FakeResponses()), CONFIG, SOL)
    long_prompt = Judge(model, "judge-v1").instructions  # judge-v1.md dài hơn 1024 token
    developer, user = model.build_input(long_prompt, "case", cache_case=False)
    assert developer["role"] == "developer" and developer["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "prompt_cache_breakpoint" not in user["content"][0]
    assert "prompt_cache_breakpoint" in model.build_input(long_prompt, "case", cache_case=True)[1]["content"][0]
    # Prompt cố định ngắn hơn ngưỡng cache thì không đặt điểm cache.
    assert "prompt_cache_breakpoint" not in model.build_input("Grade it.", "case", cache_case=False)[0]["content"][0]


def test_unknown_prompt_version(tmp_path):
    with pytest.raises(ValueError):
        Judge(OpenAIJudgeModel(SimpleNamespace(responses=FakeResponses()), CONFIG, SOL), "judge-v0", judges_dir=tmp_path)


@pytest.mark.asyncio
async def test_openai_judge_parses_strict_json():
    responses = FakeResponses(JUDGMENT)
    judgment = await build_judge(SimpleNamespace(responses=responses), CONFIG, SOL).judge(CASE)
    assert judgment.error is None and judgment.scores()["faithfulness"] == 1.0 and judgment.correctness == "correct"
    call = responses.calls[0]
    assert call["text"]["format"]["strict"] is True and call["reasoning"] == {"effort": "high"}
    assert call["prompt_cache_options"] == {"mode": "explicit"} and call["max_output_tokens"] == 16000
    assert "service_tier" not in call  # tier mặc định thì không gửi
    assert judgment.usage.cost_usd == pytest.approx(SOL.cost(100, 20))

    flex = FakeResponses(JUDGMENT)
    await build_judge(SimpleNamespace(responses=flex), CONFIG.model_copy(update={"judge_service_tier": "flex"}),
                      SOL).judge(CASE)
    assert flex.calls[0]["service_tier"] == "flex"


@pytest.mark.asyncio
async def test_judge_works_with_any_model_provider(tmp_path):
    class OtherProvider:
        name = "other"

        def __init__(self):
            self.calls = []

        async def complete(self, instructions, case_text, schema, cache_case):
            self.calls.append((instructions, case_text, schema["required"], cache_case))
            return ModelReply(json.dumps(JUDGMENT), LlmUsage(calls=1, cost_usd=0.0))

    (tmp_path / "judge-x.md").write_text("Grade the answer.", encoding="utf-8")
    provider = OtherProvider()
    judgment = await Judge(provider, "judge-x", judges_dir=tmp_path).judge(CASE, cache_case=True)
    assert judgment.correctness == "correct" and judgment.usage.calls == 1
    instructions, case_text, required, cache_case = provider.calls[0]
    assert (instructions, required, cache_case) == ("Grade the answer.", ["claims", "correctness", "relevancy",
                                                                         "explanation"], True)
    assert case_text == format_case(CASE)


@pytest.mark.asyncio
async def test_judge_errors_give_no_scores():
    bad = await build_judge(SimpleNamespace(responses=FakeResponses(raw="not json")), CONFIG, SOL).judge(CASE)
    assert bad.error == "JSONDecodeError" and set(bad.scores().values()) == {None}

    class Incomplete(FakeResponses):
        async def create(self, **kwargs):
            response = await super().create(**kwargs)
            response.status, response.incomplete_details = "incomplete", SimpleNamespace(reason="max_output_tokens")
            return response

    cut = await build_judge(SimpleNamespace(responses=Incomplete({})), CONFIG, SOL).judge(CASE)
    assert cut.error == "incomplete:max_output_tokens" and cut.usage.calls == 1
