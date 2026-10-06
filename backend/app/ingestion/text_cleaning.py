import re
import unicodedata
from collections import Counter

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


_LIGATURES = re.compile("[ﬀ-ﬆ]")


def expand_ligatures(text: str) -> str:
    """Tách chữ ghép của PDF ("speciﬁc" thành "specific") bằng NFKC, chỉ áp cho các ký tự chữ ghép.

    Không NFKC cả văn bản vì NFKC còn đổi các ký tự khác (ví dụ "½", chỉ số trên) mà ta muốn giữ.
    """
    return _LIGATURES.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)


def fix_replacement_chars(text: str) -> str:
    """Sửa ký tự lỗi mã hoá `�` (U+FFFD) trong bản dịch.

    Giữa hai khoảng trắng, `�` thường là dấu gạch ngang bị mất ("Independence � Freedom"); dính vào chữ thì
    thường là dấu nháy ("individual�s"). Trường hợp còn lại không đoán được nên bỏ đi.
    """
    text = re.sub(r"(?<=\s)�(?=\s)", "–", text)
    text = re.sub(r"(?<=\w)�(?=\w)", "’", text)
    return text.replace("�", "")


# Tỉ lệ dòng kết thúc bằng gạch nối mà trên ngưỡng này thì coi văn bản được dàn trang có ngắt từ tự động
# (GDPR khoảng 4%, bản dịch luật Việt Nam dưới 0.2%).
_HYPHENATED_DOC_RATIO = 0.01
_LINE_END_HYPHEN = re.compile(r"([^\W\d_]+)-$")
_LINE_START_WORD = re.compile(r"^([^\W\d_]+)(.*)$", re.DOTALL)


def dehyphenate_lines(lines: list[str]) -> list[str]:
    """Nối từ bị ngắt ở cuối dòng: "par-" + "ticular" thành "particular".

    Từ ghép có gạch nối thật ("fixed-" + "term") thì giữ gạch nối. Căn cứ để quyết định là chính văn bản:
    dạng nào ("particular" hay "fixed-term") xuất hiện nhiều hơn ở chỗ khác thì chọn dạng đó. Khi không có
    căn cứ, văn bản dàn trang có ngắt từ tự động thì nối liền, văn bản khác thì giữ gạch nối.
    """
    candidates = [
        i for i in range(len(lines) - 1)
        if _LINE_END_HYPHEN.search(lines[i]) and lines[i + 1][:1].islower()
    ]
    if not candidates:
        return lines
    vocabulary = Counter(re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)*", "\n".join(lines).lower()))
    join_by_default = len(candidates) / len(lines) > _HYPHENATED_DOC_RATIO

    result = list(lines)
    for i in candidates:
        head = _LINE_END_HYPHEN.search(result[i])
        tail = _LINE_START_WORD.match(result[i + 1])
        if head is None or tail is None or not tail.group(1)[0].islower():  # dòng đã bị sửa ở bước trước
            continue
        left, right = head.group(1), tail.group(1)
        joined, hyphenated = (left + right).lower(), f"{left}-{right}".lower()
        keep_hyphen = (
            vocabulary[hyphenated] > vocabulary[joined]
            or (vocabulary[hyphenated] == vocabulary[joined] and not join_by_default)
        )
        result[i] = result[i][: head.end(1)] + ("-" if keep_hyphen else "") + right
        result[i + 1] = tail.group(2).lstrip()
    return result


_MARKDOWN_INLINE = [
    (re.compile(r"<sup>.*?</sup>"), ""),  # số chú thích
    (re.compile(r"</?(?:mark|sub|u|b|i|em|strong|span)[^>]*>"), ""),
    (re.compile(r"\*\*|__"), ""),
    (re.compile(r"(?<![\w*])[_*]([^_*\n]+?)[_*](?![\w*])"), r"\1"),
    (re.compile(r"^>\s?", re.MULTILINE), ""),
    (re.compile(r"^\*\*==>.*<==\*\*$", re.MULTILINE), ""),  # chỗ ảnh bị bỏ của pymupdf4llm
]


def strip_markdown_inline(text: str) -> str:
    """Bỏ định dạng inline (đậm, nghiêng, highlight, chỉ số trên) của markdown do pymupdf4llm sinh ra.

    Giữ heading `#` và bảng `|` vì chunker chung dùng chúng. Text chunk không còn `**`, `_` thì đoạn trích
    trong golden set (lấy từ text thô) mới so khớp được.
    """
    for pattern, replacement in _MARKDOWN_INLINE:
        text = pattern.sub(replacement, text)
    return text
