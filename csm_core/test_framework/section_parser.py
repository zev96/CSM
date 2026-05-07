"""Parse a brand-result note into per-test-topic H2 sections.

Brand notes in the vault look like::

    ---
    型号: 戴森V8
    素材类型: 测试数据
    ---

    ## 云测1：吸力测试

    测试结果：……

    ## 云测2：尘杯测试

    测试结果：……

    ## 实测1：常见干垃圾测试

    测试结果：……

This module splits the body on H2 headings, normalizes the heading text by
stripping numbered prefixes like ``云测1：`` / ``实测2：``, and exposes
:func:`find_section_for_topic` for the test-framework sampler to look up
"this brand's section for the noise test" without coupling to exact
heading wording.

Matching is forgiving — a framework note's ``测试项: 噪音`` will match a
brand H2 ``## 云测3：噪音控制`` via a substring check after prefix
stripping. This is intentionally lax so users don't have to keep the two
spellings perfectly synchronised.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# Numbered prefixes that the matcher peels off the H2 title before
# comparing to the framework's ``测试项`` value. The match is case-
# insensitive on the alphabetic part; CJK is exact. Order doesn't matter
# (we apply them as a single regex alternation).
NORMALIZED_PREFIXES: tuple[str, ...] = (
    r"云测",
    r"实测",
    r"测试",
)

_PREFIX_RE = re.compile(
    r"^\s*(?:" + "|".join(NORMALIZED_PREFIXES) + r")\s*\d*\s*[：:]?\s*",
)
_H2_LINE_RE = re.compile(r"^\s*##\s+(.+?)\s*$")

# Markdown 水平分隔线（``---`` / ``***`` / ``___``）。Obsidian 用户经常
# 在笔记里用 ``---`` 当章节视觉分隔符；它们一旦留在 section body 里再
# 拼到模板段落里，会被 markdown 渲染成 ``<hr>`` —— 更糟的是，紧跟着的
# "米家3C 测试部分：" 会被当作 setext-style H2（前一行文本 + 下一行
# `---` = 标题）整行加粗。所以从 section body 里把这些线都清掉。
_HR_LINE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


@dataclass
class BrandSection:
    """A single H2 section pulled out of a brand-result note."""

    raw_title: str       # 原始 H2 文本，比如 "云测1：噪音测试"
    normalized_title: str  # 规范化后的标题，比如 "噪音测试"
    body: str             # 该 section 下的正文（不含 H2 行本身）


def normalize_section_title(title: str) -> str:
    """Strip numbered prefixes (云测N：/实测N：/测试N：) from *title*.

    >>> normalize_section_title("云测1：吸力测试")
    '吸力测试'
    >>> normalize_section_title("实测3：常见干垃圾测试")
    '常见干垃圾测试'
    >>> normalize_section_title("噪音对比")
    '噪音对比'
    """
    if not title:
        return ""
    return _PREFIX_RE.sub("", title).strip()


def extract_brand_sections(body: str) -> list[BrandSection]:
    """Split a brand-result note's body into H2 sections.

    Anything before the first H2 (frontmatter is already stripped by the
    upstream parser) is silently dropped — those notes are expected to
    consist entirely of H2 sections. Empty sections (heading with no body)
    are kept so the matcher can report them as "found but empty".
    """
    if not body:
        return []
    lines = body.splitlines()
    sections: list[BrandSection] = []
    current_title: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        if current_title is None:
            return
        # Drop horizontal-rule lines anywhere in the section body. Users
        # often use ``---`` as a visual separator inside Obsidian; we
        # don't want those to leak into the rendered article.
        cleaned = [ln for ln in current_body if not _HR_LINE_RE.match(ln)]
        body_text = "\n".join(cleaned).strip()
        sections.append(BrandSection(
            raw_title=current_title,
            normalized_title=normalize_section_title(current_title),
            body=body_text,
        ))

    for line in lines:
        m = _H2_LINE_RE.match(line)
        if m:
            flush()
            current_title = m.group(1)
            current_body = []
        else:
            if current_title is not None:
                current_body.append(line)
            # Lines before the first H2 are dropped (frontmatter / preamble).
    flush()
    return sections


def find_section_for_topic(
    sections: list[BrandSection], topic: str,
) -> BrandSection | None:
    """Find the section whose normalized title matches *topic*.

    Match strategy (in order):
        1. Exact match of normalized title to ``topic``
        2. Topic is a substring of normalized title (e.g. "噪音" → "噪音测试")
        3. Normalized title is a substring of topic (e.g. "噪音" → "噪音对比")
        4. None — caller decides whether to render placeholder or skip

    The first match wins. If two sections match equally well, the earlier
    one in the note is preferred (gives the user predictable ordering).
    """
    if not topic or not sections:
        return None
    topic = topic.strip()

    # Pass 1: exact normalized match.
    for s in sections:
        if s.normalized_title == topic:
            return s

    # Pass 2: topic ⊂ normalized title.
    for s in sections:
        if topic in s.normalized_title:
            return s

    # Pass 3: normalized title ⊂ topic.
    for s in sections:
        if s.normalized_title and s.normalized_title in topic:
            return s

    return None
