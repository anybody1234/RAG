import unicodedata

from app.ingestion.text_cleaning import clean_vietnamese_text


def test_normalizes_decomposed_vietnamese_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Điều 35. Quyền đơn phương chấm dứt")
    assert clean_vietnamese_text(decomposed) == "Điều 35. Quyền đơn phương chấm dứt"


def test_keeps_line_breaks_needed_for_article_detection():
    text = "Chương III\r\n\n\nĐiều 35.   Quyền   đơn phương\t\n  1. Người lao động"
    assert clean_vietnamese_text(text) == "Chương III\nĐiều 35. Quyền đơn phương\n1. Người lao động"


def test_removes_control_and_invisible_format_characters():
    assert clean_vietnamese_text("Xin\x00 chào\u200b!") == "Xin chào!"
