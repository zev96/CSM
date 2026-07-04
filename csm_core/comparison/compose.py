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


def _param_table(scopes: list[ModelScope]) -> str:
    """字段并集（按各型号插入序首现）× 型号列 markdown 表；缺失填 —。"""
    fields: list[str] = []
    seen: set[str] = set()
    for sc in scopes:
        for f in sc.memory.specs.keys():
            if f not in seen:
                seen.add(f)
                fields.append(f)
    if not fields:
        return ""
    labels = [_model_label(sc) for sc in scopes]
    header = "| 参数 | " + " | ".join(labels) + " |"
    sep = "| --- | " + " | ".join("---" for _ in scopes) + " |"
    rows = [header, sep]
    for f in fields:
        cells = []
        for sc in scopes:
            sv = sc.memory.specs.get(f)
            cells.append(sv.raw if sv is not None else "—")
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


def compose_comparison_draft(
    scopes: list[ModelScope], *, keyword: str, title: str | None,
) -> str:
    """占位：Task A2–A5 逐段填充。"""
    raise NotImplementedError
