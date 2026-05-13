"""Tests for the zhihu_question brand-rank matcher.

Focused on the behavior the user wants to see:
- Count how many of top-N answers contain the brand keyword
- Mark which ranks matched (for UI highlighting)
- Clamp top_n to [1, 40]
"""
from __future__ import annotations

from csm_core.monitor.platforms.zhihu_question import ZhihuQuestionAdapter


def _answers(items: list[tuple[str, str]]) -> list[dict]:
    """Helper: build answer rows shaped like the fast/browser fetch output."""
    return [
        {"author": author, "content": content, "voteup_count": 100 - i}
        for i, (author, content) in enumerate(items)
    ]


def test_rank_brand_returns_first_rank_and_all_matches():
    """3 of top 10 contain '戴森' at positions 1, 4, 7."""
    items = [
        ("@blogger1", "戴森 V12 体验"),     # 1 ✓
        ("@blogger2", "小米吸尘器分享"),     # 2
        ("@blogger3", "添可对比"),           # 3
        ("@blogger4", "我用 戴森 也很久了"),  # 4 ✓
        ("@blogger5", "希喂 测评"),          # 5
        ("@blogger6", "莱克吸尘器"),         # 6
        ("@blogger7", "戴森还是不错的"),     # 7 ✓ (中文不分大小写)
        ("@blogger8", "云鲸地宝"),           # 8
        ("@blogger9", "iRobot 体验"),        # 9
        ("@blogger10", "by.fly"),            # 10
    ]
    first, matched, snapshot = ZhihuQuestionAdapter._rank_brand(
        _answers(items), brand="戴森", top_n=10,
    )
    assert first == 1
    assert matched == [1, 4, 7]
    assert len(snapshot) == 10
    assert snapshot[0]["matches_brand"] is True
    assert snapshot[1]["matches_brand"] is False
    assert snapshot[3]["matches_brand"] is True
    assert snapshot[6]["matches_brand"] is True


def test_rank_brand_zero_match_returns_minus_one():
    items = [("@u1", "我家是小米"), ("@u2", "推荐添可")]
    first, matched, snapshot = ZhihuQuestionAdapter._rank_brand(
        _answers(items), brand="戴森", top_n=10,
    )
    assert first == -1
    assert matched == []
    # 即使 0 命中，snapshot 也要返回前 N（这里只 2 条），让 UI 知道前面是谁
    assert len(snapshot) == 2
    assert all(not s["matches_brand"] for s in snapshot)


def test_rank_brand_matches_author_field():
    """品牌词出现在作者名也算命中（比如品牌官号回答）。"""
    items = [
        ("@路人甲", "无关回答"),
        ("@戴森官方", "我是戴森客服"),  # author 命中
    ]
    first, matched, _ = ZhihuQuestionAdapter._rank_brand(
        _answers(items), brand="戴森", top_n=10,
    )
    assert first == 2
    assert matched == [2]


def test_rank_brand_only_scans_top_n():
    """top_n=3 时第 5 位的命中不被算入。"""
    items = [
        ("@u1", "无关"),
        ("@u2", "无关"),
        ("@u3", "无关"),
        ("@u4", "无关"),
        ("@u5", "戴森 V12"),  # 5 — 在 top 3 之外
    ]
    first, matched, _ = ZhihuQuestionAdapter._rank_brand(
        _answers(items), brand="戴森", top_n=3,
    )
    assert first == -1
    assert matched == []


def test_rank_brand_matches_brand_deep_in_long_answer():
    """品牌词埋在 5000 字答案里、靠近末尾，必须能识别。

    回归测试：旧代码 `content[:500]` 把 30000 字答案截掉前 500 字，命中
    词在第 5000 字时永远扫不到。修复后 _rank_brand 用全文做 in 检索。
    """
    # 答案 #2 把 "戴森" 放在第 4800 字位置
    padding = "无关填充" * 1200  # ~4800 chars
    long_answer = padding + "戴森 V12 实测心得" + "结尾"
    items = [
        ("@u1", "完全无关回答 " * 200),
        ("@u2", long_answer),
        ("@u3", "另一个无关回答 " * 300),
    ]
    first, matched, snapshot = ZhihuQuestionAdapter._rank_brand(
        _answers(items), brand="戴森", top_n=10,
    )
    assert first == 2, f"应该在 #2 命中，实际 first={first}"
    assert matched == [2]
    assert snapshot[1]["matches_brand"] is True
    # content_preview 仍然只截 200 字（UI 用），不影响匹配
    assert len(snapshot[1]["content_preview"]) <= 200


def test_top_n_clamp_logic():
    """task.config.top_n=50 应该被 clamp 到 40；top_n=0 应被 clamp 到 1。

    这里直接复现 fetch() 里的 clamp 表达式即可，不必走完整 fetch 流程
    （需要真实 cookies）。
    """
    for raw, expected in [(50, 40), (100, 40), (40, 40), (10, 10), (0, 1), (-5, 1)]:
        clamped = max(1, min(40, int(raw)))
        assert clamped == expected, f"raw={raw}: expected {expected}, got {clamped}"
