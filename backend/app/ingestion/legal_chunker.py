"""Chunk văn bản luật theo cấu trúc Phần/Chương/Mục/Điều/Khoản/Điểm (tiếng Việt) và
Part/Chapter/Section/Article/Clause/Point (tiếng Anh).

Đơn vị chính là Điều. Điều dài hơn `max_tokens` thì gom các Khoản liền nhau thành chunk; Khoản vẫn quá dài
thì tách theo Điểm, cuối cùng mới tách theo đoạn/câu. Mọi chunk tách từ một Điều đều có dòng tiêu đề Điều ở
đầu (Khoản bị tách theo Điểm thì có thêm câu dẫn của Khoản).

Một dòng chỉ được nhận là tiêu đề khi đúng định dạng và đúng thứ tự đánh số, để không nhầm với dẫn chiếu bị
ngắt dòng ("Điều 209 của Bộ luật này", "Article 42 may be used") hay nội dung luật được sửa đổi nằm trong
ngoặc kép (“Điều 12. ...” trong luật sửa đổi).

Phụ lục sau Điều cuối (mẫu biểu kèm nghị định) không thuộc Điều nào: mỗi Phụ lục, mỗi mẫu biểu là một mục
riêng, chunk theo độ dài, `article` là None.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.chunking import (
    END_PUNCT,
    CountTokens,
    Piece,
    pack_blocks,
    reflow,
    size_of,
    split_long_blocks,
    starts_block,
)
from app.ingestion.models import Block

# Ít nhất chừng này Điều/Article thì coi tài liệu là văn bản luật.
MIN_ARTICLES = 3
# Số Điều liền sau được phép lớn hơn số Điều trước tối đa chừng này (bỏ sót một tiêu đề vẫn chạy tiếp được).
MAX_ARTICLE_GAP = 3

_WORDS = {
    "vi": {"clause": "Khoản", "point": "Điểm", "preamble": "Phần mở đầu"},
    "en": {"clause": "Clause", "point": "Point", "preamble": "Preamble"},
}
_DIVISIONS = {  # tên đã chuẩn hoá, cấp (0 lớn nhất)
    "phần": ("Phần", 0), "part": ("Part", 0),
    "chương": ("Chương", 1), "chapter": ("Chapter", 1),
    "mục": ("Mục", 2), "section": ("Section", 2),
}
_POINT_LETTERS = "abcdđefghijklmnopqrstuvwxyz"
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

# DOCX/HTML/MD có thể đặt tiêu đề trong heading markdown: "## Điều 1. Phạm vi điều chỉnh".
_MARKUP = re.compile(r"^#{1,6}\s+")
_DIVISION = re.compile(
    r"^(?P<kind>(?i:phần|chương|mục|part|chapter|section))\s+(?P<num>thứ\s+\w+|[IVXLC]+|\d+)(?![\w/])\.?\s*(?P<rest>.*)$"
)
_ARTICLE_VI = re.compile(r"^Điều\s+(\d+)([a-zđ]?)\.(?:\s*(.*))?$")
_ARTICLE_EN = re.compile(r"^(?:Article|ARTICLE)\s+(\d+)([a-z]?)(?:\.?\s+[A-Z“\"‘].*|\.?)$")
_CLAUSE = re.compile(r"^(\d+)\.\s+\S")
_POINT = re.compile(r"^\(?([a-zđ])\)\s+\S")
# Tiêu đề Phụ lục và mẫu biểu đứng riêng một dòng: "Phụ lục", "PHỤ LỤC II", "Mẫu số 01a", "Mẫu 09".
_APPENDIX = re.compile(r"^(?P<kind>Phụ lục|PHỤ LỤC|Appendix|APPENDIX|Annex|ANNEX)(?:\s+(?P<num>[IVXLC]+|\d+[a-z]?))?\.?$")
_APPENDIX_WORDS = {"phụ lục": "Phụ lục", "appendix": "Appendix", "annex": "Annex"}
_FORM = re.compile(r"^(?:Mẫu(?: số)?|Form(?: No\.)?)\s+\d+[a-z]?$")


def _roman_or_int(numeral: str) -> int | None:
    if numeral.isdigit():
        return int(numeral)
    if not set(numeral) <= _ROMAN.keys():
        return None  # "thứ nhất"
    values = [_ROMAN[char] for char in numeral]
    return sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))


def _division(text: str) -> re.Match | None:
    match = _DIVISION.match(text)
    if match is None:
        return None
    rest = match["rest"]
    # Tiêu đề có thể kèm tên ("CHAPTER I General provisions", "Mục 1. TUYỂN DỤNG"); dẫn chiếu thì không
    # ("Chương XI của Bộ luật này.", "Section 2 of this Law").
    if rest and rest.upper() != rest and (not rest[0].isupper() or len(rest) > 120 or END_PUNCT.search(rest)):
        return None
    return match


def _article(text: str) -> tuple[str, int, str] | None:
    if match := _ARTICLE_VI.match(text):
        return "Điều", int(match[1]), match[2]
    if match := _ARTICLE_EN.match(text):
        return "Article", int(match[1]), match[2]
    return None


def _appendix_label(text: str) -> str | None:
    if match := _APPENDIX.match(text):
        return " ".join(filter(None, [_APPENDIX_WORDS[match["kind"].lower()], match["num"]]))
    return None


def _is_heading(text: str) -> bool:
    text = _MARKUP.sub("", text)
    return any([_article(text), _division(text), _APPENDIX.match(text), _FORM.match(text)])


def _is_start(text: str) -> bool:
    return starts_block(text) or _is_heading(text)


def _is_division_title(text: str, first_after_bare_heading: bool) -> bool:
    if any(char.isalpha() for char in text) and text.upper() == text:
        return True  # "NHỮNG QUY ĐỊNH CHUNG"
    return first_after_bare_heading and len(text) <= 120 and not END_PUNCT.search(text)


@dataclass
class Article:
    label: str  # "Điều 35" / "Article 35"
    path: list[str]  # ["Chương III", "Mục 1"]
    blocks: list[Block] = field(default_factory=list)  # blocks[0] là tiêu đề Điều
    quoted: list[bool] = field(default_factory=list)  # đoạn nằm trong ngoặc kép (nội dung được sửa đổi)


@dataclass
class Appendix:
    path: list[str]  # ["Phụ lục"], ["Phụ lục", "Mẫu số 01a"]
    blocks: list[Block]  # blocks[0] là dòng tiêu đề


@dataclass
class LegalStructure:
    preamble: list[Block]
    articles: list[Article]
    appendices: list[Appendix] = field(default_factory=list)


def _article_chain(candidates: list[tuple[int, tuple[str, int, str]]]) -> dict[int, str]:
    """Chọn dãy tiêu đề Điều dài nhất có số tăng dần, mỗi bước tăng không quá MAX_ARTICLE_GAP.

    `candidates` là (vị trí đoạn, (chữ "Điều"/"Article", số, hậu tố)); trả về {vị trí đoạn: "Điều 35"}.
    Dẫn chiếu trông giống tiêu đề ("Article 290 TFEU should be ..." trong phần Recitals của GDPR) không nối
    được vào dãy chính nên bị loại.
    """
    keys = [(number, suffix) for _, (_, number, suffix) in candidates]
    best = [1] * len(candidates)
    previous = [-1] * len(candidates)
    for j, key_j in enumerate(keys):
        for i, key_i in enumerate(keys[:j]):
            # >= để chọn ứng viên gần nhất khi hai dãy dài bằng nhau
            if key_i < key_j and key_j[0] - key_i[0] <= MAX_ARTICLE_GAP and best[i] + 1 >= best[j]:
                best[j], previous[j] = best[i] + 1, i
    chain: dict[int, str] = {}
    end = max(range(len(candidates)), key=best.__getitem__, default=-1)
    while end >= 0:
        index, (word, number, suffix) = candidates[end]
        chain[index] = f"{word} {number}{suffix}"
        end = previous[end]
    return chain


def parse_legal_structure(lines: list[Block]) -> LegalStructure:
    """Nối dòng thành đoạn rồi chia đoạn vào phần mở đầu và các Điều.

    Tiêu đề Phần/Chương/Mục và tên của chúng không nằm trong chunk nào; số của chúng nằm trong `path`.
    Phần kết (ngày thông qua, chữ ký) thuộc Điều cuối.
    """
    paragraphs = [
        Block(_MARKUP.sub("", paragraph.text), paragraph.page, paragraph.page_end)
        for paragraph in reflow(lines, _is_start, _is_heading)
    ]
    # Nội dung sửa đổi trong ngoặc kép (“Điều 12. ...) không phải tiêu đề.
    chain = _article_chain([
        (index, article)
        for index, paragraph in enumerate(paragraphs)
        if not paragraph.text.startswith("“") and (article := _article(paragraph.text))
    ])

    preamble: list[Block] = []
    articles: list[Article] = []
    appendices: list[Appendix] = []
    in_appendix = False
    divisions: dict[int, tuple[str, int | None]] = {}  # cấp -> (nhãn, số)
    after_division = False
    bare_heading = False
    quote_depth = 0
    for index, block in enumerate(paragraphs):
        text = block.text
        if index in chain:
            path = [label for _, (label, _) in sorted(divisions.items())]
            articles.append(Article(chain[index], path, [block], [False]))
            # Bản dịch có thể thiếu dấu đóng ngoặc; không để lỗi đó lan sang Điều sau.
            quote_depth = max(0, text.count("“") - text.count("”"))
            after_division = in_appendix = False
            continue
        if in_appendix:
            if label := _appendix_label(text):
                appendices.append(Appendix([label], [block]))
            elif _FORM.match(text) and _starts_page(block, paragraphs[index - 1]):
                # Mẫu biểu mới bắt đầu ở đầu trang; dòng "Mẫu số 01b" trong bảng danh mục mẫu thì không.
                appendices.append(Appendix([appendices[-1].path[0], " ".join(text.split())], [block]))
            else:
                appendices[-1].blocks.append(block)
            continue
        quoted = quote_depth > 0 or text.startswith("“")
        quote_depth = max(0, quote_depth + text.count("“") - text.count("”"))
        if not quoted:
            if articles and (label := _appendix_label(text)):
                appendices.append(Appendix([label], [block]))
                in_appendix = True
                continue
            if (division := _division(text)) and _accept_division(division, divisions):
                after_division, bare_heading = True, not division["rest"]
                continue
            if after_division and _is_division_title(text, bare_heading):
                bare_heading = False
                continue
        after_division = False
        if articles:
            articles[-1].blocks.append(block)
            articles[-1].quoted.append(quoted)
        else:
            preamble.append(block)
    return LegalStructure(preamble, articles, appendices)


def _starts_page(block: Block, previous: Block) -> bool:
    """Đoạn đầu tiên của trang. Định dạng không có trang (DOCX, HTML) thì luôn đúng."""
    return block.page is None or previous.last_page != block.page


def _accept_division(match: re.Match, divisions: dict[int, tuple[str, int | None]]) -> bool:
    name, rank = _DIVISIONS[match["kind"].lower()]
    number = _roman_or_int(match["num"])
    current = divisions.get(rank)
    if current is not None and number is not None and current[1] is not None:
        if number == current[1]:
            return True  # tiêu đề lặp lại ở đầu file sau (Luật Doanh nghiệp phần 2 mở đầu bằng "Chương V")
        if not current[1] < number <= current[1] + 2:
            return False
    divisions[rank] = (f"{name} {' '.join(match['num'].split())}", number)
    for deeper in [r for r in divisions if r > rank]:
        del divisions[deeper]
    return True


def looks_like_legal(lines: list[Block]) -> bool:
    return len(parse_legal_structure(lines).articles) >= MIN_ARTICLES


Unit = tuple[str | None, list[tuple[Block, bool]]]  # (số Khoản/chữ Điểm, các đoạn kèm cờ quoted)


def _next_in_sequence(value: str, last: str | None, level: int) -> bool:
    if level == 0:
        return int(value) == (int(last) if last else 0) + 1
    if last is None:
        return value == "a"
    return _POINT_LETTERS.index(last) < _POINT_LETTERS.index(value) <= _POINT_LETTERS.index(last) + 2


def _units(items: list[tuple[Block, bool]], level: int) -> list[Unit]:
    marker = _CLAUSE if level == 0 else _POINT
    units: list[Unit] = []
    last: str | None = None
    for block, quoted in items:
        match = None if quoted else marker.match(block.text)
        if match and _next_in_sequence(match[1], last, level):
            units.append((match[1], [(block, quoted)]))
            last = match[1]
        elif units:
            units[-1][1].append((block, quoted))
        else:
            units.append((None, [(block, quoted)]))
    return units


@dataclass
class _ArticleSplitter:
    article: str
    words: dict[str, str]
    max_tokens: int
    overlap: int
    count: CountTokens

    def split(self, items: list[tuple[Block, bool]], prefix: str, path: list[str], level: int) -> list[Piece]:
        if level < 2:
            units = _units(items, level)
            if any(label for label, _ in units):
                return self._pack_units(units, prefix, path, level)
        return self._by_length([block for block, _ in items], prefix, path)

    def _by_length(self, blocks: list[Block], prefix: str, path: list[str]) -> list[Piece]:
        budget = self.max_tokens - self.count(prefix) - 1
        groups = pack_blocks(split_long_blocks(blocks, budget, self.count), budget, self.overlap, self.count)
        return [Piece(group, path, prefix, self.article) for group in groups]

    def _pack_units(self, units: list[Unit], prefix: str, path: list[str], level: int) -> list[Piece]:
        budget = self.max_tokens - self.count(prefix) - 1
        word = self.words["clause" if level == 0 else "point"]
        pieces: list[Piece] = []
        group: list[Unit] = []
        size = 0

        def flush() -> None:
            labels = [label for label, _ in group if label]
            suffix = [f"{word} {labels[0]}" + (f"–{labels[-1]}" if len(labels) > 1 else "")] if labels else []
            blocks = [block for _, items in group for block, _ in items]
            pieces.append(Piece(blocks, path + suffix, prefix, self.article))

        for unit in units:
            unit_size = size_of([block for block, _ in unit[1]], self.count) + 1
            if group and size + unit_size > budget + 1:
                flush()
                group, size = [], 0
            if unit_size > budget + 1:
                pieces += self._split_unit(unit, prefix, path, level, budget)
                continue
            group.append(unit)
            size += unit_size
        if group:
            flush()
        return pieces

    def _split_unit(self, unit: Unit, prefix: str, path: list[str], level: int, budget: int) -> list[Piece]:
        label, items = unit
        word = self.words["clause" if level == 0 else "point"]
        unit_path = path + [f"{word} {label}"] if label else path
        lead = items[0][0].text
        if label and level == 0 and len(items) > 1 and self.count(lead) <= budget // 2:
            # Khoản quá dài: tách theo Điểm, mỗi chunk lặp lại câu dẫn của Khoản sau tiêu đề Điều.
            return self.split(items[1:], f"{prefix}\n{lead}", unit_path, level + 1)
        return self._by_length([block for block, _ in items], prefix, unit_path)


def chunk_legal(
    lines: list[Block], language: Literal["vi", "en"], max_tokens: int, overlap_ratio: float, count: CountTokens
) -> list[Piece]:
    structure = parse_legal_structure(lines)
    words = _WORDS[language]
    overlap = int(max_tokens * overlap_ratio)
    pieces: list[Piece] = []
    if structure.preamble:
        preamble = split_long_blocks(structure.preamble, max_tokens, count)
        pieces += [Piece(group, [words["preamble"]]) for group in pack_blocks(preamble, max_tokens, overlap, count)]

    for article in structure.articles:
        path = article.path + [article.label]
        if size_of(article.blocks, count) <= max_tokens:
            pieces.append(Piece(article.blocks, path, article=article.label))
            continue
        items = list(zip(article.blocks, article.quoted, strict=True))
        title = article.blocks[0].text
        splitter = _ArticleSplitter(article.label, words, max_tokens, overlap, count)
        if count(title) <= max_tokens // 4:
            pieces += splitter.split(items[1:], title, path, level=0)
        else:
            # Tiêu đề bị dính với nội dung (lỗi nối dòng): giữ cả đoạn trong nội dung, prefix chỉ là "Điều N".
            pieces += splitter.split(items, article.label, path, level=0)

    for appendix in structure.appendices:
        if size_of(appendix.blocks, count) <= max_tokens:
            pieces.append(Piece(appendix.blocks, appendix.path))
            continue
        # Mẫu biểu dài: chunk theo độ dài, mỗi chunk lặp lại dòng tiêu đề ("Mẫu số 09").
        title = appendix.blocks[0].text
        budget = max_tokens - count(title) - 1
        groups = pack_blocks(split_long_blocks(appendix.blocks[1:], budget, count), budget, overlap, count)
        pieces += [Piece(group, appendix.path, title) for group in groups]
    return pieces
