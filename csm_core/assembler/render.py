"""Render an AssemblyPlan to draft text — block dispatch + hero regions."""
from __future__ import annotations
import re
from .plan import AssemblyPlan, BlockResult, PickedVariant

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

_CN_DIGITS = "零一二三四五六七八九十"


def _format_index(i: int, style: str) -> str:
    """Return the numeric prefix for a list item (1-based)."""
    if style == "none":
        return ""
    if style == "1.":
        return f"{i}."
    if style == "一、":
        if 1 <= i <= 10:
            return f"{_CN_DIGITS[i]}、"
        if 11 <= i <= 19:
            return f"十{_CN_DIGITS[i - 10]}、"
        if 20 <= i <= 99:
            tens, ones = divmod(i, 10)
            if ones == 0:
                return f"{_CN_DIGITS[tens]}十、"
            return f"{_CN_DIGITS[tens]}十{_CN_DIGITS[ones]}、"
        return f"{i}、"
    return f"{i}."


def _substitute(text: str, variables: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        return variables.get(name, m.group(0))
    return _VAR_RE.sub(repl, text)


def _paragraph_text(r: BlockResult) -> str:
    """Flatten a paragraph result (including children) into a single text block."""
    parts = [p.text for p in r.picks]
    for c in r.children:
        if c.kind == "paragraph":
            ct = _paragraph_text(c)
            if ct:
                parts.append(ct)
    return "\n\n".join(parts)


def _numbered_list_text(r: BlockResult) -> str:
    style = r.meta.get("number_style", "1.")
    sep = r.meta.get("item_separator", "\n\n")
    # Chinese-style indices (e.g. "一、") include the separator character;
    # Arabic "1." style needs an explicit space after the dot.
    glue = "" if style == "一、" else " "
    items = [f"{_format_index(i + 1, style)}{glue}{p.text}".strip()
             for i, p in enumerate(r.picks)]
    return sep.join(items)


def compose_draft(plan: AssemblyPlan) -> str:
    """Render the plan to draft text.

    Region semantics: a `hero_brand` block opens a region. All
    subsequent paragraph / numbered_list block results until the next
    `competitor_pool`, the next `hero_brand`, or end of results are
    aggregated as the hero's reason body (each rendered normally, then
    joined with blank lines). The `competitor_pool` then appends its
    own items continuing the hero's numbering.
    """
    variables = {"keyword": plan.keyword}
    parts: list[str] = []
    i = 0
    while i < len(plan.results):
        r = plan.results[i]
        if r.kind == "hero_brand":
            chunk, i = _render_hero_region(plan.results, i, variables)
            if chunk:
                parts.append(chunk)
            continue
        if r.kind == "competitor_pool":
            parts.append(_render_competitor_pool(r, start_index=1))
            i += 1
            continue
        chunk = _render_standalone(r, variables)
        if chunk:
            parts.append(chunk)
        i += 1
    return "\n\n".join(p for p in parts if p)


def _render_standalone(r: BlockResult, variables: dict[str, str]) -> str:
    if r.kind == "heading":
        level = r.meta.get("level", 2)
        prefix = "#" * level
        idx = r.meta.get("index", "")
        text = _substitute(r.text, variables)
        return f"{prefix} {idx}、{text}" if idx else f"{prefix} {text}"
    if r.kind == "literal":
        return _substitute(r.text, variables)
    if r.kind == "paragraph":
        return _paragraph_text(r)
    if r.kind == "numbered_list":
        if not r.picks:
            return ""
        return _numbered_list_text(r)
    if r.kind == "hero_brand":
        return r.text
    return ""


def _render_hero_region(
    results: list[BlockResult], start: int, variables: dict[str, str],
) -> tuple[str, int]:
    hero = results[start]
    style = hero.meta.get("number_style", "1.")
    reason_label = hero.meta.get("reason_label", "推荐理由：")
    body_parts: list[str] = []
    j = start + 1
    pool_result: BlockResult | None = None
    while j < len(results):
        nxt = results[j]
        if nxt.kind == "competitor_pool":
            pool_result = nxt
            break
        if nxt.kind == "hero_brand":
            break
        if nxt.kind == "paragraph":
            body_parts.append(_paragraph_text(nxt))
        elif nxt.kind == "numbered_list" and nxt.picks:
            body_parts.append(_numbered_list_text(nxt))
        elif nxt.kind in ("heading", "literal"):
            body_parts.append(_render_standalone(nxt, variables))
        j += 1

    hero_title = _substitute(hero.text, variables)
    body = "\n\n".join(p for p in body_parts if p)
    if body:
        hero_chunk = f"{_format_index(1, style)} {hero_title}\n{reason_label}\n{body}"
    else:
        hero_chunk = f"{_format_index(1, style)} {hero_title}\n{reason_label}".rstrip()

    if pool_result is None:
        return hero_chunk, j

    pool_chunk = _render_competitor_pool(pool_result, start_index=2, style=style)
    return f"{hero_chunk}\n\n{pool_chunk}", j + 1


def _render_competitor_pool(
    r: BlockResult, *, start_index: int, style: str = "1.",
) -> str:
    label = r.meta.get("reason_label", "推荐理由：")
    items: list[str] = []
    for k, p in enumerate(r.picks):
        n = start_index + k
        title = p.meta.get("title") or p.note_id
        items.append(f"{_format_index(n, style)} {title}\n{label}{p.text}")
    return "\n\n".join(items)
