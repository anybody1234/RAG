"""Schema và kiểm tra bộ câu hỏi chuẩn (golden set)."""

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ingestion.manifest import Manifest

QuestionType = Literal["single_article", "numeric", "multi_hop", "paraphrase", "unanswerable", "multi_turn"]

# Khoảng tỉ lệ cho phép của từng loại câu hỏi (xem CLAUDE.md).
TARGET_DISTRIBUTION: dict[str, tuple[float, float]] = {
    "single_article": (0.30, 0.40),
    "numeric": (0.10, 0.20),
    "multi_hop": (0.10, 0.20),
    "paraphrase": (0.10, 0.20),
    "unanswerable": (0.10, 0.15),
    "multi_turn": (0.05, 0.10),
}
# Tỉ lệ tối thiểu câu hỏi khác ngôn ngữ với mọi nguồn, tính trên các câu có nguồn.
MIN_CROSS_LINGUAL_RATIO = 0.20


class GoldSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=10)


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str


class GoldenItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    language: Literal["vi", "en"]
    type: QuestionType
    reference_answer: str
    gold_sources: list[GoldSource] = []
    history: list[Turn] = []
    reviewed: bool = False

    @model_validator(mode="after")
    def check_type_rules(self) -> "GoldenItem":
        if self.type == "unanswerable" and self.gold_sources:
            raise ValueError("câu unanswerable không được có gold_sources")
        if self.type != "unanswerable" and not self.gold_sources:
            raise ValueError("câu có đáp án phải có ít nhất 1 gold_source")
        if self.type == "multi_hop" and len({(s.doc_id, s.page, s.quote) for s in self.gold_sources}) < 2:
            raise ValueError("câu multi_hop phải có ít nhất 2 gold_source khác nhau")
        if (self.type == "multi_turn") != bool(self.history):
            raise ValueError("chỉ câu multi_turn mới có history, và câu multi_turn phải có history")
        return self


def normalize_for_match(text: str) -> str:
    """Chuẩn hoá để so khớp đoạn trích với text trang PDF: NFKC, bỏ soft hyphen, gộp khoảng trắng.

    NFKC (thay vì NFC) để tách chữ ghép trong PDF tiếng Anh, ví dụ "speciﬁc" (ﬁ) thành "specific".
    """
    text = unicodedata.normalize("NFKC", text).replace("­", "")
    return re.sub(r"\s+", " ", text).strip()


def load_golden(path: Path) -> list[GoldenItem]:
    items = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(GoldenItem.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"{path.name} dòng {line_no}: {exc}") from exc
    return items


def save_golden(items: list[GoldenItem], path: Path) -> None:
    lines = [
        json.dumps(item.model_dump(exclude_defaults=True) | {"reviewed": item.reviewed}, ensure_ascii=False)
        for item in items
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_cross_lingual(item: GoldenItem, manifest: Manifest) -> bool:
    """Đúng khi câu hỏi có nguồn và không nguồn nào cùng ngôn ngữ với câu hỏi."""
    languages = {doc.language for s in item.gold_sources if (doc := manifest.get(s.doc_id))}
    return bool(languages) and item.language not in languages


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    type_counts: Counter = field(default_factory=Counter)
    cross_lingual: int = 0
    answerable: int = 0
    reviewed: int = 0
    total: int = 0
    # (id câu hỏi, chỉ số gold_source, trang đúng) khi đoạn trích nằm ở trang khác trang đã ghi
    page_fixes: list[tuple[str, int, int]] = field(default_factory=list)


def validate_golden(
    items: list[GoldenItem],
    manifest: Manifest,
    get_pages: Callable[[str], list[str]],
    check_distribution: bool = True,
) -> ValidationReport:
    """Kiểm tra golden set.

    `get_pages(doc_id)` trả về text từng trang của văn bản (phần tử 0 là trang 1).
    """
    report = ValidationReport(total=len(items))
    ids = Counter(item.id for item in items)
    report.errors += [f"id bị trùng: {item_id}" for item_id, n in ids.items() if n > 1]

    for item in items:
        report.type_counts[item.type] += 1
        report.reviewed += item.reviewed
        if item.gold_sources:
            report.answerable += 1
            report.cross_lingual += is_cross_lingual(item, manifest)
        for index, source in enumerate(item.gold_sources):
            if manifest.get(source.doc_id) is None:
                report.errors.append(f"{item.id}: doc_id không có trong manifest: {source.doc_id}")
                continue
            pages = [normalize_for_match(p) for p in get_pages(source.doc_id)]
            quote = normalize_for_match(source.quote)
            if source.page <= len(pages) and quote in pages[source.page - 1]:
                continue
            found = [n for n, text in enumerate(pages, start=1) if quote in text]
            if len(found) == 1:
                report.page_fixes.append((item.id, index, found[0]))
                report.errors.append(f"{item.id}: đoạn trích nằm ở trang {found[0]}, không phải trang {source.page}")
            elif found:
                report.errors.append(f"{item.id}: đoạn trích xuất hiện ở nhiều trang {found}, cần trích dài hơn")
            else:
                report.errors.append(f"{item.id}: không tìm thấy đoạn trích trong {source.doc_id}: {source.quote[:60]!r}")

    if check_distribution and items:
        for question_type, (low, high) in TARGET_DISTRIBUTION.items():
            ratio = report.type_counts[question_type] / len(items)
            if not low <= ratio <= high:
                report.errors.append(f"tỉ lệ loại {question_type} là {ratio:.0%}, cần trong khoảng {low:.0%}–{high:.0%}")
        if report.answerable and report.cross_lingual / report.answerable < MIN_CROSS_LINGUAL_RATIO:
            report.errors.append(
                f"câu khác ngôn ngữ với nguồn chiếm {report.cross_lingual / report.answerable:.0%}, "
                f"cần ít nhất {MIN_CROSS_LINGUAL_RATIO:.0%}"
            )
    return report
