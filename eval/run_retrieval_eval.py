"""Eval retrieval trên golden set: Hit/Recall/MRR/nDCG ở top-5 và top-50, latency từng bước, chi phí mỗi câu.

Chạy từ thư mục gốc của repo, sau khi đã index (`python scripts/index.py`):
    python eval/run_retrieval_eval.py                       # dense, sparse, hybrid với config/rag.toml
    python eval/run_retrieval_eval.py --modes hybrid
    # Thí nghiệm: ghi đè config, phải đặt config_version riêng.
    python eval/run_retrieval_eval.py --modes hybrid --set config_version=v0.2-exp-translate
                                      --set query.translate=true

Kết quả lưu vào eval/results/<YYYY-MM-DD>_<config_version>_retrieval.json.

- Câu unanswerable không có nguồn nên không tính metric, nhưng vẫn được truy vấn để đo latency.
- Câu multi_turn: khi `query.rewrite = false` thì dùng nguyên câu hỏi cuối; bật thì viết lại theo `history`.
- Mỗi câu chỉ xử lý câu hỏi (LLM) và embed một lần; các chế độ dùng chung kết quả đó. Latency của một chế độ:
  `retrieval` = embed + sparse + search + rerank (định nghĩa trong CLAUDE.md), `total` = rewrite + retrieval.
  Các câu chạy tuần tự, không có tải đồng thời. Truy vấn không lấy payload; payload chunk (để chấm và để
  rerank) được tải một lần từ Qdrant trước khi chạy.
"""

import argparse
import asyncio
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.core.rag_config import RagConfig, RetrievalMode, load_rag_config
from app.evaluation.golden import GoldenItem, is_cross_lingual, load_golden
from app.evaluation.retrieval_metrics import (
    ChunkRef,
    covers,
    mean_metrics,
    percentile,
    question_metrics,
    source_ranks,
)
from app.ingestion.manifest import load_manifest
from app.retrieval.embedding import EmbeddingUsage, build_embedder
from app.retrieval.index import SYSTEM_USER_ID, IndexMismatchError, check_collection, user_filter
from app.retrieval.llm import LlmUsage, build_llm_client
from app.retrieval.query import QueryProcessor
from app.retrieval.rerank import LlmReranker
from app.retrieval.search import Hit, Retriever
from app.retrieval.sparse import SparseEncoder

DEFAULT_GOLDEN = ROOT / "eval" / "datasets" / "golden_v1.jsonl"
RESULTS_DIR = ROOT / "eval" / "results"
MODES: tuple[RetrievalMode, ...] = ("dense", "sparse", "hybrid")
KS = (5, 50)
TOP_SAVED = 5
SHOWN = ("hit@5", "hit@50", "recall@5", "recall@50", "mrr@5", "ndcg@5", "ndcg@50")
STEPS = ("rewrite", "embed", "sparse", "search", "rerank", "retrieval", "total")
PAYLOAD_FIELDS = ["chunk_id", "doc_id", "page", "page_end", "text", "title", "heading_path"]


async def load_index(client: AsyncQdrantClient, collection: str, user_id: str) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    offset = None
    while True:
        points, offset = await client.scroll(
            collection, scroll_filter=user_filter(user_id), limit=256, offset=offset, with_payload=PAYLOAD_FIELDS
        )
        payloads |= {str(point.id): point.payload or {} for point in points}
        if offset is None:
            return payloads


# File chưa track ở các thư mục này là code hoặc config, nên làm kết quả không tái lập được từ commit.
_CODE_PATHS = ("backend/", "eval/", "config/", "scripts/")
_NOT_CODE_PATHS = ("eval/results/",)


class DirtyTreeError(RuntimeError):
    """Code có thay đổi chưa commit mà không chạy với --allow-dirty."""


def git_state() -> dict[str, str | bool | None]:
    """Commit hiện tại và cờ `dirty`: có file đã track bị sửa, hoặc có file code/config chưa track."""

    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return None

    commit, status = git("rev-parse", "--short", "HEAD"), git("status", "--porcelain", "--untracked-files=all")
    dirty = None if status is None else any(
        line[:2] != "??" or (line[3:].startswith(_CODE_PATHS) and not line[3:].startswith(_NOT_CODE_PATHS))
        for line in status.splitlines()
    )
    return {"commit": commit.strip() if commit else None, "dirty": dirty}


def check_git_clean(allow_dirty: bool) -> dict[str, str | bool | None]:
    """Gọi trước khi chạy eval, tức trước khi tốn tiền API: chỉ lưu kết quả tái lập được từ một commit."""
    state = git_state()
    if state["dirty"] is not False and not allow_dirty:
        raise DirtyTreeError(
            "code có thay đổi chưa commit (hoặc không đọc được git). Commit trước khi chạy eval, hoặc thêm "
            "--allow-dirty để vẫn lưu kết quả (kết quả ghi git.dirty = true)."
        )
    return state


def groups_of(item: GoldenItem, cross_lingual: bool) -> list[tuple[str, str]]:
    return [
        ("all", "all"),
        ("type", item.type),
        ("language", item.language),
        ("cross_lingual", "cross_lingual" if cross_lingual else "same_language"),
    ]


def latency_stats(values: list[float]) -> dict[str, float]:
    return {
        "p50": round(percentile(values, 50), 1),
        "p95": round(percentile(values, 95), 1),
        "mean": round(sum(values) / len(values), 1),
        "max": round(max(values), 1),
    }


class Evaluator:
    def __init__(self, config: RagConfig, client: AsyncQdrantClient, modes: list[RetrievalMode]):
        self.config, self.client, self.modes = config, client, modes
        self.retriever = Retriever(
            client,
            config.collection_name,
            build_embedder(config),
            SparseEncoder(config.sparse.k1, config.sparse.b, config.sparse.avg_doc_len),
            config.retrieval,
        )
        llm_client = build_llm_client()
        self.processor = QueryProcessor(llm_client, config.query, config.price(config.query.model))
        self.reranker = (
            LlmReranker(llm_client, config.rerank, config.price(config.rerank.model))
            if config.retrieval.reranker == "llm" else None
        )
        self.need_dense = any(mode != "sparse" for mode in modes)
        self.need_sparse = any(mode != "dense" for mode in modes)
        self.limit = max(max(KS), config.rerank.candidates if self.reranker else 0)
        self.payloads: dict[str, dict[str, Any]] = {}
        self.chunks: dict[str, ChunkRef] = {}
        self.embedding_usage = EmbeddingUsage()
        self.llm_usage = LlmUsage()

    async def load(self) -> None:
        self.payloads = await load_index(self.client, self.config.collection_name, SYSTEM_USER_ID)
        self.chunks = {point_id: ChunkRef.from_payload(payload) for point_id, payload in self.payloads.items()}

    async def warm_up(self) -> None:
        """Mở sẵn kết nối tới OpenAI và Qdrant để câu đầu tiên không bị tính thêm thời gian bắt tay TLS."""
        plan = await self.processor.process("Thời gian thử việc tối đa là bao lâu?")
        queries = plan.queries(self.config.query.translation_weight)
        vectors = await self.retriever.encode(
            [q for q, _ in queries], [w for _, w in queries], self.need_dense, self.need_sparse
        )
        for mode in self.modes:
            hits, _ = await self.retriever.search_vectors(vectors, SYSTEM_USER_ID, mode, self.limit, with_payload=False)
            if self.reranker and mode == self.modes[0]:
                await self.reranker.rerank(plan.standalone, [Hit(h.id, h.score, self.payloads[h.id]) for h in hits])

    async def run_item(self, item: GoldenItem, cross_lingual: bool) -> dict[str, Any]:
        plan = await self.processor.process(item.question, [(turn.role, turn.content) for turn in item.history])
        queries = plan.queries(self.config.query.translation_weight)
        vectors = await self.retriever.encode(
            [q for q, _ in queries], [w for _, w in queries], self.need_dense, self.need_sparse
        )
        self.embedding_usage += vectors.usage
        self.llm_usage += plan.usage
        record: dict[str, Any] = {
            "id": item.id, "type": item.type, "language": item.language, "cross_lingual": cross_lingual,
        }
        if plan.standalone != plan.question:
            record["standalone"] = plan.standalone
        if plan.translation:
            record["translation"] = plan.translation
        if plan.error:
            record["query_error"] = plan.error
        record["modes"] = {}
        for mode in self.modes:
            hits, search_ms = await self.retriever.search_vectors(
                vectors, SYSTEM_USER_ID, mode, self.limit, with_payload=False
            )
            result: dict[str, Any] = {}
            # Chi phí của chế độ: xử lý câu hỏi + embed (trừ sparse, không cần embed) + rerank.
            rerank_ms = 0.0
            cost = plan.usage.cost_usd + (vectors.usage.cost_usd if mode != "sparse" else 0.0)
            if self.reranker:
                reranked = await self.reranker.rerank(
                    plan.standalone, [Hit(hit.id, hit.score, self.payloads[hit.id]) for hit in hits]
                )
                hits, rerank_ms = reranked.hits, reranked.latency_ms
                self.llm_usage += reranked.usage
                cost += reranked.usage.cost_usd
                if reranked.error:
                    result["rerank_error"] = reranked.error
            timings = {
                "rewrite": plan.latency_ms,
                "embed": vectors.embed_ms if mode != "sparse" else 0.0,
                "sparse": vectors.sparse_ms if mode != "dense" else 0.0,
                "search": search_ms,
                "rerank": rerank_ms,
            }
            timings["retrieval"] = timings["embed"] + timings["sparse"] + timings["search"] + timings["rerank"]
            timings["total"] = timings["rewrite"] + timings["retrieval"]
            result |= {
                "timings_ms": {step: round(ms, 2) for step, ms in timings.items()},
                "cost_usd": round(cost, 7),
                "top": [[self.chunks[hit.id].chunk_id, round(hit.score, 4)] for hit in hits[:TOP_SAVED]],
            }
            if item.gold_sources:
                ranks = source_ranks([self.chunks[hit.id] for hit in hits[: max(KS)]], item.gold_sources)
                result["source_ranks"] = ranks
                result["metrics"] = question_metrics(ranks, KS)
            record["modes"][mode] = result
        return record


def summarize(modes: list[RetrievalMode], items: list[GoldenItem], questions: list[dict[str, Any]]) -> dict:
    by_id = {item.id: item for item in items}
    summary: dict = {}
    for mode in modes:
        grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for record in questions:
            if metrics := record["modes"][mode].get("metrics"):
                for dimension, value in groups_of(by_id[record["id"]], record["cross_lingual"]):
                    grouped[dimension][value].append(metrics)
        costs = [record["modes"][mode]["cost_usd"] for record in questions]
        summary[mode] = {
            "metrics": {
                dimension: {
                    value: {"n": len(rows)} | {k: round(v, 4) for k, v in mean_metrics(rows).items()}
                    for value, rows in sorted(values.items())
                }
                for dimension, values in grouped.items()
            },
            "latency_ms": {
                step: latency_stats([record["modes"][mode]["timings_ms"][step] for record in questions])
                for step in STEPS
            },
            "cost_usd": {"per_question_mean": round(sum(costs) / len(costs), 7), "total": round(sum(costs), 5)},
            "errors": {
                "query": sum("query_error" in record for record in questions),
                "rerank": sum("rerank_error" in record["modes"][mode] for record in questions),
            },
        }
    return summary


async def run(golden_path: Path, modes: list[RetrievalMode], overrides: list[str], only: list[str] | None) -> dict:
    config = load_rag_config(overrides=overrides)
    manifest = load_manifest()
    items = [item for item in load_golden(golden_path) if not only or item.id in only]
    client = AsyncQdrantClient(url=get_settings().qdrant_url)
    try:
        await check_collection(client, config.collection_name, config.index_signature())
        evaluator = Evaluator(config, client, modes)
        await evaluator.load()
        sources = [source for item in items for source in item.gold_sources]
        in_index = sum(any(covers(chunk, source) for chunk in evaluator.chunks.values()) for source in sources)
        print(f"config_version={config.config_version}, collection={config.collection_name}: "
              f"{len(evaluator.chunks)} chunk của user {SYSTEM_USER_ID}")
        print(f"{in_index}/{len(sources)} nguồn gold nằm trọn trong một chunk của index")
        await evaluator.warm_up()
        questions = []
        for n, item in enumerate(items, start=1):
            questions.append(await evaluator.run_item(item, is_cross_lingual(item, manifest)))
            print(f"\r{n}/{len(items)} câu", end="", flush=True)
        print()
    finally:
        await client.close()

    return {
        "kind": "retrieval",
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "config_version": config.config_version,
        "overrides": overrides,
        "git": git_state(),
        "golden": {
            "path": golden_path.relative_to(ROOT).as_posix() if golden_path.is_relative_to(ROOT) else str(golden_path),
            "questions": len(items),
            "scored": sum(bool(item.gold_sources) for item in items),
            "gold_sources": len(sources),
        },
        "index": {
            "collection": config.collection_name,
            "user_id": SYSTEM_USER_ID,
            "chunks": len(evaluator.chunks),
            "gold_sources_in_index": in_index,
        },
        "config": config.model_dump(exclude={"prices"}),
        "usage": {"embedding": vars(evaluator.embedding_usage), "llm": vars(evaluator.llm_usage)},
        "notes": [
            "Câu unanswerable không tính metric, vẫn tính latency.",
            "retrieval = embed + sparse + search + rerank; total = rewrite + retrieval.",
            "Latency đo tuần tự từng câu, không tải đồng thời; các chế độ dùng chung một lần xử lý câu hỏi và embed.",
        ],
        "modes": summarize(modes, items, questions),
        "questions": questions,
    }


def print_report(results: dict) -> None:
    modes = list(results["modes"])
    first = results["modes"][modes[0]]["metrics"]
    print(f"\nChất lượng ({results['golden']['scored']}/{results['golden']['questions']} câu có nguồn)")
    print(f"{'nhóm':<26} {'n':>3}  {'mode':<7}" + "".join(f"{name:>10}" for name in SHOWN))
    for dimension, values in first.items():
        for value in values:
            label = value if dimension == "all" else f"{dimension}={value}"
            for i, mode in enumerate(modes):
                row = results["modes"][mode]["metrics"][dimension][value]
                prefix = f"{label:<26} {row['n']:>3}" if i == 0 else " " * 30
                print(f"{prefix}  {mode:<7}" + "".join(f"{row[name]:>10.3f}" for name in SHOWN))
    print(f"\nLatency (ms, p50 / p95, {results['golden']['questions']} câu, tuần tự)")
    print(f"{'mode':<7} {'rewrite':>13} {'embed':>13} {'search':>11} {'rerank':>13} {'retrieval':>13} "
          f"{'total':>13} {'$/câu':>10} {'lỗi LLM':>8}")
    for mode in modes:
        summary = results["modes"][mode]
        lat = summary["latency_ms"]

        def cell(step: str, width: int, lat: dict = lat) -> str:
            return f"{lat[step]['p50']:.0f} / {lat[step]['p95']:.0f}".rjust(width)

        errors = summary["errors"]["query"] + summary["errors"]["rerank"]
        print(f"{mode:<7} {cell('rewrite', 13)} {cell('embed', 13)} {cell('search', 11)} {cell('rerank', 13)} "
              f"{cell('retrieval', 13)} {cell('total', 13)} {summary['cost_usd']['per_question_mean']:>10.6f} "
              f"{errors:>8}")
    usage = results["usage"]
    print(f"\nEmbedding: {usage['embedding']['requests']} request, {usage['embedding']['tokens']} token. "
          f"LLM: {usage['llm']['calls']} lần gọi, {usage['llm']['input_tokens']} token vào, "
          f"{usage['llm']['output_tokens']} token ra.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ",
                        help="ghi đè config/rag.toml cho thí nghiệm, ví dụ retrieval.rrf_k=20")
    parser.add_argument("--only", nargs="+", metavar="ID", help="chỉ chạy các câu này (để soi lỗi, không lưu)")
    parser.add_argument("--allow-dirty", action="store_true", help="vẫn chạy và lưu khi code chưa commit")
    args = parser.parse_args()

    try:
        if not args.only:
            check_git_clean(args.allow_dirty)
        results = asyncio.run(run(args.golden.resolve(), args.modes, args.set, args.only))
    except (DirtyTreeError, IndexMismatchError, ValueError) as exc:
        print(exc)
        return 1
    print_report(results)
    if args.only:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{results['run_at'][:10]}_{results['config_version']}_retrieval.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Đã lưu {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
