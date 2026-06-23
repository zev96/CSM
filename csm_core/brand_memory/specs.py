"""Parse a 产品参数 note body into ``{字段: SpecValue}``.

产品参数 notes are H2 sections (## 性能参数 …) each holding a two-column
markdown table ``| 参数 | 数值 |``. We reuse the test_framework H2 splitter
then parse each table row. Placeholder cells (未说明/-/无/暂无/0) are kept
as fields (so 缺口体检 can flag them) but yield no numbers (so they never
enter the fact whitelist). The 认证检测 row is a cert-name list (CE、3C…),
not a measurement, so it is kept raw with no numbers — its certs are
extracted separately by the resolver (see resolver._certs_from_specs, which
uses the same ``"认证" in field`` predicate).
"""
from __future__ import annotations
import re
from csm_core.test_framework.section_parser import extract_brand_sections
from .model import SpecValue

_ROW_RE = re.compile(r"^\s*\|(.+?)\|(.+?)\|\s*$")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_SEP_CELL_RE = re.compile(r"^[\s\-:]+$")           # 表头分隔行 |---|---|
_APPROX = ("约", "近", "≤", "<", "＜", "≥", "＞", ">", "起", "最高", "最低")
_PLACEHOLDERS = {"", "-", "无", "未说明", "暂无", "暂无数据", "/", "0"}


def _is_placeholder(value: str) -> bool:
    return value.strip() in _PLACEHOLDERS


def _is_cert_field(field: str) -> bool:
    # 认证检测 等认证字段是认证名清单（含 3C 这类数字+字母的标准代号），
    # 不是可量化的数值规格 → 不抽数字，避免把 "3C" 的 3 误当事实。
    return "认证" in field


def _extract_unit(value: str) -> str:
    # 去掉数字、分隔符、近似号，剩下的尾部当单位（启发式，够用即可）。
    tail = _NUM_RE.sub("", value)
    tail = re.sub(r"[\s/|、,，~\-±:：()（）]", "", tail)
    for mark in _APPROX:
        tail = tail.replace(mark, "")
    return tail.strip()


def parse_spec_table(body: str) -> dict[str, SpecValue]:
    specs: dict[str, SpecValue] = {}
    for section in extract_brand_sections(body):
        for line in section.body.splitlines():
            m = _ROW_RE.match(line)
            if not m:
                continue
            field, value = m.group(1).strip(), m.group(2).strip()
            if not field or field == "参数" or _SEP_CELL_RE.match(field):
                continue
            # 占位/0 与认证字段：保留字段（供缺口体检 / certs 抽取）但不出数字。
            if _is_placeholder(value) or _is_cert_field(field):
                specs[field] = SpecValue(field=field, raw=value)
                continue
            numbers = [float(n) for n in _NUM_RE.findall(value)]
            specs[field] = SpecValue(
                field=field, raw=value, numbers=numbers,
                unit=_extract_unit(value),
                is_approx=any(mark in value for mark in _APPROX),
            )
    return specs
