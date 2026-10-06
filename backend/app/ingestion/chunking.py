"""Hàm dùng chung cho các chunker: nối dòng thành đoạn, tách đoạn quá dài, gom đoạn thành chunk."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.ingestion.models import Block, Chunk, DocumentMeta

# Hàm đếm token (`tokens.TokenCounter`); test dùng bộ đếm từ cho dễ tính.
CountTokens = Callable[[str], int]

# Dòng kết thúc câu: dấu câu, có thể theo sau là dấu đóng ngoặc/nháy.
END_PUNCT = re.compile(r"[.;:!?…][”\"’)\]]*$")
# Dòng luôn mở đầu đoạn mới: heading markdown, hàng bảng, gạch đầu dòng, mục đánh số "1." "a)" "(a)" "(1)".
_BLOCK_START = re.compile(r"^(#{1,6}\s|\||[-•*+]\s|[“\"]?\(?(\d+|[a-zđ])[.)]\s)")
_SENTENCE_END = re.compile(r"(?<=[.;:!?…])\s+")
# Dòng ngắn hơn tỉ lệ này so với dòng dài (phân vị 90) thì coi là dòng cuối đoạn.
_WIDE_LINE_RATIO = 0.7


def starts_block(text: str) -> bool:
    return bool(_BLOCK_START.match(text))


def _continues(prev: str, line: str, wide: float, is_start: Callable[[str], bool],
               is_heading: Callable[[str], bool]) -> bool:
    if is_start(line) or prev.startswith(("#", "|")):
        return False
    if line[0].islower():
        return True
    if is_heading(prev):
        return False
    return len(prev) >= wide and not END_PUNCT.search(prev)


def _merge(lines: list[Block]) -> Block:
    return Block(" ".join(line.text for line in lines), lines[0].page, lines[-1].last_page)


def reflow(
    lines: list[Block],
    is_start: Callable[[str], bool] = starts_block,
    is_heading: Callable[[str], bool] = lambda _: False,
) -> list[Block]:
    """Nối các dòng bị ngắt do dàn trang thành đoạn.

    Dòng sau được nối vào dòng trước khi nó bắt đầu bằng chữ thường, hoặc khi dòng trước dài gần bằng khổ
    dòng mà không kết thúc câu. Không bao giờ nối khi dòng sau mở đầu một mục (`is_start`), và chỉ nối vào
    tiêu đề (`is_heading`) khi dòng sau là phần tiếp của tiêu đề (bắt đầu bằng chữ thường).
    """
    if not lines:
        return []
    lengths = sorted(len(line.text) for line in lines)
    wide = _WIDE_LINE_RATIO * lengths[int(0.9 * (len(lengths) - 1))]
    paragraphs: list[Block] = []
    current = [lines[0]]
    for line in lines[1:]:
        if _continues(current[-1].text, line.text, wide, is_start, is_heading):
            current.append(line)
        else:
            paragraphs.append(_merge(current))
            current = [line]
    paragraphs.append(_merge(current))
    return paragraphs


def size_of(blocks: list[Block], count: CountTokens) -> int:
    """Số token (cận trên) khi nối các đoạn bằng "\\n"."""
    return sum(count(block.text) + 1 for block in blocks) - 1 if blocks else 0


def _split_words(sentence: str, budget: int, count: CountTokens) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for word in sentence.split(" "):
        word_size = count(word) + 1
        if current and size + word_size > budget:
            pieces.append(" ".join(current))
            current, size = [], 0
        current.append(word)
        size += word_size
    return pieces + [" ".join(current)] if current else pieces


def _split_text(text: str, budget: int, count: CountTokens) -> list[str]:
    sentences: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentences += [sentence] if count(sentence) <= budget else _split_words(sentence, budget, count)
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in sentences:
        sentence_size = count(sentence) + 1
        if current and size + sentence_size > budget + 1:
            pieces.append(" ".join(current))
            current, size = [], 0
        current.append(sentence)
        size += sentence_size
    return pieces + [" ".join(current)] if current else pieces


def split_long_blocks(blocks: list[Block], budget: int, count: CountTokens) -> list[Block]:
    """Tách đoạn dài hơn `budget` token theo câu (câu quá dài thì theo từ)."""
    result: list[Block] = []
    for block in blocks:
        if count(block.text) <= budget:
            result.append(block)
        else:
            result += [Block(text, block.page, block.page_end) for text in _split_text(block.text, budget, count)]
    return result


def pack_blocks(blocks: list[Block], budget: int, overlap: int, count: CountTokens) -> list[list[Block]]:
    """Gom các đoạn liền nhau thành nhóm ≤ `budget` token.

    Nhóm mới lặp lại các đoạn cuối của nhóm trước, tổng không quá `overlap` token. Mọi đoạn phải ≤ `budget`
    (gọi `split_long_blocks` trước).
    """
    groups: list[list[Block]] = []
    current: list[Block] = []
    size = 0
    for block in blocks:
        block_size = count(block.text) + 1
        if current and size + block_size > budget + 1:
            groups.append(current)
            carry: list[Block] = []
            carried = 0
            for previous in reversed(current[1:]):
                previous_size = count(previous.text) + 1
                if carried + previous_size > overlap or carried + previous_size + block_size > budget + 1:
                    break
                carry.insert(0, previous)
                carried += previous_size
            current, size = carry, carried
        current.append(block)
        size += block_size
    if current:
        groups.append(current)
    return groups


@dataclass
class Piece:
    """Một chunk trước khi gắn metadata: các đoạn nội dung, đường dẫn heading và dòng tiêu đề lặp lại."""

    blocks: list[Block]
    path: list[str]
    # Tiêu đề đặt ở đầu chunk (tiêu đề Điều, heading gần nhất), không tính vào trang của chunk.
    prefix: str = ""
    article: str | None = None

    def text(self) -> str:
        return "\n".join(([self.prefix] if self.prefix else []) + [block.text for block in self.blocks])


def build_chunks(pieces: list[Piece], meta: DocumentMeta, count: CountTokens) -> list[Chunk]:
    chunks = []
    for index, piece in enumerate(pieces):
        text = piece.text()
        pages = [block.page for block in piece.blocks if block.page is not None]
        last_pages = [block.last_page for block in piece.blocks if block.last_page is not None]
        chunks.append(Chunk(
            **meta.model_dump(),
            chunk_id=f"{meta.doc_id}:{index:04d}",
            chunk_index=index,
            text=text,
            heading_path=" > ".join(piece.path),
            article=piece.article,
            page=min(pages) if pages else None,
            page_end=max(last_pages) if last_pages else None,
            token_count=count(text),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ))
    return chunks
