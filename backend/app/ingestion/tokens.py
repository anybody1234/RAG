"""Đếm token theo tokenizer của model embedding (text-embedding-3-* dùng cl100k_base)."""

from functools import lru_cache

import tiktoken


@lru_cache
def _encoding(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


class TokenCounter:
    """Đếm token có cache, vì chunker đếm lại cùng một đoạn nhiều lần khi gom nhóm."""

    def __init__(self, model: str):
        self._encoding = _encoding(model)
        self._cache: dict[str, int] = {}

    def __call__(self, text: str) -> int:
        count = self._cache.get(text)
        if count is None:
            count = self._cache[text] = len(self._encoding.encode(text, disallowed_special=()))
        return count


def truncate_tokens(text: str, max_tokens: int, model: str) -> str:
    """Giữ `max_tokens` token đầu của text (theo tokenizer của `model`), thêm " …" khi bị cắt."""
    tokens = _encoding(model).encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    # Cắt giữa một ký tự nhiều byte thì decode ra "�" ở cuối: bỏ đi.
    return _encoding(model).decode(tokens[:max_tokens]).rstrip("\ufffd") + " …"
