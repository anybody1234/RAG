"""Duyệt golden set bằng file Markdown thay vì sửa JSONL trực tiếp (CLI: eval/review_golden.py).

Trong file .md: tick `- [x] Đã duyệt` cho câu đúng. Câu cần sửa thì ghi vào dòng `Ghi chú:`; câu có ghi chú
không được đánh dấu reviewed và được liệt kê ra để sửa.
"""

import re

from app.evaluation.golden import GoldenItem, is_cross_lingual
from app.ingestion.manifest import Manifest

HEADER = """# Duyệt golden set {name}

Với mỗi câu:
- Đúng hết thì tick `- [x] Đã duyệt`.
- Sai hoặc cần sửa thì ghi vào dòng `Ghi chú:` (câu hỏi, đáp án, nguồn hay loại câu hỏi sai ở đâu).

Kiểm tra 3 điều:
1. Câu hỏi tự nhiên, giống người thật hỏi.
2. Đáp án chuẩn đúng và đủ theo đoạn trích.
3. Đoạn trích thực sự chứa đáp án.

Xong thì chạy `{apply_command}`.
"""

ROLE_LABELS = {"user": "Người dùng", "assistant": "Trợ lý"}


def render_review(items: list[GoldenItem], manifest: Manifest, name: str, apply_command: str) -> str:
    parts = [HEADER.format(name=name, apply_command=apply_command)]
    for item in items:
        cross = " · khác ngôn ngữ nguồn" if is_cross_lingual(item, manifest) else ""
        tags = f" · {', '.join(item.tags)}" if item.tags else ""
        lines = [
            f"## {item.id} · {item.type} · {item.language}{cross}{tags}",
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
    return "\n".join(parts)


def parse_review(text: str) -> dict[str, tuple[bool, str]]:
    """{id câu hỏi: (đã tick, ghi chú)} đọc từ file Markdown đã duyệt."""
    decisions: dict[str, tuple[bool, str]] = {}
    for section in re.split(r"(?m)^## ", text)[1:]:
        item_id = section.split(" ", 1)[0].strip()
        checked = bool(re.search(r"(?m)^- \[[xX]\] Đã duyệt", section))
        note = re.search(r"(?ms)^Ghi chú:(.*)\Z", section)
        decisions[item_id] = (checked, note.group(1).strip() if note else "")
    return decisions


def apply_review(items: list[GoldenItem], decisions: dict[str, tuple[bool, str]]) -> list[tuple[str, str]]:
    """Đặt `reviewed` theo kết quả duyệt; trả về (id, ghi chú) của các câu cần sửa.

    Câu không có trong file duyệt giữ nguyên trạng thái.
    """
    needs_fix = []
    for item in items:
        checked, note = decisions.get(item.id, (item.reviewed, ""))
        item.reviewed = checked and not note
        if note:
            needs_fix.append((item.id, note))
    return needs_fix
