"""Shingles: char-level n-grams for Chinese plagiarism detection."""
from csm_core.dedup.shingles import compute_shingles, compute_shingles_with_positions


def test_compute_shingles_basic():
    text = "今天天气真好，适合出门散步"
    shingles = compute_shingles(text, n=4)
    assert len(shingles) == 10
    assert "今天天气" in shingles
    assert "适合出门" in shingles


def test_compute_shingles_returns_set():
    """Set semantics: duplicates collapse."""
    text = "abcabcabc"
    shingles = compute_shingles(text, n=3)
    assert shingles == {"abc", "bca", "cab"}


def test_compute_shingles_short_text_returns_empty():
    assert compute_shingles("abc", n=4) == set()
    assert compute_shingles("", n=4) == set()


def test_compute_shingles_unicode():
    """中文字符 + emoji + 英文混合应正确切片。"""
    text = "Hello世界🌍test"
    shingles = compute_shingles(text, n=3)
    assert "Hel" in shingles
    assert "lo世" in shingles
    assert len(shingles) >= 8


def test_compute_shingles_with_positions_returns_dict():
    text = "abcabc"
    posed = compute_shingles_with_positions(text, n=3)
    assert posed["abc"] == [0, 3]
    assert posed["bca"] == [1]
    assert posed["cab"] == [2]


def test_compute_shingles_default_n_is_13():
    """默认 n=13 字符（中文论文查重常用粒度）。"""
    text = "一二三四五六七八九十一二三四"  # 14 字符
    shingles = compute_shingles(text)
    assert len(shingles) == 14 - 13 + 1  # = 2
