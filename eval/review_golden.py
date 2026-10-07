"""Duyệt golden set bằng file Markdown thay vì sửa JSONL trực tiếp.

Chạy từ thư mục gốc của repo:
    python eval/review_golden.py export        # golden_v1.jsonl -> eval/datasets/golden_v1_review.md
    python eval/review_golden.py apply         # đọc file .md, đánh dấu reviewed cho câu đã tick
    python eval/review_golden.py export eval/datasets/golden_v2_draft.jsonl   # -> golden_v2_draft_review.md

Trong file .md: tick `- [x] Đã duyệt` cho câu đúng. Câu cần sửa thì ghi vào dòng `Ghi chú:`;
câu có ghi chú sẽ không được đánh dấu reviewed và được liệt kê ra để sửa.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.evaluation.golden import load_golden, save_golden
from app.evaluation.golden_review import apply_review, parse_review, render_review
from app.ingestion.manifest import load_manifest

DEFAULT_PATH = Path(__file__).resolve().parent / "datasets" / "golden_v1.jsonl"


def review_path(golden_path: Path) -> Path:
    return golden_path.with_name(f"{golden_path.stem}_review.md")


def display(path: Path) -> str:
    return str(path.relative_to(Path.cwd())) if path.is_relative_to(Path.cwd()) else str(path)


def export(golden_path: Path) -> None:
    name = golden_path.stem.removeprefix("golden_").replace("_", " ")
    command = "python eval/review_golden.py apply"
    if golden_path.resolve() != DEFAULT_PATH:
        command += f" {golden_path.as_posix()}"
    text = render_review(load_golden(golden_path), load_manifest(), name, command)
    out = review_path(golden_path)
    out.write_text(text, encoding="utf-8")
    print(f"Đã tạo {display(out.resolve())}")


def apply(golden_path: Path) -> None:
    items = load_golden(golden_path)
    needs_fix = apply_review(items, parse_review(review_path(golden_path).read_text(encoding="utf-8")))
    save_golden(items, golden_path)
    print(f"Đã duyệt {sum(item.reviewed for item in items)}/{len(items)} câu.")
    if needs_fix:
        print(f"{len(needs_fix)} câu có ghi chú cần sửa:")
        for item_id, note in needs_fix:
            print(f"  - {item_id}: {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["export", "apply"])
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH, help="file golden set (.jsonl)")
    args = parser.parse_args()
    export(args.path) if args.command == "export" else apply(args.path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
