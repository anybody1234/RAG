"""Parse + chunk văn bản, xuất chunk ra data/processed/<doc_id>.jsonl để soi tay.

Chạy từ thư mục gốc của repo:
    python scripts/ingest.py                              # mọi văn bản trong data/manifest.json
    python scripts/ingest.py --doc vi-bo-luat-lao-dong-2019
    python scripts/ingest.py --file path/to/file.docx     # file bất kỳ, như khi user upload
"""

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.rag_config import get_rag_config
from app.ingestion.manifest import load_manifest
from app.ingestion.parsers import UnsupportedFileError
from app.ingestion.pipeline import IngestResult, ingest_file, ingest_manifest_document

PROCESSED_DIR = ROOT / "data" / "processed"


def write_chunks(doc_id: str, result: IngestResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc_id}.jsonl"
    path.write_text("".join(chunk.model_dump_json() + "\n" for chunk in result.chunks), encoding="utf-8")
    return path


def summary_row(doc_id: str, result: IngestResult, seconds: float) -> str:
    chunks = result.chunks
    tokens = [chunk.token_count for chunk in chunks]
    articles = len({chunk.article for chunk in chunks if chunk.article})
    pages = result.parsed.page_count or "-"
    mean = sum(tokens) / len(tokens) if tokens else 0
    return (
        f"{doc_id:<42} {result.parsed.structure:<8} {pages:>5} {len(result.parsed.needs_ocr_pages):>9} "
        f"{articles:>5} {len(chunks):>6} {mean:>8.0f} {max(tokens, default=0):>6} {seconds:>6.1f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--doc", action="append", help="doc_id trong manifest (lặp lại được)")
    parser.add_argument("--file", type=Path, help="file bất kỳ (PDF, DOCX, HTML, MD, TXT)")
    parser.add_argument("--out", type=Path, default=PROCESSED_DIR)
    args = parser.parse_args()

    config = get_rag_config()
    print(f"config_version={config.config_version}, max_tokens={config.chunking.max_tokens}, "
          f"overlap_ratio={config.chunking.overlap_ratio}, tokenizer theo {config.embedding.model}\n")
    print(f"{'doc_id':<42} {'cấu trúc':<8} {'trang':>5} {'needs_ocr':>9} {'Điều':>5} {'chunk':>6} "
          f"{'tok TB':>8} {'tok max':>6} {'giây':>6}")

    jobs: list[tuple[str, Callable[[], IngestResult]]] = []
    if args.file:
        jobs.append((args.file.stem, lambda: ingest_file(args.file, doc_id=args.file.stem)))
    else:
        manifest = load_manifest()
        for doc in manifest.documents:
            if not args.doc or doc.doc_id in args.doc:
                jobs.append((doc.doc_id, lambda doc=doc: ingest_manifest_document(doc)))

    failed = total_pages = ocr_pages = 0
    for doc_id, run in jobs:
        start = time.perf_counter()
        try:
            result = run()
        except (UnsupportedFileError, FileNotFoundError) as exc:
            failed += 1
            print(f"{doc_id:<42} LỖI: {exc}")
            continue
        write_chunks(doc_id, result, args.out)
        total_pages += result.parsed.page_count or 0
        ocr_pages += len(result.parsed.needs_ocr_pages)
        print(summary_row(doc_id, result, time.perf_counter() - start))

    print(f"\n{len(jobs) - failed}/{len(jobs)} văn bản OK, {failed} lỗi. "
          f"Trang needs_ocr: {ocr_pages}/{total_pages}. Chunk ghi vào {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
