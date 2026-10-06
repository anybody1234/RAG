"""Parse + chunk một văn bản: văn bản trong data/manifest.json hoặc file user upload."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.rag_config import RagConfig, get_rag_config
from app.ingestion.chunking import build_chunks
from app.ingestion.generic_chunker import chunk_generic
from app.ingestion.legal_chunker import chunk_legal
from app.ingestion.manifest import RAW_DIR, ManifestDocument, amended_article_numbers
from app.ingestion.models import Chunk, DocumentMeta, ParsedDocument
from app.ingestion.ocr import OcrEngine
from app.ingestion.parsers import parse_file, parse_pdf_files
from app.ingestion.tokens import TokenCounter

_VIETNAMESE_LETTERS = set(
    "ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ"
)


@dataclass
class IngestResult:
    parsed: ParsedDocument
    chunks: list[Chunk]


def detect_language(text: str) -> Literal["vi", "en"]:
    """Tiếng Việt khi chữ có dấu tiếng Việt chiếm trên 5% số chữ cái (văn bản tiếng Việt thường trên 25%)."""
    letters = [char for char in text[:20_000].lower() if char.isalpha()]
    vietnamese = sum(char in _VIETNAMESE_LETTERS for char in letters)
    return "vi" if letters and vietnamese / len(letters) > 0.05 else "en"


def chunk_document(parsed: ParsedDocument, meta: DocumentMeta, config: RagConfig | None = None) -> list[Chunk]:
    config = config or get_rag_config()
    count = TokenCounter(config.embedding.model)
    max_tokens, overlap_ratio = config.chunking.max_tokens, config.chunking.overlap_ratio
    if parsed.structure == "legal":
        pieces = chunk_legal(parsed.blocks, meta.language, max_tokens, overlap_ratio, count)
    else:
        pieces = chunk_generic(parsed.blocks, max_tokens, overlap_ratio, count)
    return build_chunks(pieces, meta, count)


def mark_amended(chunks: list[Chunk], amended_articles: list[str]) -> None:
    """Đánh dấu chunk thuộc Điều đã bị sửa đổi. `amended_articles` ghi theo số Điều của bản tiếng Việt
    ("Điều 60 khoản 2"), dùng chung cho bản dịch vì số Điều/Article giống nhau."""
    amended = amended_article_numbers(amended_articles)
    for chunk in chunks:
        number = re.search(r"\d+", chunk.article) if chunk.article else None
        chunk.amended = number is not None and int(number.group()) in amended


def ingest_manifest_document(
    doc: ManifestDocument, raw_dir: Path = RAW_DIR, config: RagConfig | None = None
) -> IngestResult:
    parsed = parse_pdf_files([raw_dir / file.filename for file in doc.files])
    meta = DocumentMeta(
        doc_id=doc.doc_id,
        title=doc.title,
        language=doc.language,
        so_hieu=doc.so_hieu,
        effective_date=doc.effective_date,
        status=doc.status,
        amended_by=doc.amended_by,
    )
    chunks = chunk_document(parsed, meta, config)
    mark_amended(chunks, doc.amended_articles)
    return IngestResult(parsed, chunks)


def ingest_file(
    path: Path,
    doc_id: str,
    title: str | None = None,
    ocr: OcrEngine | None = None,
    config: RagConfig | None = None,
) -> IngestResult:
    """File user upload: ngôn ngữ tự nhận ra, chưa có số hiệu và ngày hiệu lực."""
    parsed = parse_file(path, ocr)
    language = detect_language("\n".join(block.text for block in parsed.blocks[:500]))
    meta = DocumentMeta(doc_id=doc_id, title=title or path.stem, language=language)
    return IngestResult(parsed, chunk_document(parsed, meta, config))
