import math

import pytest

from app.evaluation.golden import GoldSource
from app.evaluation.retrieval_metrics import (
    ChunkRef,
    covers,
    hit_at,
    mrr_at,
    ndcg_at,
    percentile,
    question_metrics,
    recall_at,
    source_ranks,
)

SOURCE = GoldSource(doc_id="luat", page=5, quote="thời gian thử việc  không quá 60 ngày")


def chunk(chunk_id: str, doc_id: str = "luat", page: int = 4, page_end: int = 6, text: str = "") -> ChunkRef:
    return ChunkRef.from_payload(
        {"chunk_id": chunk_id, "doc_id": doc_id, "page": page, "page_end": page_end, "text": text}
    )


GOOD = "Điều 25.\nThời gian thử việc không quá 60 ngày đối với..."


def test_covers_needs_same_doc_page_range_and_quote():
    assert covers(chunk("c", text=GOOD), GoldSource(doc_id="luat", page=5, quote="Thời gian thử việc không quá 60"))
    assert covers(chunk("c", text="... thời gian thử việc\nkhông quá 60 ngày ..."), SOURCE)
    assert not covers(chunk("c", doc_id="khac", text="thời gian thử việc không quá 60 ngày"), SOURCE)
    assert not covers(chunk("c", page=6, page_end=7, text="thời gian thử việc không quá 60 ngày"), SOURCE)
    assert not covers(chunk("c", text="thời gian thử việc không quá 30 ngày"), SOURCE)


def test_source_ranks_take_first_matching_chunk():
    other = GoldSource(doc_id="luat", page=5, quote="nghỉ hằng năm 12 ngày")
    ranked = [
        chunk("a", text="không liên quan"),
        chunk("b", text="thời gian thử việc không quá 60 ngày"),
        chunk("c", text="thời gian thử việc không quá 60 ngày (chunk overlap)"),
    ]
    assert source_ranks(ranked, [SOURCE, other]) == [2, None]


def test_metrics_for_one_source():
    assert question_metrics([1], [5]) == {"hit@5": 1.0, "recall@5": 1.0, "mrr@5": 1.0, "ndcg@5": 1.0}
    assert mrr_at([3], 5) == pytest.approx(1 / 3)
    assert ndcg_at([3], 5) == pytest.approx(1 / math.log2(4))
    # Nằm ngoài top-k thì không tính.
    assert (hit_at([6], 5), recall_at([6], 5), mrr_at([6], 5), ndcg_at([6], 5)) == (0.0, 0.0, 0.0, 0.0)
    assert hit_at([None], 50) == 0.0


def test_metrics_for_multiple_sources():
    ranks = [2, None]
    assert (hit_at(ranks, 5), recall_at(ranks, 5), mrr_at(ranks, 5)) == (1.0, 0.5, 0.5)
    assert ndcg_at(ranks, 5) == pytest.approx((1 / math.log2(3)) / (1 + 1 / math.log2(3)))
    assert ndcg_at([1, 2], 5) == pytest.approx(1.0)


def test_ndcg_is_capped_when_one_chunk_covers_several_sources():
    assert ndcg_at([1, 1], 5) == 1.0


def test_percentile_interpolates():
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)
    assert percentile([7], 95) == 7
