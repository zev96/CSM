"""Sampler for ``TestFrameworkBlock``.

Workflow:
    1. List candidate framework notes from ``framework_module``.
    2. Pick ``pick_count`` of them (without replacement when
       ``unique_notes`` is on, which is the default).
    3. For each picked framework note:
        a. Extract the test topic from its frontmatter (``测试项``).
        b. Resolve the slot models — hero block produces 1 model,
           competitor pool produces N. The first goes to the hero slot,
           the rest to the competitor slots in declaration order.
        c. Look up each slot model's brand-result note (filtered by
           ``型号``). Inside that note, find the H2 section that matches
           the framework's test topic (see ``section_parser``).
        d. Replace the slot label lines (``主推 测试部分：``, etc.) in
           the framework note's raw body with ``{model} 测试部分：\\n
           {section body}``. Slot lines whose model is missing in the
           vault get a ``[缺数据：…]`` placeholder.
    4. Return the joined text of all picked + filled framework notes,
       separated by blank lines.
"""
from __future__ import annotations
import random
import re
from dataclasses import dataclass

from ..vault.scanner import VaultIndex
from ..vault.note_parser import VARIANT_MARKERS, ParsedNote
from .section_parser import (
    extract_brand_sections,
    find_section_for_topic,
)


# 文件名常见的"内容类型"前缀 — 显示标题时剥掉，让标题更干净。
# 例如 "云测-尘杯容量对比" → "尘杯容量对比"。
_FILENAME_PREFIX_RE = re.compile(r"^(?:云测|实测|测试|框架)\s*[-—–:：]\s*")

# 变体首行（"框架1 — 纯点评" / "噪音参数对比" 等）通常是个小标题，
# 我们会把它换成笔记文件名。判断标准：行不以下面这些"内容前缀"开头
# 就视为标签，剥掉。
_KEEP_LINE_PREFIXES = ("测试", "主推", "竞品", "排名", "数据")


def _derive_framework_title(note: ParsedNote) -> str:
    """从笔记文件名推导显示标题，去掉 ``云测-`` / ``实测-`` 等内容类型前缀。"""
    stem = note.path.stem if note.path else note.id
    return _FILENAME_PREFIX_RE.sub("", stem) or stem


def _strip_leading_label(body: str) -> str:
    """剥掉变体内容里的首行小标题（"框架1 — 纯点评" / 类似 H2 残留）。

    前提：变体的第一行如果不以 ``测试`` / ``主推`` / ``竞品`` / ``排名``
    这些"实际内容"关键词开头，就当作可剥的小标题处理。这样既能去掉
    框架编号又不会误删真正的正文。
    """
    lines = body.splitlines()
    # 跳过开头空行。
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return ""
    first = lines[i].strip()
    if first.startswith(_KEEP_LINE_PREFIXES):
        return "\n".join(lines[i:])
    # Treat as a label — drop the line + any blanks after it.
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    return "\n".join(lines[j:])


def _pick_framework_variant(note: ParsedNote, rng: random.Random) -> str:
    """从笔记的变体里随机选一个，剥掉首行标签后返回正文。

    笔记里若用 ①②③ 切分了多个框架变体，``note.variants`` 的第一项是
    标记前的"前言"内容（目录 / 大纲 / 一段引子），这里跳过；从真正的
    变体里抽。如果只有一个变体（无 ①②③），直接用它。
    """
    has_markers = any(m in (note.raw_body or "") for m in VARIANT_MARKERS)
    candidates: list[str]
    if has_markers and len(note.variants) > 1:
        candidates = note.variants[1:]   # 跳过前言
    elif note.variants:
        candidates = list(note.variants)
    else:
        candidates = [note.raw_body or ""]

    body = rng.choice(candidates) if candidates else ""
    return _strip_leading_label(body)


@dataclass
class TestFrameworkConfig:
    """Resolved config passed into the sampler — schema-agnostic so the
    function can also be exercised from tests without a Pydantic model."""
    # Pytest auto-collects classes starting with ``Test``; mark this one as
    # not-a-test so the runner skips it cleanly.
    __test__ = False

    framework_module: str
    results_module: str
    pick_count: int
    hero_slot: str = "主推"
    competitor_slots: tuple[str, ...] = ("竞品A", "竞品B")
    unique_notes: bool = True
    # 测试项之间的分隔符 — 用空行而不是 ``---``，避免被 markdown
    # 渲染成水平分隔线（H2 标题本身已经有视觉断点了）。
    section_separator: str = "\n\n"
    # 测试项编号样式："1."  →  "## 1. xxx"
    #                "一、" →  "## 一、xxx"
    #                "none" →  "## xxx"（无编号）
    number_style: str = "1."


# Identifies "X 测试部分：" lines in framework notes — X must match one of
# the configured slot labels exactly (we don't try to be clever, since
# false positives would silently corrupt user-edited prose).
def _slot_line_re(label: str) -> re.Pattern[str]:
    # Allow optional whitespace around the label and accept both Chinese
    # and ASCII colons. Word-boundary on the right is the colon, so we
    # don't need an explicit boundary regex for the label.
    return re.compile(
        r"^(\s*)" + re.escape(label) + r"\s*测试部分\s*[：:]\s*$",
        re.MULTILINE,
    )


def _inline_label_re(label: str) -> re.Pattern[str]:
    """Match standalone references to *label* in regular prose.

    Hits "测试排名：主推 > 竞品A > 竞品B" etc., but skips word-internal
    occurrences like "主推方案" — we use a negative lookahead that
    rejects a following Chinese character or alphanumeric. The label
    must also NOT be followed by " 测试部分" (which is the slot-line
    form, handled separately and already replaced by the time this regex
    runs).
    """
    return re.compile(
        re.escape(label)
        + r"(?!\s*测试部分)"          # not the slot line
        + r"(?![\w一-鿿])",   # not part of a longer CJK / latin word
    )


# CJK numerals for the ``一、`` style — covers 1..20 which is plenty for
# any realistic 测试项 list.
_CN_DIGITS = "零一二三四五六七八九十"


def _format_test_index(i: int, style: str) -> str:
    """Return a heading-prefix for the i-th test item (1-indexed).

    >>> _format_test_index(1, "1.")
    '1.'
    >>> _format_test_index(3, "一、")
    '三、'
    >>> _format_test_index(2, "none")
    ''
    """
    if style == "none":
        return ""
    if style == "一、":
        if 1 <= i <= 10:
            return f"{_CN_DIGITS[i]}、"
        if 10 < i < 20:
            return f"十{_CN_DIGITS[i - 10]}、"
        if i == 20:
            return "二十、"
        # Beyond 20 fall back to arabic — extremely unlikely in practice.
        return f"{i}、"
    # Default arabic style "1."
    return f"{i}."


def _fill_one_framework(
    framework: ParsedNote,
    *,
    cfg: TestFrameworkConfig,
    slot_models: dict[str, str],
    vault: VaultIndex,
    brand_of: callable,
    rng: random.Random,
    index: int = 1,
) -> str:
    """Fill the slot lines in a randomly picked variant from *framework*.

    Steps:
        1. 从 ``framework.variants`` 随机抽一个（多框架笔记里 ①②③ 是
           不同框架变体，每篇文章只用其中一个）。
        2. 剥掉变体首行的"框架1 — 纯点评" / 残留 H2 之类的小标题。
        3. 把 ``主推 测试部分：`` / ``竞品A 测试部分：`` / ``竞品B 测试
           部分：`` 三种行替换为对应产品的实际段落。
        4. 把行内独立出现的 "主推" / "竞品A" / "竞品B"（如 "测试排名：
           主推 > 竞品A > 竞品B"）也替换成对应产品名。
        5. 在最前面加一个 ``## {序号} {笔记文件名}`` 作为该测试项的总标题。
    """
    topic = (framework.frontmatter.get("测试项") or "").strip()
    title = _derive_framework_title(framework)
    text = _pick_framework_variant(framework, rng)

    for label, model in slot_models.items():
        if not model:
            replacement = f"{label} 测试部分：\n[缺数据：未选中产品]"
        else:
            section_body = _lookup_brand_section(
                model=model, topic=topic,
                results_module=cfg.results_module,
                vault=vault,
            )
            if section_body is None:
                replacement = (
                    f"{model} 测试部分：\n[缺数据：{model} {topic or '此测试项'}]"
                )
            else:
                replacement = f"{model} 测试部分：\n{section_body}"

        # Preserve the leading whitespace of the original label line so
        # nested-list indentation (rare but possible) survives.
        def repl(m: re.Match[str], rep=replacement) -> str:
            return f"{m.group(1)}{rep}"

        text = _slot_line_re(label).sub(repl, text, count=1)

    # Inline label substitution — replace standalone "主推" / "竞品A" /
    # "竞品B" tokens elsewhere in the body (e.g. "测试排名：主推 > 竞品A
    # > 竞品B") with the corresponding model names. This must run AFTER
    # the slot-line replacement so we don't accidentally rewrite the
    # slot-line label before its anchored match has fired.
    for label, model in slot_models.items():
        if model:
            text = _inline_label_re(label).sub(model, text)

    # Prepend the H2 — "## {1.|一、|} {笔记文件名}". Empty body falls back
    # to just the heading line (defensive — shouldn't happen for any real
    # framework note).
    prefix = _format_test_index(index, cfg.number_style)
    head = f"## {prefix} {title}".strip() if prefix else f"## {title}"
    text = text.lstrip("\n")
    if text:
        return f"{head}\n\n{text}"
    return head


# 品牌 section 正文前缀 — 用户写笔记时常加 "测试结果：" / "实测数据：" 之类的标签，
# 但渲染到文章里时只要后面的实际内容；这里把开头的标签连冒号一并剥掉。
# 全角冒号 (：) 和 ASCII 冒号 (:) 都支持。
_RESULT_PREFIX_RE = re.compile(
    r"^\s*(?:测试结果|实测结果|实测数据|测试数据|结果|数据)\s*[：:]\s*",
)

# 水平分隔线 — 防御性兜底（section_parser 已经过滤了，这里再扫一遍）。
_HR_LINE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


def _lookup_brand_section(
    *, model: str, topic: str,
    results_module: str, vault: VaultIndex,
) -> str | None:
    """Return the matching H2 section's body for *model* / *topic*.

    The leading ``测试结果：`` (or similar) label is stripped from the
    body so the rendered output reads "{品牌} 测试部分：{实际内容}"
    instead of "{品牌} 测试部分：测试结果：{实际内容}" — the slot line
    already supplies the "测试部分：" prefix, so duplicating it via the
    section body is just visual noise.

    Returns None when:
        - No brand note for the model exists in ``results_module``
        - The note exists but has no section matching ``topic``
    """
    matches = vault.query(
        module=results_module, filters={"型号": model},
    )
    if not matches:
        return None
    note = matches[0]  # 同一个型号在 results_module 下只该有一篇笔记
    sections = extract_brand_sections(note.raw_body)
    found = find_section_for_topic(sections, topic)
    if not (found and found.body):
        return None
    body = _RESULT_PREFIX_RE.sub("", found.body, count=1)
    # Defensive — strip any remaining horizontal-rule lines so they
    # can't render as ``<hr>`` or accidentally turn the next slot label
    # into a setext-style H2 (which would bold "米家3C 测试部分：" via
    # "preceding text + --- = heading" markdown rule).
    body = "\n".join(
        line for line in body.splitlines() if not _HR_LINE_RE.match(line)
    )
    return body


def sample_test_framework_block(
    *,
    cfg: TestFrameworkConfig,
    follow_models: list[str],
    vault: VaultIndex,
    brand_of: callable,
    rng: random.Random,
) -> tuple[str, list[str]]:
    """Pick frameworks + fill brand slots, return ``(text, warnings)``.

    ``follow_models`` is the ordered list of product models the upstream
    hero+pool produced (length = 1 hero + N competitors). The hero slot
    gets the first model; competitor slots are filled in order, padding
    with empty strings if the pool produced fewer than configured.
    """
    warnings: list[str] = []

    candidates = vault.by_module(cfg.framework_module)
    candidates = [n for n in candidates if (n.frontmatter.get("测试项") or "").strip()]
    if not candidates:
        warnings.append(
            f"test_framework: 框架目录 {cfg.framework_module!r} 下没有任何带 "
            f"`测试项` frontmatter 的笔记"
        )
        return "", warnings

    n_wanted = max(1, int(cfg.pick_count))
    if cfg.unique_notes:
        if n_wanted > len(candidates):
            warnings.append(
                f"test_framework: 请求 {n_wanted} 个测试项，但框架目录只有 "
                f"{len(candidates)} 个，已降级为全部"
            )
            n_wanted = len(candidates)
        picked = rng.sample(candidates, n_wanted)
    else:
        picked = [rng.choice(candidates) for _ in range(n_wanted)]

    # Build the slot → model mapping from follow_models.
    slot_models: dict[str, str] = {}
    if follow_models:
        slot_models[cfg.hero_slot] = follow_models[0]
    else:
        slot_models[cfg.hero_slot] = ""
    for i, slot in enumerate(cfg.competitor_slots):
        slot_models[slot] = follow_models[i + 1] if i + 1 < len(follow_models) else ""

    chunks: list[str] = []
    for i, fw in enumerate(picked, start=1):
        filled = _fill_one_framework(
            fw, cfg=cfg, slot_models=slot_models,
            vault=vault, brand_of=brand_of, rng=rng, index=i,
        )
        if filled.strip():
            chunks.append(filled)

    return cfg.section_separator.join(chunks), warnings
