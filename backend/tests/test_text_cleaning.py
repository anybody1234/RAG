import unicodedata

from app.ingestion.text_cleaning import (
    clean_vietnamese_text,
    dehyphenate_lines,
    expand_ligatures,
    fix_replacement_chars,
    strip_markdown_inline,
)


def test_normalizes_decomposed_vietnamese_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Điều 35. Quyền đơn phương chấm dứt")
    assert clean_vietnamese_text(decomposed) == "Điều 35. Quyền đơn phương chấm dứt"


def test_keeps_line_breaks_needed_for_article_detection():
    text = "Chương III\r\n\n\nĐiều 35.   Quyền   đơn phương\t\n  1. Người lao động"
    assert clean_vietnamese_text(text) == "Chương III\nĐiều 35. Quyền đơn phương\n1. Người lao động"


def test_removes_control_and_invisible_format_characters():
    assert clean_vietnamese_text("Xin\x00 chào\u200b!") == "Xin chào!"


def test_expands_pdf_ligatures_only():
    assert expand_ligatures("speciﬁc oﬃcial ½") == "specific official ½"


def test_fixes_replacement_characters():
    assert fix_replacement_chars("Independence \ufffd Freedom") == "Independence – Freedom"
    assert fix_replacement_chars("the individual\ufffds consent\ufffd") == "the individual’s consent"


def test_dehyphenates_words_broken_at_line_end():
    # Văn bản dàn trang có ngắt từ (nhiều dòng kết thúc bằng gạch nối), "particular" có ở chỗ khác.
    lines = ["in par-", "ticular the data", "a particular case", "a fixed-", "term contract", "fixed-term work"]
    assert dehyphenate_lines(lines) == [
        "in particular", "the data", "a particular case", "a fixed-term", "contract", "fixed-term work",
    ]


def test_keeps_hyphen_without_evidence_in_rarely_hyphenated_text():
    lines = ["a state-", "invested enterprise"] + ["plain line"] * 200
    assert dehyphenate_lines(lines)[:2] == ["a state-invested", "enterprise"]


def test_strips_inline_markdown_but_keeps_headings_and_tables():
    markdown = "# **<mark>Điều 40. Nghĩa vụ</mark>**\n1. _Người lao động_ là người\nCommittee<sup>1</sup> ,\n| a | b |"
    assert strip_markdown_inline(markdown) == "# Điều 40. Nghĩa vụ\n1. Người lao động là người\nCommittee ,\n| a | b |"
