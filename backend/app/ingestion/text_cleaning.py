import re
import unicodedata

_KEPT_CONTROL_CHARS = {"\n", "\t"}


def clean_vietnamese_text(text: str) -> str:
    """Làm sạch văn bản trích xuất, giữ nguyên ranh giới dòng.

    Ranh giới dòng phải còn để bước chunk nhận ra đầu "Chương", "Điều N.", "1." của văn bản luật.
    """
    # Chuẩn hóa Unicode về dạng NFC (quan trọng với tiếng Việt)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Loại bỏ ký tự control và ký tự định dạng vô hình (trừ \n và \t)
    text = "".join(
        char for char in text
        if not unicodedata.category(char).startswith("C") or char in _KEPT_CONTROL_CHARS
    )

    # Gộp khoảng trắng thừa trong từng dòng, không đụng tới \n
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)

    # Xóa dòng trống dư thừa
    text = re.sub(r"\n{2,}", "\n", text)

    return text.strip()
