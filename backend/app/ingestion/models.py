"""Kiểu dữ liệu dùng chung của bước ingestion: dòng text đã parse, tài liệu đã parse, chunk."""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel

FileFormat = Literal["pdf", "docx", "html", "md", "txt"]
Structure = Literal["legal", "generic"]


@dataclass(frozen=True, slots=True)
class Block:
    """Một dòng (sau khi parse) hoặc một đoạn (sau khi nối dòng), kèm trang bắt đầu và trang kết thúc.

    `page` là số trang PDF bắt đầu từ 1, đánh liên tục qua các file của cùng văn bản. Định dạng không có
    trang (DOCX, HTML, MD, TXT) thì là None.
    """

    text: str
    page: int | None
    page_end: int | None = None

    @property
    def last_page(self) -> int | None:
        return self.page_end if self.page_end is not None else self.page


@dataclass
class ParsedDocument:
    format: FileFormat
    # "legal": văn bản luật, chunk theo Điều/Article; "generic": chunk theo heading và độ dài.
    structure: Structure
    # Với structure "legal": từng dòng text thô. Với "generic": từng đoạn markdown (heading có dấu #).
    blocks: list[Block]
    page_count: int | None = None
    # Trang có quá ít text (thường là trang scan), cần OCR mới đọc được.
    needs_ocr_pages: list[int] = field(default_factory=list)


class DocumentMeta(BaseModel):
    """Metadata cấp văn bản, được chép vào mọi chunk để lọc và trích dẫn."""

    doc_id: str
    title: str
    language: Literal["vi", "en"]
    so_hieu: str | None = None
    effective_date: date | None = None
    status: str = "unknown"
    # Số hiệu các văn bản đã sửa đổi văn bản này (từ manifest). Nội dung chunk là bản gốc, chưa phản ánh sửa đổi.
    amended_by: list[str] = []


class Chunk(DocumentMeta):
    chunk_id: str
    chunk_index: int
    # Text đưa vào embedding và LLM. Chunk tách từ một Điều dài vẫn có tiêu đề Điều ở dòng đầu.
    text: str
    # Ví dụ "Chương III > Mục 1 > Điều 35 > Khoản 2"
    heading_path: str
    # "Điều 35" / "Article 35"; None với phần mở đầu hoặc tài liệu không phải văn bản luật.
    article: str | None = None
    page: int | None
    page_end: int | None
    token_count: int
    # sha256 của text, dùng cho upsert idempotent vào Qdrant.
    content_hash: str
    # Điều chứa chunk đã bị sửa đổi (có trong `amended_articles` của manifest, tính theo cả Điều): text là
    # bản gốc, có thể đã lỗi thời. Văn bản bị sửa bởi những luật nào nằm ở `amended_by`.
    amended: bool = False
