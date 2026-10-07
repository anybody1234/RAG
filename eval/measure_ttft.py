"""Đo TTFT của bước trả lời trên context thật, cho nhiều model / mức suy luận.

Mỗi câu hỏi chạy đúng pipeline của config (viết lại câu hỏi khi có lịch sử, retrieval top_k), rồi gửi cùng một
context cho từng biến thể model:effort, thứ tự biến thể xoay vòng theo câu để không biến thể nào luôn chạy trước.
Chạy tuần tự, không có tải đồng thời.

    python eval/measure_ttft.py                                   # Sol low (mức thấp nhất Sol nhận), Luna none, Luna low
    python eval/measure_ttft.py --variant gpt-6.1-sol:low --n 10

Mẫu câu hỏi: cứ `len/n` câu lấy một câu (golden set xếp theo loại nên mẫu trải đều các loại), cộng mọi câu
multi_turn để có số cho lượt hỏi tiếp. Kết quả lưu vào eval/results/<YYYY-MM-DD>_<config_version>_ttft.json.

TTFT của LLM: từ lúc gửi request tới token câu trả lời đầu tiên (gồm thời gian suy luận).
TTFT ước tính cho user: viết lại câu hỏi + retrieval + TTFT của LLM, chưa tính backend và mạng tới trình duyệt.
"""

import argparse
import asyncio
import json
import sys
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
from app.core.rag_config import RagConfig, ReasoningEffort, load_rag_config
from app.evaluation.golden import GoldenItem, load_golden
from app.generation.answer import AnswerGenerator, AnswerResult
from app.retrieval.embedding import build_embedder
from app.retrieval.index import SYSTEM_USER_ID, IndexMismatchError, check_collection
from app.retrieval.llm import LlmUsage, build_llm_client
from app.retrieval.query import QueryProcessor
from app.retrieval.search import Retriever
from app.retrieval.sparse import SparseEncoder

DEFAULT_GOLDEN = ROOT / "eval" / "datasets" / "golden_v1.jsonl"
DEFAULT_VARIANTS = ["gpt-6.1-sol:low", "gpt-6-luna:none", "gpt-6-luna:low"]
ANSWER_TIMEOUT_SECONDS = 90


def sample(items: list[GoldenItem], n: int) -> list[GoldenItem]:
    step = max(1, len(items) // n)
    chosen = {item.id for item in items[::step][:n]} | {item.id for item in items if item.history}
    return [item for item in items if item.id in chosen]


def parse_variant(text: str) -> tuple[str, ReasoningEffort]:
    model, sep, effort = text.rpartition(":")
    if not sep or effort not in ("none", "low", "medium", "high", "xhigh", "max"):
        raise ValueError(f"biến thể phải có dạng model:effort, ví dụ gpt-6.1-sol:low: {text!r}")
    return model, effort  # type: ignore[return-value]


def answer_record(result: AnswerResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "error": result.error,
        "ttft_ms": round(result.ttft_ms, 1) if result.ttft_ms is not None else None,
        "latency_ms": round(result.latency_ms, 1),
        "usage": vars(result.usage),
        "abstained": result.abstained,
        "citations": [c.n for c in result.citations.citations],
        "invalid_citations": result.citations.invalid,
        "answer": result.text,
    }


async def run(
    golden: Path, variants: list[str], n: int, overrides: list[str], follow_up_only: bool = False
) -> dict[str, Any]:
    config: RagConfig = load_rag_config(overrides=overrides)
    items = sample(load_golden(golden), n)
    if follow_up_only:
        items = [item for item in items if item.history]
    parsed = [parse_variant(v) for v in variants]
    llm_client = build_llm_client(timeout=ANSWER_TIMEOUT_SECONDS, max_retries=2)
    generators = {
        variant: AnswerGenerator(
            llm_client,
            config.generation.model_copy(update={"answer_model": model, "answer_reasoning_effort": effort}),
            config.price(model),
        )
        for variant, (model, effort) in zip(variants, parsed, strict=True)
    }
    processor = QueryProcessor(build_llm_client(), config.query, config.price(config.query.model))
    qdrant = AsyncQdrantClient(url=get_settings().qdrant_url)
    retriever = Retriever(
        qdrant, config.collection_name, build_embedder(config),
        SparseEncoder(config.sparse.k1, config.sparse.b, config.sparse.avg_doc_len), config.retrieval,
    )
    mode = config.retrieval.mode

    async def retrieve(item: GoldenItem) -> tuple[dict[str, Any], list[dict[str, Any]], LlmUsage]:
        plan = await processor.process(item.question, [(t.role, t.content) for t in item.history])
        queries = plan.queries(config.query.translation_weight)
        vectors = await retriever.encode(
            [q for q, _ in queries], [w for _, w in queries], dense=mode != "sparse", sparse=mode != "dense"
        )
        hits, search_ms = await retriever.search_vectors(vectors, SYSTEM_USER_ID, mode, config.retrieval.top_k)
        retrieval_ms = vectors.embed_ms + vectors.sparse_ms + search_ms
        record = {
            "id": item.id, "type": item.type, "language": item.language, "follow_up": bool(item.history),
            "standalone": plan.standalone if plan.standalone != plan.question else None,
            "rewrite_method": plan.method, "rewrite_error": plan.error,
            "rewrite_ms": round(plan.latency_ms, 1), "retrieval_ms": round(retrieval_ms, 1),
            "chunks": [hit.payload.get("chunk_id") for hit in hits],
        }
        usage = plan.usage
        usage.cost_usd += vectors.usage.cost_usd
        return record, [hit.payload for hit in hits], usage

    questions: list[dict[str, Any]] = []
    total_cost = 0.0
    try:
        await check_collection(qdrant, config.collection_name, config.index_signature())
        corpus = await corpus_identity(qdrant, config.collection_name, SYSTEM_USER_ID)
        # Mở sẵn kết nối (TLS) tới OpenAI và Qdrant, không tính vào số đo.
        _, payloads, _ = await retrieve(items[0])
        for generator in generators.values():
            total_cost += (await generator.generate(items[0].question, payloads)).usage.cost_usd
        for index, item in enumerate(items):
            record, payloads, usage = await retrieve(item)
            total_cost += usage.cost_usd
            record["answers"] = {}
            history = [(t.role, t.content) for t in item.history]
            order = variants[index % len(variants):] + variants[: index % len(variants)]
            for variant in order:
                result = await generators[variant].generate(item.question, payloads, history)
                record["answers"][variant] = answer_record(result)
                total_cost += result.usage.cost_usd
            questions.append(record)
            print(f"\r{index + 1}/{len(items)} câu, ${total_cost:.3f}", end="", flush=True)
        print()
    finally:
        await qdrant.close()

    summary = {}
    for variant in variants:
        rows = [(q, q["answers"][variant]) for q in questions]
        ok = [(q, a) for q, a in rows if a["ttft_ms"] is not None]
        if not ok:
            summary[variant] = {"n": 0, "failed": len(rows)}
            continue

        def e2e(follow_up: bool, ok: list = ok) -> dict[str, float] | None:
            values = [q["rewrite_ms"] + q["retrieval_ms"] + a["ttft_ms"] for q, a in ok if q["follow_up"] == follow_up]
            return latency_stats(values) | {"n": len(values)} if values else None

        summary[variant] = {
            "n": len(ok),
            "failed": len(rows) - len(ok),
            "llm_ttft_ms": latency_stats([a["ttft_ms"] for _, a in ok]),
            "llm_total_ms": latency_stats([a["latency_ms"] for _, a in ok]),
            "user_ttft_ms": {"first_turn": e2e(False), "follow_up": e2e(True)},
            "output_tokens_mean": round(sum(a["usage"]["output_tokens"] for _, a in ok) / len(ok), 1),
            "reasoning_tokens_mean": round(sum(a["usage"]["reasoning_tokens"] for _, a in ok) / len(ok), 1),
            "input_tokens_mean": round(sum(a["usage"]["input_tokens"] for _, a in ok) / len(ok), 1),
            "cost_usd_mean": round(sum(a["usage"]["cost_usd"] for _, a in ok) / len(ok), 6),
            "abstained": sum(a["abstained"] for _, a in ok),
            "invalid_citations": sum(len(a["invalid_citations"]) for _, a in ok),
        }
    return {
        "kind": "ttft",
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "config_version": config.config_version,
        "overrides": overrides,
        "git": git_state(),
        "corpus": corpus,
        "variants": variants,
        "questions_n": len(questions),
        "steps_ms": {
            "rewrite_follow_up": latency_stats([q["rewrite_ms"] for q in questions if q["follow_up"]]),
            "retrieval": latency_stats([q["retrieval_ms"] for q in questions]),
        },
        "total_cost_usd": round(total_cost, 4),
        "notes": [
            "llm_ttft: từ lúc gửi request tới token câu trả lời đầu tiên, gồm thời gian suy luận.",
            "user_ttft = rewrite + retrieval + llm_ttft; chưa tính backend và mạng tới trình duyệt.",
            "Chạy tuần tự, không tải đồng thời; câu đầu tiên chạy thêm một lần để mở kết nối, không tính.",
        ],
        "summary": summary,
        "questions": questions,
    }


def print_report(results: dict[str, Any]) -> None:
    steps = results["steps_ms"]
    print(f"\n{results['questions_n']} câu. Retrieval p50/p95 {steps['retrieval']['p50']:.0f} / "
          f"{steps['retrieval']['p95']:.0f} ms; viết lại câu hỏi (lượt hỏi tiếp) "
          f"{steps['rewrite_follow_up']['p50']:.0f} / {steps['rewrite_follow_up']['p95']:.0f} ms")
    print(f"{'biến thể':<20} {'n':>3} {'TTFT LLM':>13} {'tổng LLM':>13} {'TTFT lượt đầu':>15} "
          f"{'TTFT lượt sau':>15} {'out':>6} {'reason':>7} {'$/câu':>9} {'từ chối':>8}")

    def cell(stats: dict | None, width: int) -> str:
        return (f"{stats['p50']:.0f} / {stats['p95']:.0f}" if stats else "-").rjust(width)

    for variant, s in results["summary"].items():
        if not s["n"]:
            print(f"{variant:<20} lỗi {s['failed']} câu")
            continue
        print(f"{variant:<20} {s['n']:>3} {cell(s['llm_ttft_ms'], 13)} {cell(s['llm_total_ms'], 13)} "
              f"{cell(s['user_ttft_ms']['first_turn'], 15)} {cell(s['user_ttft_ms']['follow_up'], 15)} "
              f"{s['output_tokens_mean']:>6.0f} {s['reasoning_tokens_mean']:>7.0f} {s['cost_usd_mean']:>9.5f} "
              f"{s['abstained']:>8}")
    print(f"Chi phí cả lần đo: ${results['total_cost_usd']:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--variant", action="append", metavar="MODEL:EFFORT",
                        help=f"mặc định: {' '.join(DEFAULT_VARIANTS)}")
    parser.add_argument("--n", type=int, default=20, help="số câu lấy đều theo golden set (cộng mọi câu multi_turn)")
    parser.add_argument("--follow-up-only", action="store_true",
                        help="chỉ chạy câu multi_turn, để so các cách viết lại câu hỏi (query.rewrite)")
    parser.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument("--allow-dirty", action="store_true", help="vẫn chạy và lưu khi code chưa commit")
    args = parser.parse_args()
    try:
        check_git_clean(args.allow_dirty)
        results = asyncio.run(run(
            args.golden.resolve(), args.variant or DEFAULT_VARIANTS, args.n, args.set, args.follow_up_only
        ))
    except (DirtyTreeError, IndexMismatchError, ValueError) as exc:
        print(exc)
        return 1
    print_report(results)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{results['run_at'][:10]}_{results['config_version']}_ttft.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Đã lưu {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
