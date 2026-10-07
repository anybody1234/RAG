"""Phần không gọi API của eval/run_e2e_eval.py: ước tính chi phí, câu nào cần chấm, dừng gọn khi hết quota."""

import json

import pytest
from run_e2e_eval import JudgeRunner, check_estimate, estimate_cost, needs_judge, rejudge_missing

from app.core.costs import BudgetExceededError
from app.core.rag_config import load_rag_config
from app.evaluation.golden import GoldenItem
from app.evaluation.judge import Judge, JudgeCase, ModelReply, QuotaExhaustedError
from app.retrieval.llm import LlmUsage

CONFIG = load_rag_config()
JUDGMENT = {"claims": [], "correctness": "correct", "relevancy": "relevant", "explanation": ""}


def items(n: int, follow_ups: int = 0) -> list[GoldenItem]:
    rows = []
    for i in range(n):
        row = {"id": f"g{i:03d}", "question": "Câu hỏi?", "language": "vi", "type": "single_article",
               "reference_answer": "x", "gold_sources": [{"doc_id": "d", "page": 1, "quote": "đoạn trích dài"}]}
        if i < follow_ups:
            row |= {"type": "multi_turn", "history": [{"role": "user", "content": "Trước?"}]}
        rows.append(GoldenItem.model_validate(row))
    return rows


def test_estimate_refuses_sol_for_100_questions_but_not_luna():
    luna = CONFIG.model_copy(update={"generation": CONFIG.generation.model_copy(update={"answer_model": "gpt-6-luna"})})
    sol = CONFIG.model_copy(update={"generation": CONFIG.generation.model_copy(update={"answer_model": "gpt-6.1-sol"})})
    gemini = CONFIG.judge_profile("gemini")
    luna_cost = estimate_cost(luna, items(100, follow_ups=9), 100, gemini)
    assert luna_cost["judge"] == 0 and 0.01 < luna_cost["total"] < 0.30
    check_estimate(luna_cost, None)
    sol_cost = estimate_cost(sol, items(100), 100, gemini)
    with pytest.raises(BudgetExceededError, match="--max-cost"):
        check_estimate(sol_cost, None)
    assert check_estimate(sol_cost, max_cost=2.0) == 2.0
    # Judge trả phí được tính vào ước tính.
    assert estimate_cost(luna, items(10), 10, CONFIG.judge_profile("sol"), answers=False)["judge"] > 0.1


def record(status: str = "completed", runs: list | None = None) -> dict:
    result = {"answer": {"status": status}}
    if runs is not None:
        result["judge"] = {"runs": runs}
    return result


def test_needs_judge():
    assert needs_judge(record())
    assert needs_judge(record(runs=[{"error": "JSONDecodeError"}]))
    assert not needs_judge(record(runs=[{"error": "JSONDecodeError"}, {"error": None}]))
    assert not needs_judge(record(status="failed"))  # không có câu trả lời thì không chấm


class LimitedModel:
    """Model giả: trả lời `limit` lần rồi báo hết quota ngày."""

    name = "fake"

    def __init__(self, limit: int):
        self.limit, self.calls = limit, 0

    async def complete(self, instructions, case_text, schema, cache_case):
        self.calls += 1
        if self.calls > self.limit:
            raise QuotaExhaustedError("hết quota")
        return ModelReply(json.dumps(JUDGMENT), LlmUsage(calls=1))


@pytest.mark.asyncio
async def test_runner_stops_cleanly_when_quota_runs_out():
    model = LimitedModel(limit=1)
    runner = JudgeRunner(Judge(model, "judge-v1"), repeats=1)
    case = JudgeCase("Câu hỏi?", "x", [], "Trả lời.")
    first, _ = await runner.run(case)
    assert first is not None and first["scores"]["correctness"] == 1.0
    assert (await runner.run(case))[0] is None and runner.stopped and "hết quota" in runner.stopped
    assert (await runner.run(case))[0] is None and model.calls == 2  # đã dừng thì không gọi nữa


@pytest.mark.asyncio
async def test_runner_keeps_runs_done_before_quota_ran_out():
    runner = JudgeRunner(Judge(LimitedModel(limit=1), "judge-v1"), repeats=3)
    judged, _ = await runner.run(JudgeCase("Câu hỏi?", "x", [], "Trả lời."))
    assert judged is not None and len(judged["runs"]) == 1 and runner.stopped


@pytest.mark.asyncio
async def test_rejudge_refuses_to_mix_judges(tmp_path):
    path = tmp_path / "e2e.json"
    path.write_text(json.dumps({
        "kind": "e2e",
        "judge": {"profile": "groq", "provider": "groq", "model": "openai/gpt-oss-120b", "prompt_version": "judge-v1",
                  "reasoning_effort": "medium", "judged": 40, "repeats": 1},
        "questions": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="không gộp hai judge"):
        await rejudge_missing(path, tmp_path / "golden.jsonl", "gemini", None)
