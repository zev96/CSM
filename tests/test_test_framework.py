"""Tests for csm_core.test_framework.section_parser."""
from __future__ import annotations
from textwrap import dedent

import pytest

from csm_core.test_framework import (
    BrandSection,
    extract_brand_sections,
    find_section_for_topic,
    normalize_section_title,
)


# ── Section parser ─────────────────────────────────────────────────────


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("云测1：吸力测试",       "吸力测试"),
        ("云测3 噪音控制",         "噪音控制"),
        ("实测2：常见干垃圾测试",  "常见干垃圾测试"),
        ("测试4: 续航",            "续航"),
        ("噪音对比",               "噪音对比"),  # 无前缀保留
        ("",                       ""),
    ])
    def test_strips_known_prefixes(self, raw, expected):
        assert normalize_section_title(raw) == expected


class TestExtractSections:
    def test_basic_split(self):
        body = dedent("""\
            ## 云测1：吸力测试

            测试结果：吸力 220 AW

            ## 云测2：尘杯测试

            测试结果：0.6L 容量
            """)
        sections = extract_brand_sections(body)
        assert len(sections) == 2
        assert sections[0].normalized_title == "吸力测试"
        assert "220 AW" in sections[0].body
        assert sections[1].normalized_title == "尘杯测试"
        assert "0.6L" in sections[1].body

    def test_drops_preamble_before_first_h2(self):
        body = "无关序言\n\n## 云测1：吸力测试\n测试结果"
        sections = extract_brand_sections(body)
        assert len(sections) == 1
        assert "序言" not in sections[0].body

    def test_empty_body(self):
        assert extract_brand_sections("") == []
        assert extract_brand_sections("没有 H2 的纯文本") == []


class TestFindSection:
    def _sections(self):
        return [
            BrandSection("云测1：吸力测试",     "吸力测试",       "吸力 220 AW"),
            BrandSection("云测2：尘杯测试",     "尘杯测试",       "0.6L"),
            BrandSection("云测3：噪音控制水平", "噪音控制水平",   "70dB"),
            BrandSection("实测1：粉尘清洁测试", "粉尘清洁测试",   "覆盖 95%"),
        ]

    def test_exact_match(self):
        s = find_section_for_topic(self._sections(), "尘杯测试")
        assert s.body == "0.6L"

    def test_topic_substring_in_title(self):
        # "噪音" 是 "噪音控制水平" 的子串 → 命中。
        s = find_section_for_topic(self._sections(), "噪音")
        assert s and s.normalized_title == "噪音控制水平"

    def test_title_substring_in_topic(self):
        # 框架 "尘杯容量对比" 包含 "尘杯测试" 则不行 — 但反向匹配命中。
        # 这里 "尘杯" 是 sections 里 "尘杯测试" 的子串 → 命中 pass 2.
        s = find_section_for_topic(self._sections(), "尘杯")
        assert s and s.normalized_title == "尘杯测试"

    def test_no_match_returns_none(self):
        assert find_section_for_topic(self._sections(), "完全不沾边的项") is None

    def test_empty_inputs(self):
        assert find_section_for_topic([], "anything") is None
        assert find_section_for_topic(self._sections(), "") is None
