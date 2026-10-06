"""Duyệt golden set bằng file Markdown thay vì sửa JSONL trực tiếp.

Chạy từ thư mục gốc của repo:
    python eval/review_golden.py export   # tạo eval/datasets/golden_v1_review.md
    python eval/review_golden.py apply    # đọc file .md, đánh dấu reviewed cho câu đã tick

Trong file .md: tick `- [x] Đã duyệt` cho câu đúng. Câu cần sửa thì ghi vào dòng `Ghi chú:`;
câu có ghi chú sẽ không được đánh dấu reviewed và được liệt kê ra để sửa.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.evaluation.golden import is_cross_lingual, load_golden, save_golden
from app.ingestion.manifest import load_manifest

DATASETS = Path(__file__).resolve().parent / "datasets"
GOLDEN_PATH = DATASETS / "golden_v1.jsonl"
REVIEW_PATH = DATASETS / "golden_v1_review.md"

HEADER = """# Duyệt golden set v1

Với mỗi câu:
- Đúng hết thì tick `- [x] Đã duyệt`.
- Sai hoặc cần sửa thì ghi vào dòng `Ghi chú:` (câu hỏi, đáp án, nguồn hay loại câu hỏi sai ở đâu).

Kiểm tra 3 điều:
1. Câu hỏi tự nhiên, giống người thật hỏi.
2. Đáp án chuẩn đúng và đủ theo đoạn trích.
3. Đoạn trích thực sự chứa đáp án.

Xong thì chạy `python eval/review_golden.py apply`.
"""

ROLE_LABELS = {"user": "Người dùng", "assistant": "Trợ lý"}


def export() -> None:
    manifest = load_manifest()
    parts = [HEADER]
    for item in load_golden(GOLDEN_PATH):
        cross = " · khác ngôn ngữ nguồn" if is_cross_lingual(item, manifest) else ""
        lines = [
            f"## {item.id} · {item.type} · {item.language}{cross}",
            f"- [{'x' if item.reviewed else ' '}] Đã duyệt",
            "",
        ]
        for turn in item.history:
            lines.append(f"> **{ROLE_LABELS[turn.role]}:** {turn.content}")
        if item.history:
            lines.append("")
        lines += [f"**Hỏi:** {item.question}", "", f"**Đáp án chuẩn:** {item.reference_answer}", ""]
        if item.gold_sources:
            lines.append("**Nguồn:**")
            lines += [f"- `{s.doc_id}` trang {s.page}: “{s.quote}”" for s in item.gold_sources]
        else:
            lines.append("**Nguồn:** không có (câu hỏi không có đáp án trong tài liệu)")
        lines += ["", "Ghi chú:", ""]
        parts.append("\n".join(lines))
    REVIEW_PATH.write_text("\n".join(parts), encoding="utf-8")
    print(f"Đã tạo {REVIEW_PATH.relative_to(Path.cwd()) if REVIEW_PATH.is_relative_to(Path.cwd()) else REVIEW_PATH}")


def apply() -> None:
    text = REVIEW_PATH.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)[1:]
    decisions: dict[str, tuple[bool, str]] = {}
    for section in sections:
        item_id = section.split(" ", 1)[0].strip()
        checked = bool(re.search(r"(?m)^- \[[xX]\] Đã duyệt", section))
        note = re.search(r"(?ms)^Ghi chú:(.*)\Z", section)
        decisions[item_id] = (checked, note.group(1).strip() if note else "")

    items = load_golden(GOLDEN_PATH)
    needs_fix = []
    for item in items:
        checked, note = decisions.get(item.id, (item.reviewed, ""))
        item.reviewed = checked and not note
        if note:
            needs_fix.append((item.id, note))
    save_golden(items, GOLDEN_PATH)

    print(f"Đã duyệt {sum(item.reviewed for item in items)}/{len(items)} câu.")
    if needs_fix:
        print(f"{len(needs_fix)} câu có ghi chú cần sửa:")
        for item_id, note in needs_fix:
            print(f"  - {item_id}: {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["export", "apply"])
    args = parser.parse_args()
    export() if args.command == "export" else apply()
    return 0


if __name__ == "__main__":
    sys.exit(main())
