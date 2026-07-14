from csm_core.brand_memory.specs import parse_spec_table

BODY = """
## 性能参数

| 参数 | 数值 |
|------|------|
| 吸力(AW) | 220 |
| 真空度(Pa) | 0 |
| 最低噪音（dB） | 70dB |
| 电机功率 | 未说明 |

## 续航电池

| 参数 | 数值 |
|------|------|
| 不同档位续航 | 15/25/40min |

## 基础信息

| 参数 | 数值 |
|------|------|
| 认证检测 | CE、FCC、CB、3C |
"""


def test_parses_numeric_with_unit():
    specs = parse_spec_table(BODY)
    assert specs["吸力(AW)"].numbers == [220.0]
    assert specs["最低噪音（dB）"].numbers == [70.0]
    assert specs["最低噪音（dB）"].unit == "dB"


def test_range_value_yields_multiple_numbers():
    specs = parse_spec_table(BODY)
    assert specs["不同档位续航"].numbers == [15.0, 25.0, 40.0]
    assert specs["不同档位续航"].unit == "min"


def test_placeholder_and_zero_have_no_numbers():
    specs = parse_spec_table(BODY)
    # 占位/0 仍保留字段（供缺口体检），但 numbers 为空（不进白名单）。
    assert specs["真空度(Pa)"].numbers == []
    assert specs["电机功率"].numbers == []


def test_non_numeric_cell_kept_as_raw():
    specs = parse_spec_table(BODY)
    assert specs["认证检测"].raw == "CE、FCC、CB、3C"
    assert specs["认证检测"].numbers == []


def test_placeholder_flag_marks_gaps_not_certs():
    specs = parse_spec_table(BODY)
    # is_placeholder 供缺口体检：占位字段 True；有数值 / 认证名清单 False。
    assert specs["真空度(Pa)"].is_placeholder is True    # 0
    assert specs["电机功率"].is_placeholder is True        # 未说明
    assert specs["吸力(AW)"].is_placeholder is False       # 有数值
    assert specs["认证检测"].is_placeholder is False       # 认证名清单，非缺口


def test_section_retained_in_note_order():
    # 每字段记录所属 H2 小节名(原文),dict 插入序 = 笔记顺序(前端分组渲染依赖)。
    specs = parse_spec_table(BODY)
    assert specs["吸力(AW)"].section == "性能参数"
    assert specs["电机功率"].section == "性能参数"      # 占位字段也带 section
    assert specs["不同档位续航"].section == "续航电池"
    assert specs["认证检测"].section == "基础信息"      # 认证字段也带 section
    assert list(specs) == [
        "吸力(AW)", "真空度(Pa)", "最低噪音（dB）", "电机功率",
        "不同档位续航", "认证检测",
    ]
