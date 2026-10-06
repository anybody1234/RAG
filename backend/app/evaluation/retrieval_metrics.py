"""Metric retrieval trên golden set, không cần LLM.

Một chunk trúng một nguồn gold khi cùng `doc_id`, khoảng trang [page, page_end] của chunk chứa trang gold, và
text chunk chứa đoạn trích (so sau `normalize_for_match`). Mỗi nguồn gold được tính ở vị trí của chunk đầu
tiên trúng nó; từ danh sách vị trí đó suy ra mọi metric.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.evaluation.golden import GoldSource, normalize_for_match


@dataclass(frozen=True)
class ChunkRef:
    """Phần thông tin của chunk cần để chấm. `text` đã qua `normalize_for_match`."""

    chunk_id: str
    doc_id: str
    page: int | None
    page_end: int | None
    text: str

    @classmethod
    def from_payload(cls, payload: dict) -> "ChunkRef":
        return cls(
            chunk_id=payload["chunk_id"],
            doc_id=payload["doc_id"],
            page=payload.get("page"),
            page_end=payload.get("page_end"),
            text=normalize_for_match(payload["text"]),
        )


def covers(chunk: ChunkRef, source: GoldSource) -> bool:
    return (
        chunk.doc_id == source.doc_id
        and chunk.page is not None
        and chunk.page <= source.page <= (chunk.page_end or chunk.page)
        and normalize_for_match(source.quote) in chunk.text
    )


def source_ranks(ranked: Sequence[ChunkRef], sources: Sequence[GoldSource]) -> list[int | None]:
    """Vị trí (bắt đầu từ 1) của chunk đầu tiên trúng từng nguồn gold; None nếu không chunk nào trúng."""
    return [next((rank for rank, chunk in enumerate(ranked, start=1) if covers(chunk, s)), None) for s in sources]


def _found(ranks: Iterable[int | None], k: int) -> list[int]:
    return [rank for rank in ranks if rank is not None and rank <= k]


def hit_at(ranks: Sequence[int | None], k: int) -> float:
    """1 nếu ít nhất một nguồn gold có trong top-k."""
    return float(bool(_found(ranks, k)))


def recall_at(ranks: Sequence[int | None], k: int) -> float:
    """Tỉ lệ nguồn gold có trong top-k."""
    return len(_found(ranks, k)) / len(ranks)


def mrr_at(ranks: Sequence[int | None], k: int) -> float:
    """1 / vị trí của chunk trúng đầu tiên trong top-k."""
    found = _found(ranks, k)
    return 1 / min(found) if found else 0.0


def ndcg_at(ranks: Sequence[int | None], k: int) -> float:
    """nDCG với gain nhị phân theo nguồn gold: mỗi nguồn góp 1/log2(vị trí + 1) tại chunk đầu tiên trúng nó.

    DCG lý tưởng: n nguồn nằm ở n vị trí đầu. Một chunk trúng nhiều nguồn cùng lúc có thể làm DCG vượt mức
    lý tưởng, nên kết quả bị chặn ở 1.
    """
    dcg = sum(1 / math.log2(rank + 1) for rank in _found(ranks, k))
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(ranks), k) + 1))
    return min(1.0, dcg / ideal)


METRICS = {"hit": hit_at, "recall": recall_at, "mrr": mrr_at, "ndcg": ndcg_at}


def question_metrics(ranks: Sequence[int | None], ks: Sequence[int]) -> dict[str, float]:
    """{"hit@5": ..., "recall@5": ..., ...} cho một câu hỏi."""
    return {f"{name}@{k}": metric(ranks, k) for k in ks for name, metric in METRICS.items()}


def mean_metrics(rows: Sequence[dict[str, float]]) -> dict[str, float]:
    return {key: sum(row[key] for row in rows) / len(rows) for key in rows[0]} if rows else {}


def percentile(values: Sequence[float], q: float) -> float:
    """Phân vị q (0–100), nội suy tuyến tính giữa hai giá trị gần nhất (giống numpy mặc định)."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
