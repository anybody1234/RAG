"""Đọc data/manifest.json, danh sách văn bản của bộ dữ liệu phát triển."""

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal, cast

import pymupdf
from pydantic import BaseModel

from app.core.config import REPO_ROOT

MANIFEST_PATH = REPO_ROOT / "data" / "manifest.json"
RAW_DIR = REPO_ROOT / "data" / "raw"


class ManifestFile(BaseModel):
    filename: str
    url: str
    sha256: str


class ConsolidatedText(BaseModel):
    so_hieu: str
    date: date
    page_url: str


class ManifestDocument(BaseModel):
    doc_id: str
    pair_id: str | None
    title: str
    so_hieu: str
    language: Literal["vi", "en"]
    kind: Literal["original", "translation"]
    issued_date: date
    effective_date: date
    status: str
    amended_by: list[str] = []
    amended_articles: list[str] = []
    # Danh sách amended_articles được lập từ văn bản nào, để kiểm tra lại được.
    amended_articles_source: str | None = None
    amends: list[str] = []
    consolidated: ConsolidatedText | None = None
    source: str
    page_url: str
    files: list[ManifestFile]


class Manifest(BaseModel):
    version: int
    checked_at: date
    documents: list[ManifestDocument]

    def get(self, doc_id: str) -> ManifestDocument | None:
        return next((doc for doc in self.documents if doc.doc_id == doc_id), None)


def amended_article_numbers(amended_articles: list[str]) -> set[int]:
    """"Điều 139 khoản 1" -> 139. Tính theo cả Điều, kể cả khi chỉ một khoản bị sửa."""
    return {int(m.group(1)) for text in amended_articles if (m := re.search(r"Điều (\d+)", text))}


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    return Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def manifest_sha256(path: Path = MANIFEST_PATH) -> str:
    """Định danh phiên bản bộ dữ liệu, ghi vào kết quả eval."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pdf_pages(doc: ManifestDocument, raw_dir: Path = RAW_DIR) -> list[str]:
    """Text của từng trang PDF.

    Văn bản gồm nhiều file (Luật Doanh nghiệp 2020) được đánh số trang liên tục theo thứ tự file trong
    manifest: phần tử thứ i ứng với trang i + 1.
    """
    pages: list[str] = []
    for file in doc.files:
        with pymupdf.open(raw_dir / file.filename) as pdf:
            # get_text() mặc định ("text") trả về str; stub của pymupdf khai báo kiểu hợp nên cần cast.
            pages.extend(cast(str, page.get_text()) for page in pdf)
    return pages
