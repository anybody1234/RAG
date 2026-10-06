"""Eval retrieval trên golden set: Hit/Recall/MRR/nDCG ở top-5 và top-50, latency từng bước, cho 3 chế độ.

Chạy từ thư mục gốc của repo, sau khi đã index (`python scripts/index.py`):
    python eval/run_retrieval_eval.py                       # dense, sparse, hybrid
    python eval/run_retrieval_eval.py --modes hybrid

Kết quả lưu vào eval/results/<YYYY-MM-DD>_<config_version>_retrieval.json.

- Câu unanswerable không có nguồn nên không tính metric, nhưng vẫn được truy vấn để đo latency.
- Câu multi_turn dùng nguyên câu hỏi cuối, chưa viết lại theo lịch sử hội thoại (việc của P5).
- Mỗi câu chỉ embed một lần; dense và hybrid dùng chung vector. Latency của một chế độ là tổng các bước nó
  cần: embed (dense, hybrid), mã hoá sparse (sparse, hybrid) và truy vấn Qdrant. Các câu chạy tuần tự, không
  có tải đồng thời. Truy vấn không lấy payload; text chunk để chấm được tải một lần từ Qdrant trước khi chạy.
"""

import argparse
import asyncio
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.core.rag_config import RetrievalMode, get_rag_config
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
from app.retrieval.index import SYSTEM_USER_ID, user_filter
from app.retrieval.search import Retriever
from app.retrieval.sparse import SparseEncoder

DEFAULT_GOLDEN = ROOT / "eval" / "datasets" / "golden_v1.jsonl"
RESULTS_DIR = ROOT / "eval" / "results"
MODES: tuple[RetrievalMode, ...] = ("dense", "sparse", "hybrid")
KS = (5, 50)
TOP_SAVED = 5
SHOWN = ("hit@5", "hit@50", "recall@5", "recall@50", "mrr@5", "ndcg@5", "ndcg@50")


async def load_index(client: AsyncQdrantClient, collection: str, user_id: str) -> dict[str, ChunkRef]:
    chunks: dict[str, ChunkRef] = {}
    offset = None
    while True:
        points, offset = await client.scroll(
            collection, scroll_filter=user_filter(user_id), limit=256, offset=offset,
            with_payload=["chunk_id", "doc_id", "page", "page_end", "text"],
        )
        chunks |= {str(point.id): ChunkRef.from_payload(point.payload or {}) for point in points}
        if offset is None:
            return chunks


def git_state() -> dict[str, str | bool | None]:
    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    # Giống `git describe --dirty`: chỉ tính thay đổi trên file đã track, bỏ qua file chưa track.
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(status) if status is not None else None}


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


async def run(golden_path: Path, modes: list[RetrievalMode]) -> dict:
    config = get_rag_config()
    manifest = load_manifest()
    items = load_golden(golden_path)
    client = AsyncQdrantClient(url=get_settings().qdrant_url)
    retriever = Retriever(
        client,
        config.collection_name,
        build_embedder(config),
        SparseEncoder(config.sparse.k1, config.sparse.b, config.sparse.avg_doc_len),
        config.retrieval,
    )
    need_dense = any(mode != "sparse" for mode in modes)
    need_sparse = any(mode != "dense" for mode in modes)
    limit = max(KS)
    try:
        index = await load_index(client, config.collection_name, SYSTEM_USER_ID)
        sources = [source for item in items for source in item.gold_sources]
        in_index = sum(any(covers(chunk, source) for chunk in index.values()) for source in sources)
        print(f"config_version={config.config_version}, collection={config.collection_name}: "
              f"{len(index)} chunk của user {SYSTEM_USER_ID}")
        print(f"{in_index}/{len(sources)} nguồn gold nằm trọn trong một chunk của index"
              f"{'' if in_index == len(sources) else ' (index cũ hoặc chunking đã đổi: chạy lại scripts/index.py)'}")

        # Khởi động kết nối trước khi đo.
        warmup = await retriever.encode("khởi động", need_dense, need_sparse)
        for mode in modes:
            await retriever.search_vectors(warmup, SYSTEM_USER_ID, mode, limit, with_payload=False)

        usage = EmbeddingUsage()
        questions = []
        for n, item in enumerate(items, start=1):
            vectors = await retriever.encode(item.question, need_dense, need_sparse)
            usage += vectors.usage
            cross = is_cross_lingual(item, manifest)
            record: dict = {"id": item.id, "type": item.type, "language": item.language,
                            "cross_lingual": cross, "modes": {}}
            for mode in modes:
                hits, search_ms = await retriever.search_vectors(
                    vectors, SYSTEM_USER_ID, mode, limit, with_payload=False
                )
                timings = {
                    "embed": vectors.embed_ms if mode != "sparse" else 0.0,
                    "sparse": vectors.sparse_ms if mode != "dense" else 0.0,
                    "search": search_ms,
                }
                timings["total"] = sum(timings.values())
                result: dict = {
                    "timings_ms": {step: round(ms, 2) for step, ms in timings.items()},
                    "top": [[index[hit.id].chunk_id, round(hit.score, 4)] for hit in hits[:TOP_SAVED]],
                }
                if item.gold_sources:
                    ranks = source_ranks([index[hit.id] for hit in hits], item.gold_sources)
                    result["source_ranks"] = ranks
                    result["metrics"] = question_metrics(ranks, KS)
                record["modes"][mode] = result
            questions.append(record)
            print(f"\r{n}/{len(items)} câu", end="", flush=True)
        print()
    finally:
        await client.close()

    by_id = {item.id: item for item in items}
    summary: dict = {}
    for mode in modes:
        grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for record in questions:
            if metrics := record["modes"][mode].get("metrics"):
                for dimension, value in groups_of(by_id[record["id"]], record["cross_lingual"]):
                    grouped[dimension][value].append(metrics)
        steps = ("embed", "sparse", "search", "total")
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
                for step in steps
            },
        }

    return {
        "kind": "retrieval",
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "config_version": config.config_version,
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
            "chunks": len(index),
            "gold_sources_in_index": in_index,
        },
        "config": config.model_dump(exclude={"prices"}),
        "query_embedding_usage": vars(usage),
        "notes": [
            "Câu unanswerable không tính metric, vẫn tính latency.",
            "Câu multi_turn dùng câu hỏi cuối chưa viết lại.",
            "Latency đo tuần tự từng câu, không tải đồng thời; dense và hybrid dùng chung một lần embed.",
        ],
        "modes": summary,
        "questions": questions,
    }


def print_report(results: dict) -> None:
    modes = list(results["modes"])
    first = results["modes"][modes[0]]["metrics"]
    header = f"{'nhóm':<26} {'n':>3}  {'mode':<7}" + "".join(f"{name:>10}" for name in SHOWN)
    print(f"\nChất lượng ({results['golden']['scored']}/{results['golden']['questions']} câu có nguồn)")
    print(header)
    for dimension, values in first.items():
        for value in values:
            label = value if dimension == "all" else f"{dimension}={value}"
            for i, mode in enumerate(modes):
                row = results["modes"][mode]["metrics"][dimension][value]
                prefix = f"{label:<26} {row['n']:>3}" if i == 0 else " " * 30
                print(f"{prefix}  {mode:<7}" + "".join(f"{row[name]:>10.3f}" for name in SHOWN))
    print(f"\nLatency (ms, {results['golden']['questions']} câu, tuần tự)")
    print(f"{'mode':<7} {'embed p50':>10} {'embed p95':>10} {'search p50':>11} {'search p95':>11} "
          f"{'total p50':>10} {'total p95':>10} {'total max':>10}")
    for mode in modes:
        lat = results["modes"][mode]["latency_ms"]
        print(f"{mode:<7} {lat['embed']['p50']:>10} {lat['embed']['p95']:>10} {lat['search']['p50']:>11} "
              f"{lat['search']['p95']:>11} {lat['total']['p50']:>10} {lat['total']['p95']:>10} "
              f"{lat['total']['max']:>10}")
    usage = results["query_embedding_usage"]
    print(f"\nEmbed câu hỏi: {usage['requests']} request, {usage['tokens']} token, ${usage['cost_usd']:.5f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    results = asyncio.run(run(args.golden.resolve(), args.modes))
    print_report(results)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{results['run_at'][:10]}_{results['config_version']}_retrieval.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Đã lưu {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
