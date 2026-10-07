"""Kiểm tra trích dẫn `[n]` trong câu trả lời: số nào trỏ tới chunk có thật, map sang văn bản/Điều/trang, và
cảnh báo khi Điều được trích dẫn đã bị sửa đổi (text trong index là bản gốc, có thể đã lỗi thời)."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.language import Language
from app.generation.prompts import ABSTENTION, page_range

# [1], [1][3], [1, 3]. Chỉ nhận số, nên "[...]" hay "[a]" trong câu trả lời không bị tính là trích dẫn.
_CITATION = re.compile(r"\[(\d+(?:\s*[,;\-–]\s*\d+)*)\]")
_RANGE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
# Khoảng dài hơn thế này (ví dụ [1-2000]) không phải trích dẫn khoảng: chỉ lấy hai đầu, để số sai vẫn bị tính là
# invalid thay vì nở thành hàng nghìn số.
MAX_RANGE = 10
_ARTICLE = re.compile(r"^(Điều|Article)\s+\d+", re.IGNORECASE)


@dataclass
class Citation:
    n: int
    chunk_id: str
    doc_id: str
    title: str
    so_hieu: str | None
    heading_path: str
    article: str | None
    page: int | None
    page_end: int | None
    amended: bool
    amended_by: list[str]
    label: str


@dataclass
class CitationCheck:
    # Trích dẫn hợp lệ theo thứ tự xuất hiện lần đầu, không lặp.
    citations: list[Citation] = field(default_factory=list)
    # Số [n] không trỏ tới chunk nào trong context.
    invalid: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def cited_numbers(text: str) -> list[int]:
    """Các số [n] theo thứ tự xuất hiện lần đầu, không lặp. Nhận cả [1, 3] và khoảng [1-3], [1–3]."""
    numbers: list[int] = []
    for group in _CITATION.findall(text):
        for part in re.split(r"\s*[,;]\s*", group):
            if m := _RANGE.fullmatch(part):
                low, high = int(m.group(1)), int(m.group(2))
                numbers += range(low, high + 1) if 0 <= high - low <= MAX_RANGE else [low, high]
            else:
                numbers.append(int(part))
    return list(dict.fromkeys(numbers))


def section_label(heading_path: str) -> str:
    """"Chương III > Mục 3 > Điều 35 > Khoản 2" -> "Điều 35, Khoản 2": bỏ Phần/Chương/Mục khi đã có Điều."""
    parts = [part.strip() for part in heading_path.split(">") if part.strip()]
    start = next((i for i, part in enumerate(parts) if _ARTICLE.match(part)), 0)
    return ", ".join(parts[start:])


def citation_label(payload: dict[str, Any], language: Language) -> str:
    """Ví dụ "45/2019/QH14, Điều 35, Khoản 2, tr. 21"."""
    parts = [payload.get("so_hieu") or payload.get("title") or payload.get("doc_id", "")]
    if section := section_label(payload.get("heading_path") or ""):
        parts.append(section)
    if pages := page_range(payload):
        parts.append(f"{'tr.' if language == 'vi' else 'p.'} {pages}")
    return ", ".join(parts)


def amendment_warnings(citations: Sequence[Citation], language: Language) -> list[str]:
    """Một cảnh báo cho mỗi Điều đã bị sửa đổi có trong trích dẫn."""
    groups: dict[tuple[str, str | None], list[Citation]] = {}
    for citation in citations:
        if citation.amended:
            groups.setdefault((citation.doc_id, citation.article), []).append(citation)
    warnings = []
    for group in groups.values():
        first = group[0]
        refs = "".join(f"[{c.n}]" for c in group)
        law = f"{first.title} ({first.so_hieu})" if first.so_hieu else first.title
        article = first.article or ("Nội dung" if language == "vi" else "The provision")
        by = ", ".join(first.amended_by)
        if language == "vi":
            warnings.append(
                f"{article} {law} đã được sửa đổi, bổ sung bởi {by}. Trích dẫn {refs} là nội dung bản gốc, "
                "có thể đã thay đổi."
            )
        else:
            warnings.append(
                f"{article} of the {law} has been amended by {by}. Citation {refs} shows the original text, "
                "which may be outdated."
            )
    return warnings


def check_citations(answer: str, payloads: Sequence[dict[str, Any]], language: Language) -> CitationCheck:
    """`payloads` là chunk trong context theo đúng thứ tự đã đánh số (bắt đầu từ 1)."""
    check = CitationCheck()
    for n in cited_numbers(answer):
        if not 1 <= n <= len(payloads):
            check.invalid.append(n)
            continue
        payload = payloads[n - 1]
        check.citations.append(Citation(
            n=n,
            chunk_id=payload.get("chunk_id", ""),
            doc_id=payload.get("doc_id", ""),
            title=payload.get("title", ""),
            so_hieu=payload.get("so_hieu"),
            heading_path=payload.get("heading_path", ""),
            article=payload.get("article"),
            page=payload.get("page"),
            page_end=payload.get("page_end"),
            amended=bool(payload.get("amended")),
            amended_by=list(payload.get("amended_by") or []),
            label=citation_label(payload, language),
        ))
    check.warnings = amendment_warnings(check.citations, language)
    return check


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip(" \n*_#>\"'").casefold()


def is_abstention(answer: str) -> bool:
    """Câu trả lời bắt đầu bằng câu từ chối (tiếng Việt hoặc tiếng Anh, bỏ qua markdown đậm/nghiêng ở đầu)."""
    start = _normalize(answer)
    return any(start.startswith(_normalize(phrase).rstrip(".")) for phrase in ABSTENTION.values())
