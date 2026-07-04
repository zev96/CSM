"""横评确定性骨架 —— 从 list[ModelScope] 拼多型号对比文章，全部来自 memory
对象、零 LLM。段落：引言 / 参数对照表 / 各型号亮点 / 实测对比 / 总结。"""
from __future__ import annotations

from csm_core.brand_memory.inject import ModelScope

_MAX_TEST_CHARS = 200
_DIM_CAP = 3


def _model_label(sc: ModelScope) -> str:
    """展示名 = 品牌 + 型号全名（memory.model 是剥品牌短名，不用于展示）。"""
    return f"{sc.brand} {sc.model}".strip()


def _pick_sellpoint_dims(
    scripts: dict[str, list[str]], *, dim_cap: int = _DIM_CAP,
) -> list[tuple[str, str]]:
    """每维取第 1 变体，最多 dim_cap 维（插入序稳定）。竞品 scripts={} → []。"""
    out: list[tuple[str, str]] = []
    for dim, variants in scripts.items():
        if variants:
            out.append((dim, variants[0]))
        if len(out) >= dim_cap:
            break
    return out


def _is_numeric_field(f: str, scopes: list[ModelScope]) -> bool:
    """任一型号该字段为真·数值（有 numbers 且非占位）→ 数字型字段。"""
    for sc in scopes:
        sv = sc.memory.specs.get(f)
        if sv is not None and sv.numbers and not sv.is_placeholder:
            return True
    return False


def _param_table(scopes: list[ModelScope]) -> str:
    """字段并集 × 型号列 markdown 表：数字型字段在前（各按并集首现序），
    非数值/认证在后；缺失或占位单元格填 —（spec §5.1）。"""
    fields: list[str] = []
    seen: set[str] = set()
    for sc in scopes:
        for f in sc.memory.specs.keys():
            if f not in seen:
                seen.add(f)
                fields.append(f)
    if not fields:
        return ""
    # 数字型在前、非数值在后，各自保持并集首现序。
    fields = [f for f in fields if _is_numeric_field(f, scopes)] + \
             [f for f in fields if not _is_numeric_field(f, scopes)]
    labels = [_model_label(sc) for sc in scopes]
    header = "| 参数 | " + " | ".join(labels) + " |"
    sep = "| --- | " + " | ".join("---" for _ in scopes) + " |"
    rows = [header, sep]
    for f in fields:
        cells = []
        for sc in scopes:
            sv = sc.memory.specs.get(f)
            # 缺失（None）或占位（is_placeholder）都填 —，不把占位当真值印进表。
            cells.append("—" if (sv is None or sv.is_placeholder) else sv.raw)
        rows.append(f"| {f} | " + " | ".join(cells) + " |")
    return "## 参数对照\n\n" + "\n".join(rows)


def _highlights(scopes: list[ModelScope]) -> str:
    """每型号一块：卖点话术（每维 1 变体、≤3 维）+ 认证行。空块（无卖点无认证）跳过。"""
    blocks: list[str] = []
    for sc in scopes:
        m = sc.memory
        lines = [f"### {_model_label(sc)}"]
        for dim, variant in _pick_sellpoint_dims(m.scripts):
            lines.append(f"- {dim}：{variant}")
        if m.certs:
            lines.append(f"- 认证：{'、'.join(m.certs)}")
        if len(lines) > 1:                       # 有内容才收
            blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return "## 各型号亮点\n\n" + "\n\n".join(blocks)


def _test_comparison(scopes: list[ModelScope]) -> str:
    """共有测试话题（有 tests 的型号取 keys 交集，≥2 个型号才成立）逐话题
    各型号摘要（每型号 ≤200 字）；无共有话题 → 整节省略。"""
    with_tests = [sc for sc in scopes if sc.memory.tests]
    if len(with_tests) < 2:
        return ""
    common = set(with_tests[0].memory.tests.keys())
    for sc in with_tests[1:]:
        common &= set(sc.memory.tests.keys())
    if not common:
        return ""
    ordered = [t for t in with_tests[0].memory.tests.keys() if t in common]
    blocks: list[str] = []
    for topic in ordered:
        lines = [f"### {topic}"]
        for sc in with_tests:
            body = (sc.memory.tests.get(topic) or "").strip()
            if body:
                lines.append(f"- {_model_label(sc)}：{body[:_MAX_TEST_CHARS]}")
        blocks.append("\n".join(lines))
    return "## 实测对比\n\n" + "\n\n".join(blocks)


def _leading_fields(
    primary_specs: dict, competitor_specs: list[dict],
) -> list[tuple[str, str]]:
    """主推「独有或数值有别」的数值型 spec 字段（中性事实，不判方向优劣）。

    - 只看有 numbers 的字段（认证/占位跳过）；
    - 竞品都没这个字段 → 独有，收；
    - 竞品有但主推 max 与每个竞品 max 都不等 → 数值有别，收。"""
    out: list[tuple[str, str]] = []
    for field, sv in primary_specs.items():
        if not sv.numbers:
            continue
        comp_nums = [
            cs[field].numbers for cs in competitor_specs
            if field in cs and cs[field].numbers
        ]
        p_max = max(sv.numbers)
        if not comp_nums:
            out.append((field, sv.raw))
        elif all(p_max != max(cn) for cn in comp_nums):
            out.append((field, sv.raw))
    return out


def _summary(scopes: list[ModelScope]) -> str:
    """主推型号背书（按品牌去重）+ 事实领先/独有 spec 陈列（中性）。无主推 → 空。

    「突出主推优势」的价值判断留给 LLM 润色的对比指令块；本节只陈列事实。"""
    primary = [sc for sc in scopes if sc.role == "主推"]
    if not primary:
        return ""
    competitor_specs = [sc.memory.specs for sc in scopes if sc.role != "主推"]
    lines = ["## 总结"]
    seen_brand: set[str] = set()
    for sc in primary:
        if sc.brand in seen_brand:
            continue
        seen_brand.add(sc.brand)
        for e in sc.memory.endorsements:
            lines.append(f"- {e}")
    for sc in primary:
        for field, raw in _leading_fields(sc.memory.specs, competitor_specs):
            lines.append(f"- {_model_label(sc)} 的 {field}：{raw}")
    # 无背书且无领先项 → 只剩裸标题，整节省略（同 highlights/test 的空节策略）。
    return "\n".join(lines) if len(lines) > 1 else ""


def _intro(scopes: list[ModelScope], keyword: str, title: str | None) -> str:
    names = "、".join(_model_label(sc) for sc in scopes)
    kw = keyword.strip() or "这几款产品"
    lead = f"{kw}？本文把 {names} 放在一起，从参数、亮点到实测逐项对比。"
    if title:
        return f"# {title}\n\n{lead}"
    return lead


def compose_comparison_draft(
    scopes: list[ModelScope], *, keyword: str, title: str | None,
) -> str:
    """多型号对比文章骨架（零 LLM）。空节自动省略。空 scopes → 空串。"""
    if not scopes:
        return ""
    parts = [
        _intro(scopes, keyword, title),
        _param_table(scopes),
        _highlights(scopes),
        _test_comparison(scopes),
        _summary(scopes),
    ]
    return "\n\n".join(p for p in parts if p)
