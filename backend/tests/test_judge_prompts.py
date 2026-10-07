"""Prompt judge không được chứa câu hỏi, đoạn trích hay đáp án chuẩn của golden set: judge đã thấy "expected output"
của một câu thì điểm của câu đó (và mức đồng thuận khi hiệu chỉnh) bị đẩy lên giả tạo.

So theo chuỗi 7 từ liên tiếp sau `normalize_for_match`, đủ dài để bắt câu chép lại hay sửa nhẹ, đủ ngắn để không vướng
cụm từ pháp lý thông dụng.
"""

import json
import re

import pytest

from app.core.config import REPO_ROOT
from app.evaluation.golden import normalize_for_match

JUDGES_DIR = REPO_ROOT / "eval" / "judges"
GOLDEN_FILES = sorted((REPO_ROOT / "eval" / "datasets").glob("golden_*.jsonl"))
SHINGLE = 7
# judge-v1 lấy ví dụ từ g034 và g061 của golden v1 (phát hiện 08/10/2026). Giữ nguyên vì đã dùng để chấm kết quả thử
# quy trình (2026-10-08_v0.2-luna_e2e-n5.json); không dùng cho số liệu chính thức.
KNOWN_LEAKY = {"judge-v1"}


def shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", normalize_for_match(text).casefold())
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def golden_shingles() -> dict[tuple[str, ...], str]:
    """Chuỗi 7 từ của mọi câu hỏi, lịch sử hội thoại, đoạn trích và đáp án chuẩn -> id câu."""
    found: dict[tuple[str, ...], str] = {}
    for path in GOLDEN_FILES:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            texts = [item["question"], item.get("reference_answer", "")]
            texts += [turn["content"] for turn in item.get("history", [])]
            texts += [source["quote"] for source in item.get("gold_sources", [])]
            for text in texts:
                for shingle in shingles(text):
                    found.setdefault(shingle, f"{path.name}:{item['id']}")
    return found


GOLDEN = golden_shingles()


def leaks(prompt: str) -> dict[str, str]:
    return {" ".join(s): GOLDEN[s] for s in shingles(prompt) if s in GOLDEN}


@pytest.mark.parametrize("path", sorted(JUDGES_DIR.glob("judge-*.md")), ids=lambda p: p.stem)
def test_judge_prompt_does_not_contain_golden_items(path):
    if path.stem in KNOWN_LEAKY:
        pytest.skip("prompt cũ đã biết có lỗi rò rỉ, giữ để tái lập kết quả thử quy trình")
    assert leaks(path.read_text(encoding="utf-8")) == {}


def test_detector_catches_the_known_leak():
    assert GOLDEN_FILES, "chưa có golden set"
    found = leaks((JUDGES_DIR / "judge-v1.md").read_text(encoding="utf-8"))
    assert any(item_id.endswith(":g034") for item_id in found.values())
