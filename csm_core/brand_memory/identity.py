"""Resolve (品牌, 型号) from a 产品参数 filename stem + brand-alias folding.

The real vault has no 品牌/型号 frontmatter (only the filename), and brand
aliases differ between folder names and frontmatter (希喂 vs CEWEY). This
module is the single place that (a) folds an alias to its canonical brand
and (b) splits a stem like ``CEWEYDS18-产品参数`` into ("CEWEY", "DS18").
Seed alias table; Phase 0 taxonomy extends it.
"""
from __future__ import annotations

# canonical 品牌 -> 所有写法（含 canonical 自身）。
BRAND_ALIASES: dict[str, list[str]] = {
    "CEWEY": ["CEWEY", "希喂"],
    "小米": ["小米", "米家"],
    "戴森": ["戴森"],
    "追觅": ["追觅"],
    "美的": ["美的"],
    "海尔": ["海尔"],
    "石头": ["石头"],
    "松下": ["松下"],
    "苏泊尔": ["苏泊尔"],
    "德尔玛": ["德尔玛"],
    "小狗": ["小狗"],
    "友望": ["友望"],
    "京造": ["京造"],
}

_STEM_SUFFIXES = ("-产品参数", "-测试结果")


def canonical_brand(name: str, aliases: dict[str, list[str]] = BRAND_ALIASES) -> str:
    """Fold any alias to its canonical brand; unknown names pass through."""
    for canon, al in aliases.items():
        if name == canon or name in al:
            return canon
    return name


def parse_brand_model(
    stem: str, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> tuple[str, str] | None:
    """Split a product-note stem into (canonical_brand, model).

    Strips a trailing ``-产品参数`` / ``-测试结果``, then matches the longest
    known brand alias prefix. Returns ``None`` when no known brand prefixes
    the stem (caller adds it to a manual-review list).
    """
    name = stem
    for suffix in _STEM_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    flat = sorted(
        ((al, canon) for canon, als in aliases.items() for al in als),
        key=lambda t: len(t[0]), reverse=True,
    )
    for alias, canon in flat:
        if name.startswith(alias) and len(name) > len(alias):
            return canon, name[len(alias):]
    return None
