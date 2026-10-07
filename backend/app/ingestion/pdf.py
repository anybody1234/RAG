"""Trích text từ PDF bằng PyMuPDF.

Có hai cách trích, chọn theo loại tài liệu (xem `parsers.parse_pdf_files`):
- `extract_pdf_lines`: text thô theo dòng, dùng cho văn bản luật. Ranh giới dòng còn nguyên nên regex nhận
  đúng đầu "Điều N.", "1.", "a)". Golden set cũng được kiểm tra trên text thô này.
- `extract_pdf_markdown`: markdown của pymupdf4llm, dùng cho tài liệu khác vì có heading và bảng. Không dùng
  cho văn bản luật: trên PDF Công báo, pymupdf4llm dính tiêu đề Điều vào đoạn trước (Điều 146 Bộ luật Lao
  động) và tách một điểm a), b) thành nhiều list item, nên chỉ nhận được 215/220 Điều.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pymupdf4llm

from app.ingestion.models import Block
from app.ingestion.ocr import OcrEngine
from app.ingestion.text_cleaning import (
    clean_vietnamese_text,
    dehyphenate_lines,
    expand_ligatures,
    fix_replacement_chars,
    strip_markdown_inline,
)

# Trang có ít ký tự hơn ngưỡng này mà có ảnh thì coi là trang scan, cần OCR.
MIN_TEXT_CHARS = 50

_CONG_BAO_HEADER = re.compile(r"^CÔNG BÁO/Số [\d +]+/Ngày \d{1,2}-\d{1,2}-\d{4}(?: \d+)?$")
_CONTINUED_FROM = re.compile(r"^\(Tiếp theo Công báo số [\d +]+\)$")
_CONTINUED_IN = re.compile(r"^\(Xem tiếp Công báo số [\d +]+\)$")
# Khối chữ ký số của Cổng Thông tin điện tử Chính phủ ở trang đầu bản Công báo. Dòng đầu là "Ký bởi:", hoặc
# "Người ký:" (Công báo năm 2025); bản năm 2026 ghi "Ngày ký" thay cho "Thời gian ký". Các dòng "Email:",
# "Cơ quan:" chỉ bị bỏ khi nằm trong khối này, vì phụ lục mẫu biểu (Nghị định 356) có dòng "Email:……" thật.
_SIGNATURE_START = re.compile(r"^(Ký bởi|Người ký): ")
_SIGNATURE_REST = re.compile(r"^(Email|Cơ quan|Thời gian ký|Ngày ký): ")
# Tên người ký dài bị ngắt sang dòng sau ("Ký bởi: Cổng Thông tin điện tử Chính" / "phủ"): dòng ngắn, không có
# dấu hai chấm, nằm ngay sau dòng đầu của khối.
_SIGNATURE_WRAP_MAX_CHARS = 30

# Header/footer lặp: dòng nằm trong _EDGE_LINES dòng đầu hoặc cuối trang, xuất hiện (sau khi thay chữ số
# bằng #) ở ít nhất _RUNNING_MIN_RATIO số trang và ít nhất _RUNNING_MIN_PAGES trang. Bắt được số trang,
# "CÔNG BÁO/Số .../Ngày ...", "Translated Version by Viet An Law Firm - Vietnam".
_EDGE_LINES = 3
_RUNNING_MIN_PAGES = 3
_RUNNING_MIN_RATIO = 0.5


@dataclass
class PdfText:
    blocks: list[Block]
    page_count: int
    needs_ocr_pages: list[int]


def _edge_key(line: str) -> str:
    return re.sub(r"\d+", "#", line)


def _running_lines(pages: list[list[str]]) -> set[str]:
    counts: Counter[str] = Counter()
    for lines in pages:
        counts.update({_edge_key(line) for line in lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]})
    threshold = max(_RUNNING_MIN_PAGES, math.ceil(_RUNNING_MIN_RATIO * sum(1 for lines in pages if lines)))
    return {key for key, n in counts.items() if n >= threshold}


def _strip_page_furniture(lines: list[str], running: set[str]) -> list[str]:
    """Bỏ header/footer, chữ ký số và dòng nối số Công báo của một trang."""
    start = next((i + 1 for i, line in enumerate(lines) if _CONTINUED_FROM.match(line)), 0)
    if start:
        # Trang đầu file Công báo thứ hai lặp lại tên văn bản trước dòng "(Tiếp theo Công báo số ...)".
        lines = lines[start:]
    kept: list[str] = []
    in_signature = after_start = False
    for i, line in enumerate(lines):
        at_edge = i < _EDGE_LINES or i >= len(lines) - _EDGE_LINES
        if _SIGNATURE_START.match(line):
            in_signature = after_start = True
            continue
        if in_signature:
            if _SIGNATURE_REST.match(line):
                after_start = False
                continue
            if after_start and ":" not in line and len(line.strip()) <= _SIGNATURE_WRAP_MAX_CHARS:
                continue
        in_signature = after_start = False
        if _CONG_BAO_HEADER.match(line) or _CONTINUED_IN.match(line) or (at_edge and _edge_key(line) in running):
            continue
        kept.append(line)
    return kept


def _page_lines(text: str) -> list[str]:
    text = fix_replacement_chars(expand_ligatures(clean_vietnamese_text(text)))
    return [line for line in text.split("\n") if line.strip()]


def extract_pdf_lines(paths: Sequence[Path], ocr: OcrEngine | None = None) -> PdfText:
    """Text thô từng dòng của một văn bản (có thể gồm nhiều file PDF, số trang đánh liên tục)."""
    lines: list[str] = []
    pages_of_lines: list[int] = []
    needs_ocr: list[int] = []
    page_offset = 0
    for path in paths:
        with pymupdf.open(path) as pdf:
            pages: list[list[str]] = []
            for page in pdf:
                page_lines = _page_lines(page.get_text())
                if sum(len(line) for line in page_lines) < MIN_TEXT_CHARS and page.get_images():
                    if ocr is None:
                        needs_ocr.append(page_offset + page.number + 1)
                    else:
                        page_lines = _page_lines(ocr.ocr_page(page))
                pages.append(page_lines)
            page_count = pdf.page_count
        running = _running_lines(pages)
        for index, page_lines in enumerate(pages):
            for line in _strip_page_furniture(page_lines, running):
                lines.append(line)
                pages_of_lines.append(page_offset + index + 1)
        page_offset += page_count

    blocks = [
        Block(line, page)
        for line, page in zip(dehyphenate_lines(lines), pages_of_lines, strict=True)
        if line.strip()
    ]
    return PdfText(blocks=blocks, page_count=page_offset, needs_ocr_pages=needs_ocr)


def extract_pdf_markdown(paths: Sequence[Path]) -> list[Block]:
    """Từng đoạn markdown (heading `#`, bảng `|`) của pymupdf4llm, đã bỏ định dạng inline.

    Header/footer do mô hình layout của pymupdf4llm phát hiện và bỏ. Không bật OCR của pymupdf4llm: trang
    scan đã được `extract_pdf_lines` đánh dấu `needs_ocr`.
    """
    blocks: list[Block] = []
    page_offset = 0
    for path in paths:
        pages = pymupdf4llm.to_markdown(
            str(path), page_chunks=True, header=False, footer=False, use_ocr=False, show_progress=False
        )
        for page in pages:
            number = page_offset + page["metadata"]["page_number"]
            text = _page_lines(strip_markdown_inline(page["text"]))
            blocks += [Block(line, number) for line in text]
        page_offset += len(pages)
    return blocks
