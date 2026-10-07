"""Kiểm tra golden set: schema, đoạn trích có thật ở đúng trang PDF, phân bố loại câu hỏi.

Chạy từ thư mục gốc của repo:
    python eval/validate_golden.py                    # kiểm tra eval/datasets/golden_v1.jsonl
    python eval/validate_golden.py --fix-pages        # tự sửa số trang khi đoạn trích nằm ở trang khác
    python eval/validate_golden.py FILE --no-distribution
"""

import argparse
import sys
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.evaluation.golden import (
    TARGET_DISTRIBUTION,
    load_golden,
    save_golden,
    validate_golden,
)
from app.ingestion.manifest import load_manifest, read_pdf_pages

DEFAULT_PATH = Path(__file__).resolve().parent / "datasets" / "golden_v1.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--fix-pages", action="store_true", help="sửa số trang khi đoạn trích chỉ có ở 1 trang khác")
    parser.add_argument("--no-distribution", action="store_true", help="bỏ qua kiểm tra phân bố (khi đang soạn dở)")
    args = parser.parse_args()

    manifest = load_manifest()
    items = load_golden(args.path)

    @cache
    def get_pages(doc_id: str) -> list[str]:
        return read_pdf_pages(manifest.get(doc_id))

    def run():
        return validate_golden(items, manifest, get_pages, check_distribution=not args.no_distribution)

    report = run()
    if args.fix_pages and report.page_fixes:
        by_id = {item.id: item for item in items}
        for item_id, index, page in report.page_fixes:
            by_id[item_id].gold_sources[index].page = page
        save_golden(items, args.path)
        print(f"Đã sửa số trang cho {len(report.page_fixes)} đoạn trích.\n")
        report = run()

    print(f"{report.total} câu, {report.reviewed} câu đã duyệt")
    for question_type, (low, high) in TARGET_DISTRIBUTION.items():
        count = report.type_counts[question_type]
        ratio = count / report.total if report.total else 0
        print(f"  {question_type:<15} {count:>3}  {ratio:>4.0%}  (mục tiêu {low:.0%}–{high:.0%})")
    if report.answerable:
        print(f"  khác ngôn ngữ với nguồn: {report.cross_lingual}/{report.answerable} câu có nguồn "
              f"({report.cross_lingual / report.answerable:.0%})")
    print("  ngôn ngữ câu hỏi: " + ", ".join(f"{lang} {n}" for lang, n in sorted(report.language_counts.items())))
    if report.tag_counts:
        print("  tags: " + ", ".join(f"{tag} {n}" for tag, n in report.tag_counts.most_common()))

    if report.errors:
        print(f"\n{len(report.errors)} lỗi:")
        for error in report.errors:
            print(f"  - {error}")
        return 1
    print("\nKhông có lỗi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
