"""Chunk tài liệu không phải văn bản luật: chia theo heading markdown, phần dài thì gom đoạn theo độ dài.

Mỗi chunk có heading gần nhất ở dòng đầu; `heading_path` là chuỗi heading từ cấp cao nhất xuống. Chunk liền
nhau trong cùng một phần lặp lại các đoạn cuối của chunk trước (tổng ≤ overlap_ratio × max_tokens).
"""

import re

from app.ingestion.chunking import CountTokens, Piece, pack_blocks, reflow, split_long_blocks
from app.ingestion.models import Block

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


def chunk_generic(blocks: list[Block], max_tokens: int, overlap_ratio: float, count: CountTokens) -> list[Piece]:
    overlap = int(max_tokens * overlap_ratio)
    pieces: list[Piece] = []
    stack: list[tuple[int, str]] = []  # (cấp heading, tiêu đề)
    section: list[Block] = []

    def flush() -> None:
        if not section:
            return
        path = [title for _, title in stack]
        prefix = path[-1] if path and count(path[-1]) <= max_tokens // 4 else ""
        budget = max_tokens - (count(prefix) + 1 if prefix else 0)
        groups = pack_blocks(split_long_blocks(section, budget, count), budget, overlap, count)
        pieces.extend(Piece(group, path, prefix) for group in groups)
        section.clear()

    for block in reflow(blocks):
        if match := _HEADING.match(block.text):
            flush()
            level = len(match[1])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match[2].strip()))
        else:
            section.append(block)
    flush()
    return pieces
