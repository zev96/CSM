"""Tests for text_match — comment similarity matching."""
from __future__ import annotations
import pytest

from csm_core.monitor.text_match import (
    DEFAULT_SIMILARITY_THRESHOLD,
    calculate_similarity,
    find_best_match,
    match_in_range,
    normalize_text,
)


class TestNormalize:
    def test_strips_whitespace_and_punctuation(self):
        assert normalize_text("这个产品 真的 非常好用！！！") == "这个产品真的非常好用"

    def test_lowercases_ascii(self):
        assert normalize_text("Hello World!") == "helloworld"

    def test_drops_emoji(self):
        assert normalize_text("好用👍 推荐") == "好用推荐"

    def test_empty_input(self):
        assert normalize_text(None) == ""
        assert normalize_text("") == ""
        assert normalize_text("   ") == ""


class TestSimilarity:
    def test_identical_strings(self):
        assert calculate_similarity("这个产品很好", "这个产品很好") == 1.0

    def test_punctuation_invariance(self):
        # The matcher should treat punctuation as noise.
        assert calculate_similarity("好用！！", "好用") == 1.0

    def test_zero_for_empty(self):
        assert calculate_similarity("", "anything") == 0.0
        assert calculate_similarity(None, "x") == 0.0

    def test_partial_overlap(self):
        sim = calculate_similarity("这个产品真的很好", "这个产品挺好的")
        assert 0.4 < sim < 1.0


class TestFindBestMatch:
    def _comments(self) -> list[dict]:
        return [
            {"text": "完全不相关", "rank": 1},
            {"text": "这个产品真的非常好用", "rank": 2},
            {"text": "另一条评论", "rank": 3},
        ]

    def test_finds_exact_match_with_correct_rank(self):
        r = find_best_match("这个产品真的非常好用", self._comments())
        assert r["found"] is True
        assert r["rank"] == 2
        assert r["similarity"] == pytest.approx(1.0)

    def test_no_match_below_threshold(self):
        # Function records the best partial-similarity rank even when
        # the score doesn't clear the threshold. ``found`` is what
        # callers check; rank is informational in that case.
        r = find_best_match("毫无相关内容", self._comments(), threshold=0.95)
        assert r["found"] is False
        assert r["similarity"] < 0.95

    def test_threshold_default_used_when_omitted(self):
        # Same input but with default threshold => still matches.
        r = find_best_match("这个产品真的非常好用！！！", self._comments())
        assert r["found"] is True
        assert r["threshold_used"] == DEFAULT_SIMILARITY_THRESHOLD

    def test_empty_target(self):
        r = find_best_match("", self._comments())
        assert r["found"] is False
        assert r["rank"] == -1


class TestMatchInRange:
    def test_slice_boundary_is_respected(self):
        comments = [
            {"text": "miss", "rank": 1},
            {"text": "肉夹馍真好吃", "rank": 2},
        ]
        # Slicing out the only matching comment should miss.
        r = match_in_range("肉夹馍真好吃", comments, start=0, end=1)
        assert r["found"] is False
