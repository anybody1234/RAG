import unicodedata

import pytest
from pydantic import ValidationError

from app.evaluation.golden import (
    GoldenItem,
    article_at,
    is_cross_lingual,
    load_golden,
    save_golden,
    validate_golden,
)
from app.evaluation.golden_review import apply_review, parse_review, render_review
from app.ingestion.manifest import Manifest


def make_manifest() -> Manifest:
    def doc(doc_id: str, language: str, so_hieu: str = "1/2020/QH14", **extra) -> dict:
        return {
            "doc_id": doc_id, "pair_id": None, "title": doc_id, "so_hieu": so_hieu,
            "language": language, "kind": "original", "issued_date": "2020-01-01",
            "effective_date": "2020-01-01", "status": "in_force", "source": "test", "page_url": "x",
            "files": [{"filename": f"{doc_id}.pdf", "url": "x", "sha256": "x"}], **extra,
        }

    documents = [
        doc("vi-law", "vi", amended_by=["9/2025/QH15"], amended_articles=["Điều 3 khoản 1"]),
        doc("en-law", "en"),
        doc("vi-amend", "vi", so_hieu="9/2025/QH15", amends=["1/2020/QH14"]),
    ]
    return Manifest.model_validate({"version": 1, "checked_at": "2026-10-06", "documents": documents})


PAGES = {
    "vi-law": [
        "Điều 1. Phạm vi điều chỉnh",
        "Điều 2. Người lao động được nghỉ 12 ngày làm việc\nĐiều 3. Giải thể\n1. Công ty không còn đủ số lượng thành viên",
        "tối thiểu trong thời hạn 06 tháng liên tục",
    ],
    "en-law": ["Article 1. Scope", "Article 2. Employees are entitled to 12 working days"],
    "vi-amend": ["Sửa đổi điểm c khoản 1 Điều 3: không còn đủ số lượng thành viên, cổ đông tối thiểu"],
}
ARTICLE_3_QUOTE = {"doc_id": "vi-law", "page": 2, "quote": "Công ty không còn đủ số lượng thành viên"}


def item(**overrides) -> GoldenItem:
    data = {
        "id": "g001", "question": "Nghỉ phép năm bao nhiêu ngày?", "language": "vi", "type": "single_article",
        "reference_answer": "12 ngày làm việc.",
        "gold_sources": [{"doc_id": "vi-law", "page": 2, "quote": "được nghỉ 12 ngày làm việc"}],
    }
    return GoldenItem.model_validate(data | overrides)


def validate(items):
    return validate_golden(items, make_manifest(), PAGES.__getitem__, check_distribution=False)


def test_quote_matches_despite_nfd_and_line_breaks():
    quote = unicodedata.normalize("NFD", "được nghỉ\n12   ngày làm việc")
    report = validate([item(gold_sources=[{"doc_id": "vi-law", "page": 2, "quote": quote}])])
    assert report.errors == []


def test_quote_on_wrong_page_suggests_the_right_page():
    report = validate([item(gold_sources=[{"doc_id": "vi-law", "page": 1, "quote": "được nghỉ 12 ngày làm việc"}])])
    assert report.page_fixes == [("g001", 0, 2)]


def test_missing_quote_is_an_error():
    report = validate([item(gold_sources=[{"doc_id": "vi-law", "page": 2, "quote": "được nghỉ 14 ngày làm việc"}])])
    assert "không tìm thấy đoạn trích" in report.errors[0]


def test_unanswerable_question_must_not_have_sources():
    with pytest.raises(ValidationError):
        item(type="unanswerable")


def test_multi_hop_needs_two_sources():
    with pytest.raises(ValidationError):
        item(type="multi_hop")


def test_cross_lingual_when_no_source_shares_question_language():
    english_question = item(language="en", question="How many days of annual leave?")
    assert is_cross_lingual(english_question, make_manifest())
    assert not is_cross_lingual(item(), make_manifest())


def test_article_at_uses_nearest_heading_including_previous_pages():
    assert article_at(PAGES["vi-law"], 2, "được nghỉ 12 ngày làm việc") == 2
    assert article_at(PAGES["vi-law"], 2, "Công ty không còn đủ số lượng thành viên") == 3
    assert article_at(PAGES["vi-law"], 3, "06 tháng liên tục") == 3


def test_question_on_amended_article_is_an_error():
    report = validate([item(gold_sources=[ARTICLE_3_QUOTE])])
    assert any("Điều 3" in error and "đã bị sửa đổi" in error for error in report.errors)


def test_amended_article_is_allowed_when_the_amending_law_is_cited():
    amendment = {"doc_id": "vi-amend", "page": 1, "quote": "không còn đủ số lượng thành viên, cổ đông tối thiểu"}
    report = validate([item(type="multi_hop", gold_sources=[ARTICLE_3_QUOTE, amendment])])
    assert report.errors == []


def test_distribution_outside_target_is_an_error():
    report = validate_golden([item()], make_manifest(), PAGES.__getitem__)
    assert any("single_article" in error for error in report.errors)


def test_tags_are_optional_validated_and_counted(tmp_path):
    tagged = item(id="g002", tags=["explicit_ref", "no_doc_name"])
    with pytest.raises(ValidationError):
        item(tags=["slang"])
    with pytest.raises(ValidationError):
        item(tags=["colloquial", "colloquial"])
    report = validate([item(), tagged])
    assert report.tag_counts == {"explicit_ref": 1, "no_doc_name": 1}
    assert report.language_counts == {"vi": 2}

    path = tmp_path / "golden.jsonl"
    save_golden([item(), tagged], path)
    first, second = path.read_text(encoding="utf-8").splitlines()
    assert "tags" not in first and '"tags": ["explicit_ref", "no_doc_name"]' in second  # v1 không có tags
    assert load_golden(path)[1].tags == ["explicit_ref", "no_doc_name"]


def test_review_roundtrip_marks_ticked_items_and_lists_notes():
    items = [item(), item(id="g002", tags=["colloquial"]), item(id="g003")]
    text = render_review(items, make_manifest(), "v2 draft", "python eval/review_golden.py apply x.jsonl")
    assert text.startswith("# Duyệt golden set v2 draft")
    assert "## g002 · single_article · vi · colloquial\n- [ ] Đã duyệt" in text
    text = text.replace("- [ ] Đã duyệt", "- [x] Đã duyệt", 2)  # tick g001, g002; g003 để trống
    text = text.replace("Ghi chú:\n\n## g003", "Ghi chú: sai số ngày\n\n## g003")  # ghi chú của g002
    needs_fix = apply_review(items, parse_review(text))
    assert [i.reviewed for i in items] == [True, False, False]
    assert needs_fix == [("g002", "sai số ngày")]
