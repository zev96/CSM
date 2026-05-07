"""Tests for csm_core.test_framework — section parser + sampler."""
from __future__ import annotations
import random
from pathlib import Path
from textwrap import dedent

import pytest

from csm_core.test_framework import (
    BrandSection,
    extract_brand_sections,
    find_section_for_topic,
    normalize_section_title,
    sample_test_framework_block,
)
from csm_core.test_framework.sampler import TestFrameworkConfig
from csm_core.vault.scanner import scan_vault


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


# ── End-to-end sampler ─────────────────────────────────────────────────


def _make_vault_with_frameworks_and_brands(tmp_path: Path) -> Path:
    """Build a temp vault with 2 frameworks + 2 brand notes.

    The 吸力对比 framework note has TWO ①② variants so the random-pick
    behaviour can be exercised; 噪音对比 has a single (no-variant) body.
    """
    fw_dir = tmp_path / "营销资料库" / "产品模块" / "吸尘器" / "云测试项目框架"
    fw_dir.mkdir(parents=True)
    (fw_dir / "云测-吸力对比.md").write_text(dedent("""\
        ---
        测试项: 吸力测试
        素材类型: 云测试项目框架
        ---
        ## 二、无线吸尘器测试对比

        ## ①框架1 — 纯点评

        测试原理：声压级测量。
        测试方法：使用功率计。
        测试数据图：

        测试总结：差异明显。

        主推 测试部分：
        竞品A 测试部分：
        竞品B 测试部分：

        ## ②框架2 - 排序+点评

        测试原理：声压级测量。
        测试方法：使用功率计。

        排名：主推 > 竞品A > 竞品B

        主推 测试部分：
        竞品A 测试部分：
        竞品B 测试部分：
        """), encoding="utf-8")
    (fw_dir / "云测-噪音对比.md").write_text(dedent("""\
        ---
        测试项: 噪音控制
        素材类型: 云测试项目框架
        ---
        ## 噪音参数对比

        测试原理：分贝测量。

        主推 测试部分：
        竞品A 测试部分：
        """), encoding="utf-8")

    res_dir = tmp_path / "营销资料库" / "产品模块" / "吸尘器" / "品牌产品测试结果"
    res_dir.mkdir(parents=True)
    (res_dir / "戴森V8-测试结果.md").write_text(dedent("""\
        ---
        型号: 戴森V8
        素材类型: 测试数据
        ---
        ## 云测1：吸力测试

        测试结果：220 AW，强劲。

        ## 云测2：噪音控制水平

        测试结果：70 dB，偏吵。
        """), encoding="utf-8")
    (res_dir / "米家2-测试结果.md").write_text(dedent("""\
        ---
        型号: 米家2
        素材类型: 测试数据
        ---
        ## 云测1：吸力测试

        测试结果：130 AW，够用。
        """), encoding="utf-8")
    return tmp_path


class TestSampler:
    def test_picks_and_fills(self, tmp_path: Path):
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
            hero_slot="主推",
            competitor_slots=("竞品A", "竞品B"),
        )
        text, warnings = sample_test_framework_block(
            cfg=cfg,
            follow_models=["戴森V8", "米家2", "苏泊尔C36"],
            vault=idx,
            brand_of=lambda m: None,
            rng=random.Random(42),
        )
        # H2 应来自笔记文件名（剥掉"云测-"前缀，并按 number_style 加 "1."、"2." 序号）
        assert "## 1. 吸力对比" in text
        assert "## 2. 噪音对比" in text
        # 不应该出现笔记里"## 二、无线吸尘器测试对比" 这种前言 H2
        assert "二、无线吸尘器测试对比" not in text
        # Hero slot — 戴森V8 has both topics → both filled
        assert "戴森V8 测试部分：" in text
        assert "220 AW" in text   # 吸力 result
        assert "70 dB" in text    # 噪音 result
        # 竞品A — 米家2 has 吸力 only
        assert "米家2 测试部分：" in text
        assert "130 AW" in text
        # 竞品B — 苏泊尔C36 has no note → placeholder
        assert "[缺数据：苏泊尔C36" in text
        # No warnings (everything resolved with placeholders or data)
        assert warnings == []

    def test_only_one_variant_picked_from_multi_variant_note(self, tmp_path: Path):
        """吸力笔记里有 ①② 两个框架变体，每次生成只能选中其一。"""
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=1,  # 只抽吸力对比
            hero_slot="主推",
            competitor_slots=("竞品A", "竞品B"),
        )
        # 用不同 seed 触发不同变体；任何一次输出都不应同时含两个变体的特征。
        seen_v1 = seen_v2 = False
        for seed in range(20):
            text, _ = sample_test_framework_block(
                cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
                vault=idx, brand_of=lambda m: None, rng=random.Random(seed),
            )
            # 跳过随机抽到噪音笔记的轮次（pick_count=1，每次只抽一个）
            if "吸力对比" not in text:
                continue
            # 单次输出里 "测试方法：" 字段最多出现一次
            assert text.count("测试方法：") <= 1
            # 不能同时出现框架1的"测试总结"和框架2的"排名"
            has_summary = "测试总结" in text
            has_rank = "排名：" in text
            assert not (has_summary and has_rank), \
                f"两个变体同时出现了：\n{text}"
            if has_summary:
                seen_v1 = True
            if has_rank:
                seen_v2 = True
        # 20 次足以观察到两个变体（概率上 ~99.9999%）
        assert seen_v1, "20 次抽样竟然一次都没抽到框架1，random 出问题了"
        assert seen_v2, "20 次抽样竟然一次都没抽到框架2，random 出问题了"

    def test_inline_label_substitution(self, tmp_path: Path):
        """框架笔记里 "测试排名：主推 > 竞品A > 竞品B" 之类的行内标签也要替换。

        变体 ② 的 body 含 "排名：主推 > 竞品A > 竞品B" 一行；这条不是
        slot 行（没有"测试部分："后缀），但里面的"主推 / 竞品A / 竞品B"
        应当被替换成实际产品名。
        """
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
        )
        # 多 seed 找到抽中"排序+点评"那条变体的轮次。
        found_v2 = False
        for seed in range(40):
            text, _ = sample_test_framework_block(
                cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
                vault=idx, brand_of=lambda m: None, rng=random.Random(seed),
            )
            if "排名：" in text:
                found_v2 = True
                # 这一行应该被改写为产品名而不是保留标签。
                rank_line = next(
                    (line for line in text.splitlines() if "排名：" in line),
                    "",
                )
                assert "戴森V8" in rank_line, f"主推标签没替换：{rank_line!r}"
                assert "米家2" in rank_line, f"竞品A标签没替换：{rank_line!r}"
                assert "苏泊尔C36" in rank_line, f"竞品B标签没替换：{rank_line!r}"
                # 原标签不应残留
                assert "主推 >" not in rank_line
                assert "竞品A" not in rank_line
                assert "竞品B" not in rank_line
                break
        assert found_v2, "40 次抽样没抽到框架2，random 失常"

    def test_numbered_headings(self, tmp_path: Path):
        """测试项 H2 应按 number_style 加序号。"""
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
            number_style="1.",
        )
        text, _ = sample_test_framework_block(
            cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(7),
        )
        # 两个测试项分别带 "1." 和 "2." 前缀
        assert "## 1. " in text
        assert "## 2. " in text

    def test_chinese_numbering(self, tmp_path: Path):
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
            number_style="一、",
        )
        text, _ = sample_test_framework_block(
            cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(7),
        )
        assert "## 一、" in text
        assert "## 二、" in text

    def test_no_numbering(self, tmp_path: Path):
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
            number_style="none",
        )
        text, _ = sample_test_framework_block(
            cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(7),
        )
        # 不带任何编号前缀
        assert "## 1. " not in text
        assert "## 一、" not in text
        # 但仍有 H2
        assert "## 吸力对比" in text or "## 噪音对比" in text

    def test_framework_label_stripped_from_output(self, tmp_path: Path):
        """变体首行的 "框架1 — 纯点评" / 残留小标题不应出现在输出里。"""
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
        )
        for seed in range(5):
            text, _ = sample_test_framework_block(
                cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
                vault=idx, brand_of=lambda m: None, rng=random.Random(seed),
            )
            assert "框架1 — 纯点评" not in text
            assert "框架2 - 排序+点评" not in text
            assert "噪音参数对比" not in text  # body 内 H2 残留也要剥掉

    def test_unique_constraint(self, tmp_path: Path):
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=5,  # 但只有 2 个候选
            unique_notes=True,
        )
        text, warnings = sample_test_framework_block(
            cfg=cfg, follow_models=["戴森V8", "米家2"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(42),
        )
        # 应该被 cap 到 2 + 报警
        assert any("已降级为全部" in w for w in warnings)
        assert text.count("吸力对比") >= 1
        assert text.count("噪音对比") >= 1
        # 序号化的 H2 应都出现
        assert "## 1. " in text
        assert "## 2. " in text

    def test_no_horizontal_rule_inside_brand_section_body(self, tmp_path: Path):
        """回归：用户在品牌结果笔记里用 ``---`` 当视觉分隔符的话，section
        body 里的 ``---`` 行必须被清掉，否则会：
        1. 渲染成 ``<hr>`` 水平线
        2. 紧跟其后的 "米家3C 测试部分：" 被当成 setext H2 加粗
        """
        # 自建一个带 --- 的 vault
        fw_dir = tmp_path / "营销资料库" / "产品模块" / "吸尘器" / "云测试项目框架"
        fw_dir.mkdir(parents=True)
        (fw_dir / "云测-噪音对比.md").write_text(dedent("""\
            ---
            测试项: 噪音对比
            ---
            ## 噪音参数对比

            主推 测试部分：
            竞品A 测试部分：
            """), encoding="utf-8")

        res_dir = tmp_path / "营销资料库" / "产品模块" / "吸尘器" / "品牌产品测试结果"
        res_dir.mkdir(parents=True)
        (res_dir / "戴森V8-测试结果.md").write_text(dedent("""\
            ---
            型号: 戴森V8
            ---
            ## 云测1：噪音对比

            测试结果：戴森的噪音控制良好。

            ---

            ## 云测2：吸力测试

            测试结果：220 AW。
            """), encoding="utf-8")
        (res_dir / "米家2-测试结果.md").write_text(dedent("""\
            ---
            型号: 米家2
            ---
            ## 云测1：噪音对比

            测试结果：米家偏吵。
            """), encoding="utf-8")

        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=1,
        )
        text, _ = sample_test_framework_block(
            cfg=cfg, follow_models=["戴森V8", "米家2"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(0),
        )
        # 戴森V8 的噪音 section 末尾有 "---"，必须被剥掉
        for line in text.splitlines():
            assert line.strip() != "---", (
                f"section body 里残留水平分隔线 ---：\n{text}"
            )
        # 内容本身保留
        assert "戴森的噪音控制良好" in text
        # 米家2 的部分应该正常显示，不是 setext H2 加粗
        assert "米家2 测试部分：" in text

    def test_no_horizontal_rule_between_test_items(self, tmp_path: Path):
        """回归：测试项之间不应该出现 ``---`` 水平分隔线。

        早期版本的 ``section_separator`` 是 ``\\n\\n---\\n\\n``，markdown
        渲染成水平线，跟 H2 标题的视觉断点重复。改成纯空行后，两个测试
        项之间只剩自然段落间距。
        """
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
        )
        text, _ = sample_test_framework_block(
            cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(7),
        )
        # 输出里不应有以 --- 单独成行的水平分隔线
        for line in text.splitlines():
            assert line.strip() != "---", f"留下了水平分隔线：\n{text}"
            assert line.strip() != "***", f"留下了水平分隔线：\n{text}"

    def test_result_prefix_stripped_from_section_body(self, tmp_path: Path):
        """品牌 section 内容前的 "测试结果：" 标签应该被剥掉。

        Slot 行已经写了 "{品牌} 测试部分："，再带上 "测试结果：" 就重复
        累赘了。各种常见标签（测试结果 / 实测数据 / 数据 / 结果）都剥。
        """
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=2,
        )
        text, _ = sample_test_framework_block(
            cfg=cfg, follow_models=["戴森V8", "米家2", "苏泊尔C36"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(42),
        )
        # 戴森V8 的吸力 section 原文是 "测试结果：220 AW，强劲。"，
        # 剥前缀后只剩内容；不应再出现重复的 "测试部分：测试结果：" 序列。
        assert "测试部分：\n测试结果：" not in text
        assert "220 AW" in text   # 内容本身保留
        assert "70 dB" in text

    def test_resolve_follow_models_strips_competitor_prefix(self):
        """回归：_resolve_follow_models 必须用 meta['title']（已清理）
        而不是 meta['model']（带"竞品-"前缀）。

        Real-world vault notes carry ``型号: 竞品-米家3C`` in frontmatter;
        ``_clean_competitor_title`` strips the prefix into ``meta['title']``
        but ``meta['model']`` keeps the raw value. Earlier versions used
        ``meta['model']`` for follow-resolution → test-result lookup failed
        ("[缺数据：竞品-米家3C ...]") AND inline-substituted prose leaked
        "竞品-米家3C" into rank lines.
        """
        from csm_core.assembler.constraints import _resolve_follow_models
        from csm_core.assembler.plan import BlockResult, PickedVariant

        hero = BlockResult(
            block_id="hero_a", kind="hero_brand", text="CEWEY DS18", meta={},
        )
        pool = BlockResult(
            block_id="pool_a", kind="competitor_pool",
            picks=[
                PickedVariant(
                    note_id="mijia3c-brand", variant_index=0, text="米家3C",
                    # meta carries BOTH raw ``model`` (frontmatter) and
                    # cleaned ``title`` — resolver should pick the title.
                    meta={"model": "竞品-米家3C", "title": "米家3C"},
                ),
                PickedVariant(
                    note_id="delma-brand", variant_index=0, text="德尔玛VC80",
                    meta={"model": "竞品-德尔玛VC80", "title": "德尔玛VC80"},
                ),
            ],
        )
        models = _resolve_follow_models(
            "hero_a+pool_a", {"hero_a": hero, "pool_a": pool},
        )
        assert models == ["CEWEY DS18", "米家3C", "德尔玛VC80"]
        # Make sure no stale prefix sneaks back in
        assert all(not m.startswith("竞品") for m in models)

    def test_empty_framework_module(self, tmp_path: Path):
        idx = scan_vault(tmp_path)  # 空 vault
        cfg = TestFrameworkConfig(
            framework_module="不存在/路径",
            results_module="也不存在",
            pick_count=3,
        )
        text, warnings = sample_test_framework_block(
            cfg=cfg, follow_models=["X"],
            vault=idx, brand_of=lambda m: None, rng=random.Random(42),
        )
        assert text == ""
        assert any("没有任何" in w for w in warnings)

    def test_no_follow_models_yields_placeholders(self, tmp_path: Path):
        _make_vault_with_frameworks_and_brands(tmp_path)
        idx = scan_vault(tmp_path)
        cfg = TestFrameworkConfig(
            framework_module="营销资料库/产品模块/吸尘器/云测试项目框架",
            results_module="营销资料库/产品模块/吸尘器/品牌产品测试结果",
            pick_count=1,
        )
        text, _ = sample_test_framework_block(
            cfg=cfg, follow_models=[],  # 没有任何上游产品
            vault=idx, brand_of=lambda m: None, rng=random.Random(42),
        )
        assert "[缺数据：未选中产品]" in text
