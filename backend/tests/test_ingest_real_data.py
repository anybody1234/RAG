"""Ingestion trên bộ dữ liệu thật trong data/raw. Bỏ qua khi chưa chạy `python scripts/download_data.py`
(CI không tải dữ liệu)."""

import re

import pytest

from app.core.config import REPO_ROOT
from app.core.rag_config import get_rag_config
from app.evaluation.golden import load_golden, normalize_for_match
from app.ingestion.manifest import RAW_DIR, amended_article_numbers, load_manifest
from app.ingestion.pipeline import IngestResult, ingest_manifest_document

MANIFEST = load_manifest()
GOLDEN_PATH = REPO_ROOT / "eval" / "datasets" / "golden_v1.jsonl"
# Số Điều/Article đếm theo văn bản gốc (data/SOURCES.md).
EXPECTED_ARTICLES = {
    "vi-bo-luat-lao-dong-2019": 220,
    "en-labour-code-2019": 220,
    "vi-luat-doanh-nghiep-2020": 218,
    "en-law-on-enterprises-2020": 218,
    "vi-luat-sua-doi-luat-doanh-nghiep-2025": 3,
    "en-law-amending-enterprises-2025": 3,
    "vi-luat-bao-ve-du-lieu-ca-nhan-2025": 39,
    "en-personal-data-protection-law-2025": 39,
    "en-gdpr-2016": 99,
    "vi-nghi-dinh-bao-ve-du-lieu-ca-nhan-2025": 42,
}

pytestmark = pytest.mark.skipif(
    not all((RAW_DIR / file.filename).exists() for doc in MANIFEST.documents for file in doc.files),
    reason="chưa tải dữ liệu: python scripts/download_data.py",
)


@pytest.fixture(scope="module")
def results() -> dict[str, IngestResult]:
    return {doc.doc_id: ingest_manifest_document(doc) for doc in MANIFEST.documents}


def test_expected_counts_cover_the_manifest():
    assert set(EXPECTED_ARTICLES) == {doc.doc_id for doc in MANIFEST.documents}


@pytest.mark.parametrize(("doc_id", "expected"), EXPECTED_ARTICLES.items())
def test_finds_every_article_in_order(results, doc_id, expected):
    articles = list(dict.fromkeys(chunk.article for chunk in results[doc_id].chunks if chunk.article))
    word = "Điều" if MANIFEST.get(doc_id).language == "vi" else "Article"
    assert articles == [f"{word} {n}" for n in range(1, expected + 1)]


def test_no_chunk_exceeds_max_tokens(results):
    max_tokens = get_rag_config().chunking.max_tokens
    too_long = [(c.chunk_id, c.token_count) for r in results.values() for c in r.chunks if c.token_count > max_tokens]
    assert too_long == []


def test_no_page_furniture_or_broken_characters(results):
    junk = re.compile(
        r"CÔNG BÁO/Số|Ký bởi:|Ngày ký:|Translated Version by|Tiếp theo Công báo|Xem tiếp Công báo|�|[ﬀ-ﬆ]"
    )
    assert [c.chunk_id for r in results.values() for c in r.chunks if junk.search(c.text)] == []


def test_no_leftover_signature_lines(results):
    # Từng sót (sửa 07/10/2026): Luật Doanh nghiệp 2020 có tên người ký bị ngắt sang dòng "phủ"; Luật BVDLCN 2025
    # và luật 76/2025 mở khối chữ ký bằng "Người ký:" thay cho "Ký bởi:".
    leftover = re.compile(r"Người ký:|Thời gian ký:|Email: thongtinchinhphu|Cơ quan: Văn phòng Chính phủ", re.IGNORECASE)
    assert [c.chunk_id for r in results.values() for c in r.chunks if leftover.search(c.text)] == []


def test_decree_appendix_forms_are_not_part_of_the_last_article(results):
    """Phụ lục 13 mẫu biểu của Nghị định 356/2025 (trang 38–70) nằm ngoài Điều 42."""
    chunks = results["vi-nghi-dinh-bao-ve-du-lieu-ca-nhan-2025"].chunks
    article_42 = [c for c in chunks if c.article == "Điều 42"]
    assert len(article_42) == 1 and article_42[0].page_end == 37
    appendix = [c for c in chunks if c.heading_path.startswith("Phụ lục")]
    assert all(c.article is None and c.page >= 38 for c in appendix)
    forms = list(dict.fromkeys(c.heading_path.removeprefix("Phụ lục > ") for c in appendix[1:]))
    expected = ["01a", "01b", "02a", "02b", "03a", "03b", "04", "05", "06", "07", "08", "09", "10"]
    assert [form.split()[-1] for form in forms] == expected


def test_gdpr_words_broken_at_line_end_are_rejoined(results):
    text = "\n".join(chunk.text for chunk in results["en-gdpr-2016"].chunks)
    assert "par- ticular" not in text and "per- sonal" not in text
    assert text.count("personal data") > 500


def test_pages_ids_and_structure(results):
    for result in results.values():
        assert result.parsed.structure == "legal" and result.parsed.needs_ocr_pages == []
        ids = [chunk.chunk_id for chunk in result.chunks]
        assert len(ids) == len(set(ids))
        assert all(1 <= c.page <= c.page_end <= result.parsed.page_count for c in result.chunks)


def test_amended_flag_matches_manifest(results):
    """Mọi Điều trong `amended_articles` đều có chunk được đánh dấu, và chỉ những Điều đó."""
    for doc in MANIFEST.documents:
        flagged = {int(c.article.split()[-1]) for c in results[doc.doc_id].chunks if c.amended}
        assert flagged == amended_article_numbers(doc.amended_articles), doc.doc_id
    flagged_ldn = {c.article for c in results["en-law-on-enterprises-2020"].chunks if c.amended}
    assert len(flagged_ldn) == 33 and "Article 207" in flagged_ldn


def test_every_gold_quote_lies_in_one_chunk_on_its_page(results):
    """Nếu đoạn trích bị cắt ngang ranh giới chunk thì retrieval eval không thể tính trúng dù tìm đúng chỗ."""
    normalized = {
        doc_id: [(normalize_for_match(c.text), c.page, c.page_end) for c in result.chunks]
        for doc_id, result in results.items()
    }
    misses = []
    for item in load_golden(GOLDEN_PATH):
        for source in item.gold_sources:
            quote = normalize_for_match(source.quote)
            if not any(quote in text and first <= source.page <= last for text, first, last in normalized[source.doc_id]):
                misses.append((item.id, source.doc_id, source.page))
    assert misses == []
