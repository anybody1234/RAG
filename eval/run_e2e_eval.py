"""Eval end-to-end trên golden set: viết lại câu hỏi → truy xuất → trả lời (streaming, đo TTFT) → LLM-judge.

Chạy từ thư mục gốc của repo, sau khi đã index (`python scripts/index.py`):
    python eval/run_e2e_eval.py                       # đủ golden set, judge theo [eval] judge, chấm 1 lần
    python eval/run_e2e_eval.py --only g001 g034      # soi lỗi, không lưu
    python eval/run_e2e_eval.py --n 20                # mẫu trải đều theo loại câu, lưu với hậu tố _e2e-n20
    python eval/run_e2e_eval.py --judge groq          # judge theo hồ sơ [judges.groq]
    python eval/run_e2e_eval.py --no-judge            # chỉ trả lời, đo latency và từ chối
    # Chấm nốt các câu chưa có điểm (hết quota hôm trước), dùng câu trả lời và context đã lưu:
    python eval/run_e2e_eval.py --rejudge-missing eval/results/<...>_e2e.json
    # So sánh model trả lời: ghi đè config, phải đặt config_version riêng.
    python eval/run_e2e_eval.py --set config_version=v0.2-exp-sol --set generation.answer_model=gpt-6.1-sol

Kết quả lưu vào eval/results/<YYYY-MM-DD>_<config_version>_e2e.json. Mỗi câu có: câu gốc, câu đã viết lại, chunk
id kèm score, context đã đánh số [n] (đủ text, để chấm lại hoặc xuất mẫu hiệu chỉnh judge mà không cần Qdrant),
câu trả lời, trích dẫn, cảnh báo, token và chi phí, latency từng bước, điểm judge.

- Từ chối đếm trực tiếp (`is_abstention`), không qua judge. "Từ chối sai" chia thêm theo context có chứa nguồn gold
  hay không: từ chối khi retrieval đã trượt là hành vi đúng của bước trả lời (giữ faithfulness).
- Latency đo tuần tự từng câu, không tải đồng thời. TTFT của user = rewrite + retrieval + TTFT của LLM.
- Chi phí: trước khi chạy in ước tính, quá `--max-cost` (mặc định $0.30) thì từ chối chạy; trong khi chạy, sắp vượt
  `--max-cost` thì dừng. Mọi lời gọi API còn đi qua trần ngày và trần dự án (`app.core.costs`); chạm trần thì dừng,
  lưu phần đã chạy với hậu tố _partial và `complete = false`.
- Judge chạy tuần tự. Hết quota ngày của provider judge thì ngừng chấm nhưng vẫn sinh câu trả lời cho các câu còn
  lại; `judge.missing` ghi số câu chưa có điểm, chấm nốt bằng --rejudge-missing.
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from qdrant_client import AsyncQdrantClient
from run_retrieval_eval import (
    RESULTS_DIR,
    DirtyTreeError,
    check_git_clean,
    corpus_identity,
    git_state,
    latency_stats,
)

from app.core.config import get_settings
from app.core.costs import BudgetExceededError, get_cost_ledger
from app.core.rag_config import JudgeProfile, RagConfig, load_rag_config
from app.evaluation.golden import GoldenItem, is_cross_lingual, load_golden
from app.evaluation.judge import (
    METRICS,
    Judge,
    JudgeCase,
    QuotaExhaustedError,
    QuotaTracker,
    build_judge,
    judge_identity,
)
from app.evaluation.retrieval_metrics import ChunkRef, covers, hit_at, recall_at, source_ranks
from app.generation.answer import AnswerGenerator
from app.generation.prompts import page_range
from app.ingestion.manifest import load_manifest
from app.retrieval.embedding import build_embedder
from app.retrieval.index import SYSTEM_USER_ID, IndexMismatchError, check_collection
from app.retrieval.llm import LlmUsage, build_llm_client
from app.retrieval.query import QueryProcessor
from app.retrieval.rerank import LlmReranker
from app.retrieval.search import Retriever
from app.retrieval.sparse import SparseEncoder

DEFAULT_GOLDEN = ROOT / "eval" / "datasets" / "golden_v1.jsonl"
ANSWER_TIMEOUT_SECONDS = 90
DEFAULT_MAX_COST_USD = 0.30
STEPS = ("rewrite", "embed", "sparse", "search", "rerank", "retrieval", "llm_ttft", "generation", "ttft", "total")
CONTEXT_FIELDS = ("chunk_id", "doc_id", "title", "so_hieu", "language", "heading_path", "article", "page", "page_end",
                  "amended", "amended_by", "text")
# Token ước tính cho mỗi câu, dư so với số đo 06/10/2026 (28 câu: trả lời trung bình 2160 token vào, 150 token ra
# với Sol, 95 với Luna; viết lại câu hỏi khoảng 210 vào, 33 ra).
ANSWER_TOKENS_EST = (3000, 500)
REWRITE_TOKENS_EST = (400, 100)
QUERY_EMBED_TOKENS_EST = 60
JUDGE_TOKENS_EST = (5000, 3000)


def stratified(items: list[GoldenItem], n: int) -> list[GoldenItem]:
    """Golden set xếp theo loại câu, nên lấy đều mỗi `len/n` câu là trải đều các loại."""
    step = max(1, len(items) // n)
    return items[::step][:n]


def mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def estimate_cost(
    config: RagConfig, items: list[GoldenItem], judge_calls: int, profile: JudgeProfile | None, answers: bool = True
) -> dict[str, float]:
    """Chi phí dự kiến (USD) của một lần chạy, theo số token ước tính mỗi lời gọi."""
    estimate = {"answers": 0.0, "judge": 0.0}
    if answers:
        follow_ups = sum(bool(item.history) for item in items)
        rewrite = config.price(config.query.model).cost(*REWRITE_TOKENS_EST) if config.query.rewrite == "llm" else 0.0
        estimate["answers"] = (
            len(items) * config.price(config.generation.answer_model).cost(*ANSWER_TOKENS_EST)
            + len(items) * config.price(config.embedding.model).cost(QUERY_EMBED_TOKENS_EST, 0)
            + follow_ups * rewrite
        )
    if profile and judge_calls:
        estimate["judge"] = judge_calls * config.price(profile.model, profile.service_tier).cost(*JUDGE_TOKENS_EST)
    estimate["total"] = estimate["answers"] + estimate["judge"]
    return estimate


def check_estimate(estimate: dict[str, float], max_cost: float | None) -> float:
    """Trả về mức trần của lần chạy; ước tính vượt trần thì báo lỗi trước khi gọi API."""
    limit = DEFAULT_MAX_COST_USD if max_cost is None else max_cost
    print(f"Chi phí dự kiến: ${estimate['total']:.4f} (trả lời ${estimate['answers']:.4f}, judge "
          f"${estimate['judge']:.4f}); trần của lần chạy ${limit:.2f}")
    if estimate["total"] > limit:
        raise BudgetExceededError(
            f"chi phí dự kiến ${estimate['total']:.4f} vượt trần ${limit:.2f} của lần chạy; chạy lại với "
            "--max-cost nếu đã được duyệt"
        )
    return limit


def print_quota(name: str, profile: JudgeProfile, planned_calls: int) -> None:
    requests_left, tokens_left = QuotaTracker(get_cost_ledger(), profile).remaining()
    parts = []
    if requests_left is not None:
        parts.append(f"còn {requests_left}/{profile.rpd} request")
    if tokens_left is not None:
        parts.append(f"còn {tokens_left}/{profile.tpd} token")
    quota = ", ".join(parts) or "không giới hạn theo ngày"
    print(f"Judge {name} ({profile.provider}/{profile.model}): {quota} trong ngày quota ({profile.quota_reset}); "
          f"lần chạy cần {planned_calls} lời gọi")
    if requests_left is not None and planned_calls > requests_left:
        print(f"  Quota không đủ: chấm được tối đa {max(requests_left, 0)} lời gọi (retry cũng tính) rồi dừng, "
              "chấm nốt bằng --rejudge-missing vào ngày quota sau")


def needs_judge(record: dict[str, Any]) -> bool:
    """Câu có câu trả lời nhưng chưa có lần chấm nào thành công."""
    if record["answer"]["status"] == "failed":
        return False
    runs = record.get("judge", {}).get("runs", [])
    return not any(run["error"] is None for run in runs)


class JudgeRunner:
    """Chấm một câu trả lời `repeats` lần. Hết quota ngày hoặc chạm trần chi phí thì ghi lý do vào `stopped` và
    không chấm nữa."""

    def __init__(self, judge: Judge, repeats: int):
        self.judge, self.repeats = judge, repeats
        self.stopped: str | None = None

    async def run(self, case: JudgeCase) -> tuple[dict[str, Any] | None, LlmUsage]:
        usage = LlmUsage()
        if self.stopped:
            return None, usage
        runs = []
        try:
            for _ in range(self.repeats):
                runs.append(await self.judge.judge(case, cache_case=self.repeats > 1))
                usage += runs[-1].usage
        except (QuotaExhaustedError, BudgetExceededError) as exc:
            self.stopped = f"{type(exc).__name__}: {exc}"
            print(f"\nNgừng chấm: {self.stopped}")
            if not runs:
                return None, usage
        record = {
            "scores": {metric: mean([run.scores()[metric] for run in runs]) for metric in METRICS},
            "runs": [run.record() for run in runs],
        }
        return record, usage


class E2EEvaluator:
    def __init__(self, config: RagConfig, qdrant: AsyncQdrantClient, judge: JudgeRunner | None):
        self.config, self.judge = config, judge
        self.mode = config.retrieval.mode
        self.retriever = Retriever(
            qdrant, config.collection_name, build_embedder(config),
            SparseEncoder(config.sparse.k1, config.sparse.b, config.sparse.avg_doc_len), config.retrieval,
        )
        self.query_client = build_llm_client()
        self.processor = QueryProcessor(self.query_client, config.query, config.price(config.query.model))
        self.reranker = (
            LlmReranker(self.query_client, config.rerank, config.price(config.rerank.model))
            if config.retrieval.reranker == "llm" else None
        )
        self.answer_client = build_llm_client(ANSWER_TIMEOUT_SECONDS, max_retries=2)
        self.generator = AnswerGenerator(
            self.answer_client, config.generation, config.price(config.generation.answer_model)
        )

    async def warm_up(self) -> None:
        """Mở sẵn kết nối (TLS) tới OpenAI và Qdrant, để câu đầu tiên không bị tính thêm thời gian bắt tay."""
        vectors = await self.retriever.encode(["khởi động"], dense=self.mode != "sparse", sparse=self.mode != "dense")
        await self.retriever.search_vectors(vectors, SYSTEM_USER_ID, self.mode, 1, with_payload=False)
        for client, model, effort in (
            (self.answer_client, self.config.generation.answer_model, self.config.generation.answer_reasoning_effort),
            (self.query_client, self.config.query.model, self.config.query.reasoning_effort),
        ):
            await client.responses.create(
                model=model, input="OK", reasoning={"effort": effort}, max_output_tokens=16, store=False
            )

    async def run_item(self, item: GoldenItem, cross_lingual: bool) -> dict[str, Any]:
        config = self.config
        history = [(turn.role, turn.content) for turn in item.history]
        plan = await self.processor.process(item.question, history)
        queries = plan.queries(config.query.translation_weight)
        vectors = await self.retriever.encode(
            [q for q, _ in queries], [w for _, w in queries], dense=self.mode != "sparse", sparse=self.mode != "dense"
        )
        limit = config.rerank.candidates if self.reranker else config.retrieval.top_k
        hits, search_ms = await self.retriever.search_vectors(vectors, SYSTEM_USER_ID, self.mode, limit)
        pipeline_usage = LlmUsage()
        pipeline_usage += plan.usage
        rerank_ms = 0.0
        record: dict[str, Any] = {
            "id": item.id, "type": item.type, "language": item.language, "cross_lingual": cross_lingual,
            "follow_up": bool(history), "question": item.question,
        }
        if plan.standalone != plan.question:
            record["standalone"] = plan.standalone
        if plan.method != "none":
            record["rewrite_method"] = plan.method
        if plan.error:
            record["query_error"] = plan.error
        if self.reranker:
            reranked = await self.reranker.rerank(plan.standalone, hits)
            hits, rerank_ms = reranked.hits, reranked.latency_ms
            pipeline_usage += reranked.usage
            if reranked.error:
                record["rerank_error"] = reranked.error
        hits = hits[: config.retrieval.top_k]
        payloads = [hit.payload for hit in hits]

        answer = await self.generator.generate(item.question, payloads, history)
        pipeline_usage += answer.usage

        retrieval_ms = vectors.embed_ms + vectors.sparse_ms + search_ms + rerank_ms
        llm_ttft = answer.ttft_ms if answer.ttft_ms is not None else answer.latency_ms
        timings = {
            "rewrite": plan.latency_ms, "embed": vectors.embed_ms, "sparse": vectors.sparse_ms, "search": search_ms,
            "rerank": rerank_ms, "retrieval": retrieval_ms, "llm_ttft": llm_ttft, "generation": answer.latency_ms,
            "ttft": plan.latency_ms + retrieval_ms + llm_ttft, "total": plan.latency_ms + retrieval_ms + answer.latency_ms,
        }
        record["contexts"] = [
            {"n": n, "score": round(hit.score, 4)} | {key: hit.payload.get(key) for key in CONTEXT_FIELDS}
            | {"pages": page_range(hit.payload)}
            for n, hit in enumerate(hits, start=1)
        ]
        record["answer"] = {
            "text": answer.text,
            "status": answer.status,
            "error": answer.error,
            "model": answer.model,
            "prompt_version": answer.prompt_version,
            "abstained": answer.abstained,
            "citations": [{"n": c.n, "chunk_id": c.chunk_id, "label": c.label} for c in answer.citations.citations],
            "invalid_citations": answer.citations.invalid,
            "warnings": answer.citations.warnings,
            "usage": vars(answer.usage),
        }
        record["timings_ms"] = {step: round(ms, 1) for step, ms in timings.items()}
        if item.gold_sources:
            refs = [ChunkRef.from_payload(payload) for payload in payloads]
            ranks = source_ranks(refs, item.gold_sources)
            k = config.retrieval.top_k
            record["retrieval"] = {
                "source_ranks": ranks,
                "hit": hit_at(ranks, k),
                "recall": recall_at(ranks, k),
                # Tỉ lệ chunk trong context chứa ít nhất một nguồn gold.
                "context_precision": (
                    sum(any(covers(ref, s) for s in item.gold_sources) for ref in refs) / len(refs) if refs else 0.0
                ),
            }

        judge_usage = LlmUsage()
        if self.judge and answer.status != "failed":
            judged, judge_usage = await self.judge.run(
                JudgeCase(item.question, item.reference_answer, payloads, answer.text, history)
            )
            if judged:
                record["judge"] = judged
        record["cost_usd"] = {
            "pipeline": round(pipeline_usage.cost_usd + vectors.usage.cost_usd, 6),
            "judge": round(judge_usage.cost_usd, 6),
        }
        return record


def group_values(record: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("all", "all"),
        ("type", record["type"]),
        ("language", record["language"]),
        ("cross_lingual", "cross_lingual" if record["cross_lingual"] else "same_language"),
        ("turn", "follow_up" if record["follow_up"] else "first_turn"),
    ]


def quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in rows if "retrieval" in r]
    unanswerable = [r for r in rows if "retrieval" not in r]
    refused = [r for r in answerable if r["answer"]["abstained"]]

    def rate(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    result: dict[str, Any] = {
        "n": len(rows),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "correct_refusal": rate(sum(r["answer"]["abstained"] for r in unanswerable), len(unanswerable)),
        "false_refusal": rate(len(refused), len(answerable)),
        # Từ chối dù context có chứa nguồn gold: lỗi của bước trả lời, không phải của retrieval.
        "false_refusal_gold_in_context": rate(sum(r["retrieval"]["hit"] == 1 for r in refused), len(answerable)),
        "hit": mean([r["retrieval"]["hit"] for r in answerable]),
        "recall": mean([r["retrieval"]["recall"] for r in answerable]),
        "context_precision": mean([r["retrieval"]["context_precision"] for r in answerable]),
        "invalid_citation_rate": rate(sum(bool(r["answer"]["invalid_citations"]) for r in rows), len(rows)),
        "answers_with_amendment_warning": sum(bool(r["answer"]["warnings"]) for r in rows),
        "failed_answers": sum(r["answer"]["status"] == "failed" for r in rows),
    }
    judged = [r for r in rows if "judge" in r]
    result["judged"] = len(judged)
    for metric in METRICS:
        values = [r["judge"]["scores"][metric] for r in judged]
        result[metric] = mean(values)
        result[f"{metric}_n"] = sum(v is not None for v in values)
    return result


def summarize(questions: list[dict[str, Any]], judge_repeats: int) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for record in questions:
        for dimension, value in group_values(record):
            grouped[dimension][value].append(record)
    summary: dict[str, Any] = {
        "quality": {
            dimension: {value: quality(rows) for value, rows in sorted(values.items())}
            for dimension, values in grouped.items()
        },
        "latency_ms": {step: latency_stats([q["timings_ms"][step] for q in questions]) for step in STEPS},
        "ttft_ms": {
            turn: latency_stats(values) | {"n": len(values)}
            for turn, values in (
                ("first_turn", [q["timings_ms"]["ttft"] for q in questions if not q["follow_up"]]),
                ("follow_up", [q["timings_ms"]["ttft"] for q in questions if q["follow_up"]]),
            )
            if values
        },
    }

    def usage_mean(path: str, key: str) -> float:
        values = [q["answer"]["usage"][key] for q in questions] if path == "answer" else [
            run["usage"][key] for q in questions for run in q.get("judge", {}).get("runs", [])
        ]
        return round(sum(values) / len(values), 1) if values else 0.0

    pipeline = [q["cost_usd"]["pipeline"] for q in questions]
    judge = [q["cost_usd"]["judge"] for q in questions]
    summary["cost_usd"] = {
        "pipeline_per_question": round(sum(pipeline) / len(pipeline), 6),
        "pipeline_total": round(sum(pipeline), 4),
        "judge_per_question": round(sum(judge) / len(judge), 6),
        "judge_total": round(sum(judge), 4),
    }
    keys = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")
    summary["tokens_mean"] = {
        "answer": {key: usage_mean("answer", key) for key in keys},
        "judge_call": {key: usage_mean("judge", key) for key in keys},
    }
    judge_latency = [run["latency_ms"] for q in questions for run in q.get("judge", {}).get("runs", [])]
    if judge_latency:
        summary["judge_latency_ms"] = latency_stats(judge_latency)
    if judge_repeats > 1:
        labels = [
            {run["correctness"] for run in q["judge"]["runs"] if not run["error"]} for q in questions if "judge" in q
        ]
        summary["judge_consistency"] = {
            "correctness_same_label": round(sum(len(s) == 1 for s in labels) / len(labels), 4) if labels else None
        }
    return summary


def judge_block(identity: dict[str, Any] | None, repeats: int, questions: list[dict[str, Any]],
                stopped: str | None) -> dict[str, Any]:
    return (identity or {}) | {
        "repeats": repeats,
        "judged": sum("judge" in q and not needs_judge(q) for q in questions),
        "missing": sum(needs_judge(q) for q in questions) if repeats else None,
        "stopped_reason": stopped,
    }


async def run(
    golden_path: Path,
    overrides: list[str],
    only: list[str] | None,
    n: int | None,
    judge_repeats: int,
    judge_name: str | None,
    max_cost: float | None,
) -> dict[str, Any]:
    config = load_rag_config(overrides=overrides)
    manifest = load_manifest()
    items = load_golden(golden_path)
    if only:
        items = [item for item in items if item.id in only]
    elif n:
        items = stratified(items, n)
    name = judge_name or config.eval.judge
    profile = config.judge_profile(name) if judge_repeats else None
    estimate = estimate_cost(config, items, len(items) * judge_repeats, profile)
    limit = check_estimate(estimate, max_cost)
    per_question = estimate["total"] / max(len(items), 1)
    ledger = get_cost_ledger()
    spent_before = ledger.spent_today()
    identity = judge_identity(name, profile, config.eval.judge_prompt_version) if profile else None
    runner = None
    if profile:
        print_quota(name, profile, len(items) * judge_repeats)
        runner = JudgeRunner(build_judge(profile, config.eval.judge_prompt_version, config.prices), judge_repeats)
    qdrant = AsyncQdrantClient(url=get_settings().qdrant_url)
    questions: list[dict[str, Any]] = []
    stopped: str | None = None
    try:
        await check_collection(qdrant, config.collection_name, config.index_signature())
        corpus = await corpus_identity(qdrant, config.collection_name, SYSTEM_USER_ID)
        evaluator = E2EEvaluator(config, qdrant, runner)
        print(f"config_version={config.config_version}, {len(items)} câu, trả lời bằng "
              f"{config.generation.answer_model}:{config.generation.answer_reasoning_effort}, judge "
              f"{identity['provider'] + '/' + identity['model'] if identity else 'không'} x{judge_repeats}. "
              f"Hôm nay đã tiêu ${spent_before:.4f}/${ledger.limit_usd:.2f}, cả dự án "
              f"${ledger.spent_total():.4f}/${ledger.project_limit_usd or 0:.2f}")
        await evaluator.warm_up()
        for index, item in enumerate(items, start=1):
            spent_run = sum(q["cost_usd"]["pipeline"] + q["cost_usd"]["judge"] for q in questions)
            if spent_run + per_question > limit:
                stopped = f"lần chạy đã tiêu ${spent_run:.4f}, câu tiếp theo có thể vượt trần ${limit:.2f}"
                print(f"\nDừng ở câu {item.id}: {stopped}")
                break
            try:
                questions.append(await evaluator.run_item(item, is_cross_lingual(item, manifest)))
            except BudgetExceededError as exc:
                stopped = str(exc)
                print(f"\nDừng ở câu {item.id}: {exc}")
                break
            pipeline = sum(q["cost_usd"]["pipeline"] for q in questions)
            judge = sum(q["cost_usd"]["judge"] for q in questions)
            print(f"\r{index}/{len(items)} câu, trả lời ${pipeline:.4f}, judge ${judge:.4f}", end="", flush=True)
        print()
    finally:
        await qdrant.close()
    if not questions:
        raise BudgetExceededError(stopped or "không chạy được câu nào")

    return {
        "kind": "e2e",
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "config_version": config.config_version,
        "overrides": overrides,
        "git": git_state(),
        "corpus": corpus,
        "complete": stopped is None,
        "stopped_reason": stopped,
        "golden": {
            "path": golden_path.relative_to(ROOT).as_posix() if golden_path.is_relative_to(ROOT) else str(golden_path),
            "questions": len(questions),
            "sample": n if n and not only else None,
        },
        "judge": judge_block(identity, judge_repeats, questions, runner.stopped if runner else None),
        "config": config.model_dump(exclude={"prices"}),
        "cost_estimate_usd": {key: round(value, 4) for key, value in estimate.items()},
        "cost_ledger": {"spent_before_usd": round(spent_before, 4), "spent_after_usd": round(ledger.spent_today(), 4)},
        "notes": [
            "Từ chối đếm trực tiếp bằng is_abstention; false_refusal_gold_in_context là từ chối dù context có nguồn gold.",
            "Điểm judge của mỗi câu là trung bình các lần chấm; faithfulness/citation chỉ tính trên câu trả lời có ý.",
            "ttft = rewrite + retrieval + llm_ttft; latency đo tuần tự, không tải đồng thời.",
        ],
        "summary": summarize(questions, judge_repeats),
        "questions": questions,
    }


async def rejudge_missing(path: Path, golden_path: Path, judge_name: str | None, max_cost: float | None) -> dict:
    """Chấm các câu chưa có điểm trong một file kết quả e2e, dùng câu trả lời và context đã lưu. Chỉ gộp với các lần
    chấm trước khi cùng judge (provider, model, prompt version)."""
    results = json.loads(path.read_text(encoding="utf-8"))
    if results.get("kind") != "e2e":
        raise ValueError(f"{path} không phải kết quả e2e")
    config = load_rag_config()
    previous = results.get("judge", {})
    name = judge_name or previous.get("profile") or config.eval.judge
    profile = config.judge_profile(name)
    identity = judge_identity(name, profile, config.eval.judge_prompt_version)
    keys = ("provider", "model", "prompt_version", "reasoning_effort")
    if previous.get("judged") and any(previous.get(key) != identity[key] for key in keys):
        raise ValueError(
            f"file đã được chấm bởi {[previous.get(k) for k in keys]}, judge hiện tại là {[identity[k] for k in keys]}; "
            "không gộp hai judge trong một kết quả"
        )
    repeats = previous.get("repeats") or 1
    missing = [q for q in results["questions"] if needs_judge(q)]
    estimate = estimate_cost(config, [], len(missing) * repeats, profile, answers=False)
    check_estimate(estimate, max_cost)
    print_quota(name, profile, len(missing) * repeats)
    golden = {item.id: item for item in load_golden(golden_path)}
    runner = JudgeRunner(build_judge(profile, config.eval.judge_prompt_version, config.prices), repeats)
    judged = 0
    for index, record in enumerate(missing, start=1):
        item = golden[record["id"]]
        case = JudgeCase(
            record["question"], item.reference_answer, record["contexts"], record["answer"]["text"],
            [(turn.role, turn.content) for turn in item.history],
        )
        result, usage = await runner.run(case)
        if result is None:
            break
        record["judge"] = result
        record["cost_usd"]["judge"] = round(record["cost_usd"]["judge"] + usage.cost_usd, 6)
        judged += 1
        print(f"\r{index}/{len(missing)} câu", end="", flush=True)
    print()
    results["judge"] = judge_block(identity, repeats, results["questions"], runner.stopped)
    results["summary"] = summarize(results["questions"], repeats)
    results.setdefault("rejudge_log", []).append({
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git": git_state(),
        "judged": judged,
        "missing_after": results["judge"]["missing"],
        "stopped_reason": runner.stopped,
    })
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Đã chấm thêm {judged} câu, còn thiếu {results['judge']['missing']}; đã ghi lại {path}")
    return results


def fmt(value: float | None, width: int = 7) -> str:
    return (f"{value:.3f}" if value is not None else "-").rjust(width)


def print_report(results: dict[str, Any]) -> None:
    summary = results["summary"]
    quality_rows = summary["quality"]
    judge = results["judge"]
    print(f"\nChất lượng ({results['golden']['questions']} câu; judge {judge.get('provider')}/{judge.get('model')} "
          f"x{judge['repeats']}, đã chấm {judge['judged']}, còn thiếu {judge['missing']})")
    print(f"{'nhóm':<28} {'n':>3} {'hit':>7} {'correct':>7} {'faith':>7} {'citP':>7} {'citR':>7} {'relev':>7} "
          f"{'từ chối đúng':>13} {'từ chối sai':>12}")
    for dimension in ("all", "type", "cross_lingual", "turn"):
        for value, row in quality_rows.get(dimension, {}).items():
            label = value if dimension == "all" else f"{dimension}={value}"
            print(f"{label:<28} {row['n']:>3} {fmt(row['hit'])} {fmt(row['correctness'])} {fmt(row['faithfulness'])} "
                  f"{fmt(row['citation_precision'])} {fmt(row['citation_recall'])} {fmt(row['relevancy'])} "
                  f"{fmt(row['correct_refusal'], 13)} {fmt(row['false_refusal'], 12)}")
    overall = quality_rows["all"]["all"]
    print(f"Từ chối sai dù context có nguồn gold: {fmt(overall['false_refusal_gold_in_context'], 0)}; "
          f"câu trả lời có [n] sai: {fmt(overall['invalid_citation_rate'], 0)}; "
          f"lỗi trả lời: {overall['failed_answers']}")
    lat = summary["latency_ms"]
    print("\nLatency (ms, p50 / p95, tuần tự): " + ", ".join(
        f"{step} {lat[step]['p50']:.0f} / {lat[step]['p95']:.0f}" for step in STEPS
    ))
    for turn, stats in summary["ttft_ms"].items():
        print(f"TTFT user {turn} (n={stats['n']}): p50 {stats['p50']:.0f} / p95 {stats['p95']:.0f} ms")
    if "judge_latency_ms" in summary:
        stats = summary["judge_latency_ms"]
        print(f"Latency judge mỗi lời gọi: p50 {stats['p50']:.0f} / p95 {stats['p95']:.0f} ms")
    cost, tokens = summary["cost_usd"], summary["tokens_mean"]
    print(f"\nChi phí: trả lời ${cost['pipeline_per_question']:.5f}/câu (tổng ${cost['pipeline_total']:.4f}), "
          f"judge ${cost['judge_per_question']:.5f}/câu (tổng ${cost['judge_total']:.4f})")
    for name, row in tokens.items():
        print(f"Token trung bình mỗi lần gọi ({name}): " + ", ".join(f"{k} {v:.0f}" for k, v in row.items()))
    if judge.get("stopped_reason"):
        print(f"Judge dừng sớm: {judge['stopped_reason']}")
    if not results["complete"]:
        print(f"CHƯA XONG: {results['stopped_reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ",
                        help="ghi đè config/rag.toml cho thí nghiệm, phải kèm config_version riêng")
    parser.add_argument("--only", nargs="+", metavar="ID", help="chỉ chạy các câu này (để soi lỗi, không lưu)")
    parser.add_argument("--n", type=int, help="chỉ chạy n câu trải đều theo loại (lưu với hậu tố -n<N>)")
    parser.add_argument("--judge", metavar="TÊN", help="hồ sơ judge trong [judges.<tên>]; mặc định [eval] judge")
    parser.add_argument("--judge-repeats", type=int, default=1, help="số lần judge chấm mỗi câu trả lời")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--rejudge-missing", type=Path, metavar="FILE",
                        help="chấm các câu chưa có điểm trong file kết quả e2e này, không sinh lại câu trả lời")
    parser.add_argument("--max-cost", type=float, metavar="USD",
                        help=f"trần chi phí của lần chạy (mặc định ${DEFAULT_MAX_COST_USD:.2f})")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument("--allow-dirty", action="store_true", help="vẫn chạy và lưu khi code chưa commit")
    args = parser.parse_args()

    try:
        if not args.only:
            check_git_clean(args.allow_dirty)
        if args.rejudge_missing:
            asyncio.run(rejudge_missing(args.rejudge_missing.resolve(), args.golden.resolve(), args.judge, args.max_cost))
            return 0
        repeats = 0 if args.no_judge else args.judge_repeats
        results = asyncio.run(
            run(args.golden.resolve(), args.set, args.only, args.n, repeats, args.judge, args.max_cost)
        )
    except (BudgetExceededError, DirtyTreeError, IndexMismatchError, KeyError, ValueError) as exc:
        print(exc)
        return 1
    print_report(results)
    if args.only:
        return 0
    suffix = (f"-n{args.n}" if args.n else "") + ("" if results["complete"] else "_partial")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{results['run_at'][:10]}_{results['config_version']}_e2e{suffix}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Đã lưu {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
