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


def _append_keyword(title: str, keyword: str) -> str:
    """Append the product keyword to a brand/model title for display.

    Users write titles like "CEWEY DS18" or "米家3基站版" — the keyword
    ("无线吸尘器") is tacked on at render time so the template doesn't have
    to duplicate it. If the title already ends with the keyword (legacy
    templates or notes that include it), skip appending to avoid
    duplication.
    """
    if not keyword:
        return title
    if title.endswith(keyword):
        return title
    return f"{title}{keyword}"


def _paragraph_text(r: BlockResult) -> str:
    """Flatten a paragraph result (including children) into a single text block."""
    parts = [p.text for p in r.picks]
    for c in r.children:
        if c.kind == "paragraph":
            ct = _paragraph_text(c)
            if ct:
                parts.append(ct)
    return "\n\n".join(parts)


def _prefix_join(i: int, style: str, text: str) -> str:
    """Join a formatted index with text, handling style-specific spacing.

    Chinese-style indices (e.g. "一、") include the separator character;
    Arabic "1." style needs an explicit space. Returns empty-style text unchanged.
    """
    pfx = _format_index(i, style)
    if not pfx:
        return text
    glue = "" if style == "一、" else " "
    return f"{pfx}{glue}{text}"


def _numbered_list_text(r: BlockResult) -> str:
    style = r.meta.get("number_style", "1.")
    sep = r.meta.get("item_separator", "\n\n")
    items = [_prefix_join(i + 1, style, p.text).strip()
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

    Variable substitution
    ---------------------
    ``{keyword}``         → core product term (e.g. "无线吸尘器")
                            — what you almost always want in a body
                            block. Default for legacy templates.
    ``{search_keyword}``  → full long-tail keyword (e.g. "无线吸尘器
                            哪款好用") — only used by templates that
                            want to mirror the user's exact search query.
    """
    core = plan.get_core_keyword()
    variables = {
        "keyword": core,
        "search_keyword": plan.keyword,
    }
    parts: list[str] = []
    i = 0
    while i < len(plan.results):
        r = plan.results[i]
        if r.meta.get("card") and r.kind in ("hero_brand", "competitor_pool"):
            chunk, i = _render_card_region(plan.results, i, variables)
            if chunk:
                parts.append(chunk)
            continue
        if r.kind == "hero_brand":
            chunk, i = _render_hero_region(plan.results, i, variables)
            if chunk:
                parts.append(chunk)
            continue
        if r.kind == "competitor_pool":
            # Use core keyword so brand titles read "CEWEY DS18 无线吸尘器"
            # rather than "CEWEY DS18 无线吸尘器哪款好用".
            parts.append(_render_competitor_pool(
                r, start_index=1, keyword=core,
            ))
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
    if r.kind == "test_framework":
        # Sampler已经把所有槽位都填好了。变量替换走一道，让 {keyword}
        # 等占位符在框架原理/方法描述里也能正常展开。
        return _substitute(r.text or "", variables)
    return ""


# ── 榜单卡片 ──────────────────────────────────────────────────────────
def _card_heading(
    template: str, *, n: int, title: str, tier: str,
    brand: str, model: str, variables: dict[str, str],
) -> str:
    """渲染卡片标题行。

    ``{title}`` 卡片模式**不**追加产品关键词 —— 用户范文是「TOP2. 欧瑞达
    X9」而不是「欧瑞达 X9 空气净化器」。要追加用 ``{title_kw}``。
    多余空格收掉（tier 为空时 "### {tier} TOP1." 会留下双空格）。
    """
    keyword = variables.get("keyword", "")
    text = _substitute(template, {
        **variables,
        "n": str(n), "title": title, "tier": tier,
        "brand": brand, "model": model,
        "title_kw": _append_keyword(title, keyword),
    })
    return re.sub(r"[ \t]{2,}", " ", text).replace(" \n", "\n").strip()


def _render_card_sections(
    picks: list[PickedVariant], layout: str,
) -> str:
    """把打平的 picks 按 section 顺序拼成加粗小节。

    同一个 section 的多个 pick（``pick_variants`` > 1 或多篇笔记）合成一
    段一段；section_label 为空表示「续段」——只出正文不出标题，用来把
    「分维度硬核测评」这样的点拆成多段。
    """
    chunks: list[str] = []
    current_index: int | None = None
    for p in picks:
        idx = p.meta.get("section_index")
        label = str(p.meta.get("section_label") or "")
        text = (p.text or "").strip()
        if not text:
            continue
        new_section = idx != current_index
        current_index = idx
        if label and new_section:
            if layout == "line":
                chunks.append(f"**{label}**\n{text}")
            else:
                chunks.append(f"**{label}** ：{text}")
        else:
            chunks.append(text)
    return "\n\n".join(chunks)


def _render_hero_card(r: BlockResult, n: int, variables: dict[str, str]) -> str:
    keyword = variables.get("keyword", "")
    title = _substitute(r.text or "", variables).strip()
    heading = _card_heading(
        r.meta.get("heading_template", "### {tier} TOP{n}. {title}"),
        n=n, title=title, tier=str(r.meta.get("tier") or ""),
        brand="", model=title, variables=variables,
    )
    body = _render_card_sections(r.picks, r.meta.get("label_layout", "inline"))
    return f"{heading}\n\n{body}" if body else heading


def _render_competitor_cards(
    r: BlockResult, start_index: int, variables: dict[str, str],
) -> tuple[str, int]:
    """渲染一个卡片竞品池，返回 (文本, 下一个可用排位)。"""
    keyword = variables.get("keyword", "")
    layout = r.meta.get("label_layout", "inline")
    sep = r.meta.get("card_separator", "\n\n")
    tmpl = r.meta.get("heading_template", "### {tier} TOP{n}. {title}")

    grouped: list[tuple[str, list[PickedVariant]]] = []
    for p in r.picks:
        key = str(p.meta.get("competitor_key") or p.note_id)
        if not grouped or grouped[-1][0] != key:
            grouped.append((key, []))
        grouped[-1][1].append(p)

    cards: list[str] = []
    n = start_index
    for _, picks in grouped:
        head = picks[0].meta
        heading = _card_heading(
            tmpl, n=n,
            title=str(head.get("title") or ""),
            tier=str(head.get("tier") or ""),
            brand=str(head.get("brand") or ""),
            model=str(head.get("model") or ""),
            variables=variables,
        )
        body = _render_card_sections(picks, layout)
        cards.append(f"{heading}\n\n{body}" if body else heading)
        n += 1
    return sep.join(cards), n


def _render_card_region(
    results: list[BlockResult], start: int, variables: dict[str, str],
) -> tuple[str, int]:
    """卡片榜单区：主推卡 = TOP1，后续卡片池连续编号。

    区域语法 ``hero卡 → (literal)* → 竞品卡池+``：允许一个区里放多个池
    （TOP2-3 深结构池 + TOP4-10 浅结构池），后池排位接着前池数。遇到别的
    块类型（标题/段落/新的 hero）就收尾 —— 编号计数器绝不跨区泄漏。
    跨池竞品去重已在采样期完成，这里只管排版。
    """
    parts: list[str] = []
    n = 1
    i = start
    first = results[start]
    if first.kind == "hero_brand":
        parts.append(_render_hero_card(first, n, variables))
        n += 1
        i += 1
    while i < len(results):
        nxt = results[i]
        if nxt.kind == "competitor_pool" and nxt.meta.get("card"):
            chunk, n = _render_competitor_cards(nxt, n, variables)
            if chunk:
                parts.append(chunk)
            i += 1
            continue
        if nxt.kind == "literal":
            parts.append(_render_standalone(nxt, variables))
            i += 1
            continue
        break
    return "\n\n".join(p for p in parts if p), i


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

    keyword = variables.get("keyword", "")
    hero_title = _append_keyword(_substitute(hero.text, variables), keyword)
    body = "\n\n".join(p for p in body_parts if p)
    # Blank line between title and 推荐理由 so markdown renders them as
    # separate paragraphs (single \n would collapse into one line).
    if body:
        hero_chunk = f"{_prefix_join(1, style, hero_title)}\n\n{reason_label}\n{body}"
    else:
        hero_chunk = f"{_prefix_join(1, style, hero_title)}\n\n{reason_label}".rstrip()

    if pool_result is None:
        return hero_chunk, j

    # competitor_pool inherits the preceding hero's reason_label (and style)
    # so the user doesn't have to configure it twice.
    pool_chunk = _render_competitor_pool(
        pool_result, start_index=2, style=style,
        reason_label=reason_label, keyword=keyword,
    )
    return f"{hero_chunk}\n\n{pool_chunk}", j + 1


def _render_competitor_pool(
    r: BlockResult, *, start_index: int, style: str = "1.",
    reason_label: str | None = None, keyword: str = "",
) -> str:
    # When rendered as part of a hero region, the caller passes the hero's
    # reason_label; standalone pools fall back to the pool's own meta.
    label = reason_label if reason_label is not None else r.meta.get(
        "reason_label", "推荐理由：",
    )
    items: list[str] = []
    for k, p in enumerate(r.picks):
        n = start_index + k
        title = p.meta.get("title") or p.note_id
        title = _append_keyword(title, keyword)
        # Blank line so markdown keeps title and 推荐理由 on separate lines.
        items.append(f"{_prefix_join(n, style, title)}\n\n{label}{p.text}")
    return "\n\n".join(items)
