from app.ingestion.models import Chunk
from app.ingestion.pipeline import mark_amended


def make_chunk(article: str | None) -> Chunk:
    return Chunk(
        doc_id="d", title="t", language="vi", chunk_id=f"d:{article}", chunk_index=0, text="x",
        heading_path=article or "Phần mở đầu", article=article, page=1, page_end=1, token_count=1, content_hash="h",
    )


def test_mark_amended_flags_whole_article_in_both_languages():
    chunks = [make_chunk(a) for a in ("Điều 60", "Điều 61", "Article 60", "Article 154", None, "Điều 6")]
    mark_amended(chunks, ["Điều 60 khoản 2", "Điều 154 (bổ sung khoản 8a)"])
    assert [c.amended for c in chunks] == [True, False, True, True, False, False]


def test_mark_amended_without_amendments():
    chunks = [make_chunk("Điều 1")]
    mark_amended(chunks, [])
    assert chunks[0].amended is False
