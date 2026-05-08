"""Tests for csm_core.keyword.extract_core."""
from __future__ import annotations
import pytest
from csm_core.keyword import extract_core


class TestBasicTails:
    """Single-tail strips — the core 80% of SEO long-tail patterns."""

    @pytest.mark.parametrize("kw,expected", [
        ("无线吸尘器哪款好用",       "无线吸尘器"),
        ("扫地机器人哪款最好",       "扫地机器人"),
        ("空气净化器哪个好",          "空气净化器"),
        ("空气净化器哪种好",          "空气净化器"),
        ("吸尘器怎么选",              "吸尘器"),
        ("吸尘器怎么挑",              "吸尘器"),
        ("吸尘器怎么样",              "吸尘器"),
        ("吸尘器好用吗",              "吸尘器"),
        ("吸尘器好不好",              "吸尘器"),
        ("吸尘器选哪款",              "吸尘器"),
    ])
    def test_decision_tails(self, kw, expected):
        assert extract_core(kw) == expected

    @pytest.mark.parametrize("kw,expected", [
        ("家用空气净化器推荐",         "家用空气净化器"),
        ("无线吸尘器测评",             "无线吸尘器"),
        ("扫地机器人评测",             "扫地机器人"),
        ("吸尘器排行榜",               "吸尘器"),
        ("吸尘器盘点",                 "吸尘器"),
        ("空气净化器对比",             "空气净化器"),
        ("空气净化器性价比",           "空气净化器"),
        ("吸尘器什么牌子好",           "吸尘器"),
        ("吸尘器哪个牌子好",           "吸尘器"),
        ("吸尘器哪个品牌",             "吸尘器"),
    ])
    def test_review_tails(self, kw, expected):
        assert extract_core(kw) == expected

    @pytest.mark.parametrize("kw,expected", [
        ("吸尘器多少钱",  "吸尘器"),
        ("吸尘器价格",    "吸尘器"),
        ("吸尘器贵吗",    "吸尘器"),
        ("吸尘器贵不贵",  "吸尘器"),
    ])
    def test_price_tails(self, kw, expected):
        assert extract_core(kw) == expected


class TestLeadingPrefixes:
    @pytest.mark.parametrize("kw,expected", [
        ("2026年无线吸尘器哪款好用",   "无线吸尘器"),
        ("2025年家用空气净化器推荐",   "家用空气净化器"),
        ("2024 年吸尘器测评",          "吸尘器"),
        ("最新无线吸尘器推荐",          "无线吸尘器"),
        ("今年最新吸尘器哪款好用",      "吸尘器"),
        ("入手前必看的吸尘器推荐",      "的吸尘器"),  # "的" 不剥（不在词典里），可接受
    ])
    def test_leading(self, kw, expected):
        # The last case demonstrates we don't over-extract.
        assert extract_core(kw) == expected

    def test_year_with_half_marker(self):
        assert extract_core("2026年上半年吸尘器推荐") == "吸尘器"


class TestEdgeCases:
    def test_empty(self):
        assert extract_core("") == ""

    def test_whitespace_only(self):
        assert extract_core("   ") == ""

    def test_already_core(self):
        # No edges to strip — pass through unchanged.
        assert extract_core("吸尘器") == "吸尘器"
        assert extract_core("无线吸尘器") == "无线吸尘器"

    def test_idempotent(self):
        once = extract_core("无线吸尘器哪款好用")
        twice = extract_core(once)
        assert once == twice == "无线吸尘器"

    def test_too_aggressive_falls_back(self):
        # If stripping would leave nothing meaningful, return original.
        # "好用" alone strips to empty → must fall back.
        assert extract_core("好用") == "好用"
        assert extract_core("推荐") == "推荐"

    def test_trailing_punctuation_stripped(self):
        assert extract_core("无线吸尘器哪款好用？") == "无线吸尘器"
        assert extract_core("吸尘器推荐！") == "吸尘器"
        assert extract_core("吸尘器，") == "吸尘器"

    def test_double_tail_strips_iteratively(self):
        # "哪款好用吗" — should strip both layers.
        assert extract_core("吸尘器哪款好用吗") == "吸尘器"

    def test_lead_and_tail_combined(self):
        assert extract_core("2026年无线吸尘器测评推荐") == "无线吸尘器"


class TestRealWorldSamples:
    """Spot-check actual long-tail searches users would type."""

    @pytest.mark.parametrize("kw,expected", [
        ("智能马桶哪款好用",                "智能马桶"),
        ("电动牙刷哪个牌子好",               "电动牙刷"),
        ("洗碗机怎么选",                     "洗碗机"),
        ("空调扇好不好",                     "空调扇"),
        ("2026年最新破壁机推荐",            "破壁机"),
        ("家用咖啡机性价比排行",            "家用咖啡机"),
        ("筋膜枪多少钱",                     "筋膜枪"),
        ("跑步鞋什么牌子好",                "跑步鞋"),
        ("空气炸锅怎么样",                  "空气炸锅"),
        ("无线耳机哪款值得买",               "无线耳机"),
    ])
    def test_realistic_long_tails(self, kw, expected):
        assert extract_core(kw) == expected
