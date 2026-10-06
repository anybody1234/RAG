from app.ingestion.chunking import Piece, build_chunks
from app.ingestion.generic_chunker import chunk_generic
from app.ingestion.models import Block, DocumentMeta


def words(text: str) -> int:
    return len(text.split())


def paragraph(n: int) -> str:
    return f"Đoạn {n} " + "nội dung " * 8 + "hết."


def test_chunks_follow_headings_and_repeat_nearest_heading():
    lines = ["# Hướng dẫn", "Giới thiệu ngắn.", "## Cài đặt", paragraph(1), paragraph(2), paragraph(3),
             "## Sử dụng", "Chạy lệnh."]
    pieces = chunk_generic([Block(line, 1) for line in lines], max_tokens=50, overlap_ratio=0.5, count=words)
    paths = [" > ".join(p.path) for p in pieces]
    assert paths == ["Hướng dẫn", "Hướng dẫn > Cài đặt", "Hướng dẫn > Cài đặt", "Hướng dẫn > Sử dụng"]
    assert pieces[1].text().startswith("Cài đặt\nĐoạn 1")
    assert all(words(p.text()) <= 50 for p in pieces)
    # Chunk sau lặp lại đoạn cuối của chunk trước (overlap).
    assert pieces[1].blocks[-1] == pieces[2].blocks[0]


def test_text_without_headings_is_packed_by_length():
    pieces = chunk_generic([Block(paragraph(n), None) for n in range(10)], 40, 0.0, words)
    assert len(pieces) == 5
    assert all(p.path == [] and p.prefix == "" for p in pieces)


def test_build_chunks_sets_ids_pages_and_hash():
    meta = DocumentMeta(doc_id="doc", title="Tài liệu", language="vi")
    piece = Piece([Block("a b", 2), Block("c", 3, 4)], ["Chương I", "Điều 1"], prefix="Điều 1. X", article="Điều 1")
    [chunk] = build_chunks([piece], meta, words)
    assert chunk.chunk_id == "doc:0000"
    assert chunk.text == "Điều 1. X\na b\nc"
    assert chunk.heading_path == "Chương I > Điều 1"
    assert (chunk.page, chunk.page_end, chunk.token_count) == (2, 4, 6)
    assert len(chunk.content_hash) == 64
