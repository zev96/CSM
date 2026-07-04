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


def compose_comparison_draft(
    scopes: list[ModelScope], *, keyword: str, title: str | None,
) -> str:
    """占位：Task A2–A5 逐段填充。"""
    raise NotImplementedError
