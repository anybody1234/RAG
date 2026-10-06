"""Sparse vector kiểu BM25 cho tiếng Việt và tiếng Anh, không cần model chạy trên máy.

Term gồm âm tiết/từ (tách theo khoảng trắng và dấu câu) và bigram của hai âm tiết liền nhau, để khớp được
cả cụm như "điều 35", "45 2019", "thử việc". Vector văn bản mang phần TF của BM25; IDF do Qdrant tính
(`modifier: idf`), nên vector câu hỏi chỉ cần trọng số 1 cho mỗi term.
"""

import hashlib
import re
import unicodedata
from collections import Counter

from qdrant_client import models

# Số có dấu phân cách bên trong ("20.000.000", "1,5") giữ thành một token; còn lại là chuỗi chữ/số.
_TOKEN = re.compile(r"\d+(?:[.,]\d+)+|\w+")
# Không tạo bigram qua dấu câu hoặc xuống dòng. Dấu "/" không chặn để "45/2019/QH14" có bigram "45 2019".
_BIGRAM_BREAK = re.compile(r"[.,;:!?()\[\]{}“”\"…\n]")


def _split(text: str) -> tuple[list[str], list[str]]:
    text = unicodedata.normalize("NFC", text).lower()
    unigrams: list[str] = []
    bigrams: list[str] = []
    previous_end = None
    for match in _TOKEN.finditer(text):
        token = match.group()
        if previous_end is not None and not _BIGRAM_BREAK.search(text, previous_end, match.start()):
            bigrams.append(f"{unigrams[-1]} {token}")
        unigrams.append(token)
        previous_end = match.end()
    return unigrams, bigrams


def tokenize(text: str) -> list[str]:
    """Âm tiết/từ (NFC, chữ thường) rồi đến các bigram, theo thứ tự xuất hiện."""
    unigrams, bigrams = _split(text)
    return unigrams + bigrams


def term_index(term: str) -> int:
    """Chỉ số ổn định (uint32) của term trong sparse vector. Hai term trùng chỉ số thì được cộng dồn."""
    return int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=4).digest(), "little")


def _term_counts(terms: list[str]) -> Counter[int]:
    return Counter(term_index(term) for term in terms)


class SparseEncoder:
    def __init__(self, k1: float, b: float, avg_doc_len: float):
        self.k1, self.b, self.avg_doc_len = k1, b, avg_doc_len

    def encode_document(self, text: str) -> models.SparseVector:
        """Trọng số TF của BM25: tf·(k1 + 1) / (tf + k1·(1 − b + b·dl/avgdl)), dl là số âm tiết/từ."""
        unigrams, bigrams = _split(text)
        norm = self.k1 * (1 - self.b + self.b * len(unigrams) / self.avg_doc_len)
        counts = sorted(_term_counts(unigrams + bigrams).items())
        return models.SparseVector(
            indices=[index for index, _ in counts],
            values=[tf * (self.k1 + 1) / (tf + norm) for _, tf in counts],
        )

    def encode_query(self, text: str) -> models.SparseVector:
        indices = sorted(_term_counts(tokenize(text)))
        return models.SparseVector(indices=indices, values=[1.0] * len(indices))
