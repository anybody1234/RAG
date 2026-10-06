"""Nhận ngôn ngữ (vi/en) của văn bản hoặc câu hỏi bằng tỉ lệ chữ có dấu tiếng Việt, không cần model."""

from typing import Literal

Language = Literal["vi", "en"]

_VIETNAMESE_LETTERS = set(
    "ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ"
)


def detect_language(text: str) -> Language:
    """Tiếng Việt khi chữ có dấu tiếng Việt chiếm trên 5% số chữ cái (văn bản tiếng Việt thường trên 25%).

    Text phải ở dạng NFC (dấu ghép sẵn vào chữ).
    """
    letters = [char for char in text[:20_000].lower() if char.isalpha()]
    vietnamese = sum(char in _VIETNAMESE_LETTERS for char in letters)
    return "vi" if letters and vietnamese / len(letters) > 0.05 else "en"
