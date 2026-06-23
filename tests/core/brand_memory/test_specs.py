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
