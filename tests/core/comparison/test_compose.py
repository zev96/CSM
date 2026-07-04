"""横评确定性骨架 compose_comparison_draft 单测（合成 memory fixtures）。"""
from __future__ import annotations

from csm_core.brand_memory.inject import ModelScope
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.comparison.compose import _pick_sellpoint_dims, _model_label


def _mem(brand: str, model: str, role: str, *,
         specs: dict[str, str] | None = None,
         scripts: dict[str, list[str]] | None = None,
         certs: list[str] | None = None,
         endorsements: list[str] | None = None,
         tests: dict[str, str] | None = None) -> BrandModelMemory:
    spec_objs = {}
    for f, raw in (specs or {}).items():
        nums = [float(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", raw)]
        spec_objs[f] = SpecValue(field=f, raw=raw, numbers=nums)
    return BrandModelMemory(
        brand=brand, model=model, category="吸尘器", role=role,
        specs=spec_objs, certs=certs or [], scripts=scripts or {},
        endorsements=endorsements or [], intro=[], tests=tests or {})


def _scope(brand: str, model: str, role: str, **kw) -> ModelScope:
    return ModelScope(brand=brand, model=model, role=role,
                      memory=_mem(brand, model, role, **kw))


def test_pick_sellpoint_dims_one_variant_cap_three():
    scripts = {
        "动力系统": ["强劲吸力 A", "强劲吸力 B"],
        "过滤系统": ["HEPA A"],
        "防缠绕技术": ["防缠 A"],
        "噪音大小": ["静音 A"],
    }
    picked = _pick_sellpoint_dims(scripts)
    # 每维取第 1 变体，最多 3 维（插入序）
    assert picked == [
        ("动力系统", "强劲吸力 A"),
        ("过滤系统", "HEPA A"),
        ("防缠绕技术", "防缠 A"),
    ]


def test_pick_sellpoint_dims_empty_for_competitor():
    assert _pick_sellpoint_dims({}) == []


def test_model_label_brand_space_model():
    sc = _scope("CEWEY", "CEWEYDS18", "主推")
    assert _model_label(sc) == "CEWEY CEWEYDS18"


from csm_core.comparison.compose import _param_table


def test_param_table_union_columns_and_placeholder():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               specs={"吸力(AW)": "220", "转速": "12万转"})
    b = _scope("Dyson", "V12", "竞品",
               specs={"吸力(AW)": "150", "重量": "2.2kg"})
    out = _param_table([a, b])
    lines = out.splitlines()
    assert lines[0] == "## 参数对照"
    # 表头：参数 + 两个型号展示名
    assert lines[2] == "| 参数 | CEWEY CEWEYDS18 | Dyson V12 |"
    assert lines[3] == "| --- | --- | --- |"
    # 字段并集按首现序：吸力(AW)（a 有 b 有）、转速（a 有 b 无→—）、重量（a 无→—）
    assert "| 吸力(AW) | 220 | 150 |" in out
    assert "| 转速 | 12万转 | — |" in out
    assert "| 重量 | — | 2.2kg |" in out


def test_param_table_empty_when_no_specs():
    a = _scope("CEWEY", "CEWEYDS18", "主推")
    assert _param_table([a]) == ""


from csm_core.comparison.compose import _highlights, _test_comparison


def test_highlights_one_variant_cap3_plus_certs():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               scripts={"动力系统": ["强劲吸力"], "过滤系统": ["HEPA"],
                        "防缠绕技术": ["防缠"], "噪音大小": ["静音"]},
               certs=["CE", "FCC"])
    out = _highlights([a])
    assert out.startswith("## 各型号亮点")
    assert "### CEWEY CEWEYDS18" in out
    assert "- 动力系统：强劲吸力" in out
    assert "- 过滤系统：HEPA" in out
    assert "- 防缠绕技术：防缠" in out
    assert "噪音大小" not in out          # cap 3 维，第 4 维被截
    assert "- 认证：CE、FCC" in out


def test_highlights_omitted_when_no_scripts_no_certs():
    a = _scope("Dyson", "V12", "竞品")   # 竞品无 scripts、无 certs
    assert _highlights([a]) == ""


def test_test_comparison_common_topics_intersection_and_truncation():
    long_body = "噪音实测：" + "很安静" * 100     # >200 字
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               tests={"噪音测试": long_body, "尘杯测试": "0.6L"})
    b = _scope("Dyson", "V12", "竞品",
               tests={"噪音测试": "略吵", "续航测试": "60min"})
    out = _test_comparison([a, b])
    assert out.startswith("## 实测对比")
    assert "### 噪音测试" in out          # 共有话题
    assert "尘杯测试" not in out          # 非共有
    assert "续航测试" not in out
    # 主推正文截断到 200 字
    assert len([ln for ln in out.splitlines() if ln.startswith("- CEWEY CEWEYDS18：")][0]) <= 200 + len("- CEWEY CEWEYDS18：")


def test_test_comparison_omitted_when_no_common_topic():
    a = _scope("CEWEY", "CEWEYDS18", "主推", tests={"噪音测试": "安静"})
    b = _scope("Dyson", "V12", "竞品", tests={"续航测试": "60min"})
    assert _test_comparison([a, b]) == ""


from csm_core.comparison.compose import _summary, _leading_fields


def test_leading_fields_unique_or_numerically_distinct():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               specs={"吸力(AW)": "220", "转速": "12万转", "认证检测": "CE"})
    b = _scope("Dyson", "V12", "竞品",
               specs={"吸力(AW)": "150"})
    # 吸力 220≠150 → 领先项；转速 b 无 → 独有项；认证无数字 → 跳过
    fields = _leading_fields(a.memory.specs, [b.memory.specs])
    keys = [f for f, _ in fields]
    assert "吸力(AW)" in keys
    assert "转速" in keys
    assert "认证检测" not in keys


def test_summary_lists_endorsements_and_leading_neutral():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               specs={"吸力(AW)": "220"}, endorsements=["十年老牌"])
    b = _scope("Dyson", "V12", "竞品", specs={"吸力(AW)": "150"})
    out = _summary([a, b])
    assert out.startswith("## 总结")
    assert "- 十年老牌" in out
    assert "吸力(AW)" in out and "220" in out      # 事实陈列
    # 中性：不出现贬损/比较级断言词
    assert "秒杀" not in out and "碾压" not in out


def test_summary_empty_without_primary():
    b = _scope("Dyson", "V12", "竞品", specs={"吸力(AW)": "150"})
    assert _summary([b]) == ""
