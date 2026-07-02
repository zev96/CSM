import pytest

from csm_core.vault.chunking import ChunkResult, split_for_atomize

SENT_END = tuple("。！？!?\n")


def _nospace(s: str) -> str:
    return "".join(s.split())


def test_short_text_single_chunk():
    r = split_for_atomize("短文。", max_chars=100)
    assert r.chunks == ["短文。"] and r.truncated is False and r.dropped_chars == 0


def test_empty():
    assert split_for_atomize("  ") == ChunkResult()


def test_chunks_respect_max_and_sentence_boundary():
    text = "".join(f"第{i}句，测试内容比较长一些。" for i in range(200))
    r = split_for_atomize(text, max_chars=500)
    assert len(r.chunks) > 1
    for c in r.chunks:
        assert len(c) <= 500
        assert c.rstrip().endswith(SENT_END) or c is r.chunks[-1]


def test_no_content_loss_when_not_truncated():
    text = "\n\n".join(f"## 标题{i}\n" + "内容句。" * 50 for i in range(6))
    r = split_for_atomize(text, max_chars=400)
    assert r.truncated is False
    assert _nospace("".join(r.chunks)) == _nospace(text)


def test_heading_prefers_new_chunk():
    text = ("引言。" * 120) + "\n\n## 参数详解\n" + ("参数句。" * 120)
    r = split_for_atomize(text, max_chars=600)
    assert any(c.lstrip().startswith("## 参数详解") for c in r.chunks)


def test_cap_truncates_tail():
    text = "长句测试内容。" * 4000          # 28000 字
    r = split_for_atomize(text, max_chars=1000, cap=3)
    assert len(r.chunks) == 3 and r.truncated is True
    assert r.dropped_chars > 0


def test_pathological_no_punct_hard_cut():
    text = "字" * 2500
    r = split_for_atomize(text, max_chars=1000)
    assert len(r.chunks) == 3
    assert all(len(c) <= 1000 for c in r.chunks)


def test_hard_limit_bounds_cpu_and_counts_dropped():
    text = "字" * (8000 * 8 * 3 + 500)     # 超硬上限 500 字
    r = split_for_atomize(text)             # 默认 max_chars=8000, cap=8
    assert r.truncated is True
    assert r.dropped_chars >= 500
    assert len(r.chunks) == 8


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        split_for_atomize("正文。", max_chars=0)
    with pytest.raises(ValueError):
        split_for_atomize("正文。", max_chars=-5)
    with pytest.raises(ValueError):
        split_for_atomize("正文。", max_chars=100, cap=0)


def test_no_empty_chunks_ever():
    # 混合空白段/超短段的构造输入：任何配置下不产出空 chunk
    text = ("句。\n\n\n\n" + " \n\n" + "词" * 120 + "\n\n## 标\n" + "尾句。") * 3
    r = split_for_atomize(text, max_chars=50)
    assert all(c.strip() for c in r.chunks)


def test_no_empty_chunks_small_max_chars_guard_path():
    # 极小 max_chars 下超长块的尾部空白句会单独撑爆缓冲——去掉空块守卫
    # 这条会产出空 chunk（变异捕获输入，终审提供）
    r = split_for_atomize("甲。甲。甲。\n\n乙。乙。乙。乙。", max_chars=4)
    assert r.chunks and all(c.strip() for c in r.chunks)
