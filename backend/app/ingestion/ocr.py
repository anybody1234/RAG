"""Interface OCR. Chưa có engine nào; trang thiếu text được đánh dấu `needs_ocr` và báo cho user.

Khi gắn OCR (Tesseract, PaddleOCR, ...), viết một class có method `ocr_page` rồi truyền vào `parse_file`.
"""

from typing import Protocol

import pymupdf


class OcrEngine(Protocol):
    def ocr_page(self, page: pymupdf.Page) -> str:
        """Trả về text của trang PDF (đã nhận dạng)."""
        ...
