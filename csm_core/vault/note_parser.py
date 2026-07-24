"""Parse a single Obsidian markdown note into frontmatter + variant sections."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re
import frontmatter

# Circled numbers ①–⑳ (U+2460–U+2473). Notes in the vault occasionally run
# past 9 variants (挑选攻略-style lists with 10+ bullets), so the regex must
# cover ⑩⑪⑫…⑳ too — otherwise variant 9 absorbs everything from ⑩ onward
# into its body. 20 variants is plenty for any realistic note.
VARIANT_MARKERS = tuple(chr(c) for c in range(0x2460, 0x2474))
_CIRCLED_CLASS = "[\u2460-\u2473]"
# Match a variant marker at the start of a line, tolerating leading whitespace
# and an optional ATX heading prefix (``### ① ...``) so heading-wrapped
# markers are stripped along with bare ones.
_VARIANT_RE = re.compile(
    rf"^\s*(?:#{{1,6}}\s+)?{_CIRCLED_CLASS}\s*", re.MULTILINE,
)
# Same pattern without the trailing ``\s*`` — used to *detect* a variant-start
# line (independent of splitting), so ``_split_variants`` recognises e.g.
# ``### ① 噪音控制水平`` as a variant boundary.
_VARIANT_START_RE = re.compile(rf"^\s*(?:#{{1,6}}\s+)?{_CIRCLED_CLASS}")
# Inline bold (``**text**``). Kept conservative: no newlines, non-greedy, at
# least one inner char. The inner text survives; the ``**`` markers are peeled
# off so drafts render as plain prose.
_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
# Horizontal-rule lines (``---`` / ``***`` / ``___``): vault notes sometimes
# put a stray ``---`` between the last variant and the backlink tail, and it
# would otherwise be rendered as a horizontal rule mid-draft.
_HR_LINE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
# ATX heading markers (``### Foo``): drop the ``#``s but keep the text so the
# sentence survives as plain prose instead of an unwanted subheading.
_HEADING_PREFIX_RE = re.compile(r"^\s*#{1,6}\s+")
# Any of these on a line marks the start of the vault's navigation / editorial
# tail —— 「说明块」。Everything from the first match to EOF is authoring chrome
# and must never leak into a draft. Two families:
#
#  导航回链（nav backlinks）:
#   ← 返回: [[索引]]                          (arrow style)
#   **返回上层**: [[引言模块总索引|…]]         (bold label)
#   **返回主页**: 关联数据库                    (bold label)
#   返回上层: …   /   返回主页: …               (naked label)
#   相关笔记 / 相关笔记: [[..]] / **相关笔记**  (section header / inline)
#
#  编辑批注（editorial annotations）—— 素材作者写给自己的规格与红线:
#   **取材**: [[型号-产品参数]] | [[..]]        (数据出处)
#   **红线**: - 气态CCM为F3…                    (合规约束)
#   **短板槽**（需收短板的模块：…）             (竞品短板位)
#   **说明**: …                                 (通用说明)
#
# ⚠ 主推位笔记把「取材/红线」排在「返回上层」**之上**（竞品位则相反）。
# 只认「返回」时，排在它上面的取材/红线会躲过切割、被 split_variants 当成
# 最后一个 ①②③ 变体的尾巴一起录进正文 —— 真机生成里「取材:[[..]] 红线:」
# 整块渗进成稿就是这么来的。所以按**最先出现的任意 tail 标记**切，与顺序无关。
_BACKLINK_LINE_RE = re.compile(
    r"(?:←\s*返回"
    r"|\*\*返回(?:上层|主页)\*\*\s*[:：]"
    r"|^\s*返回(?:上层|主页)\s*[:：]"
    r"|^\s*(?:\*\*)?相关笔记(?:\*\*)?(?:\s*[:：].*)?\s*$"
    r"|^\s*\*\*(?:取材|红线|短板槽|说明)\*\*)"
)
# 说明块前常有一条独立的 ``---`` 分隔线。按标记切断后它会留在正文末尾；
# 下游 _clean_chrome / extract_brand_sections 都会剥 HR，但 raw_body 本身也
# 被多处直接消费，索性在切断时把尾部的 HR 行一并 rstrip 掉，正文更干净。
_TRAILING_HR_RE = re.compile(r"(?:^\s*(?:-{3,}|\*{3,}|_{3,})\s*$\n?)+\Z", re.MULTILINE)


@dataclass
class ParsedNote:
    path: Path
    id: str
    frontmatter: dict[str, Any]
    variants: list[str] = field(default_factory=list)
    raw_body: str = ""


def _strip_backlinks(body: str) -> str:
    """Drop the Obsidian navigation / backlink tail from ``body``.

    Returns ``body`` up to (but excluding) the first line that matches any of
    the styles listed in ``_BACKLINK_LINE_RE``. See that regex for the exact
    markers. Everything from that line onward is considered navigation chrome
    and must not leak into generated drafts.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if _BACKLINK_LINE_RE.search(line):
            head = "\n".join(lines[:i]).rstrip()
            # 尾部若剩一条分隔说明块的 ``---``，一并去掉（见 _TRAILING_HR_RE）。
            return _TRAILING_HR_RE.sub("", head).rstrip()
    return body


def parse_note(path: Path) -> ParsedNote:
    # Read as utf-8-sig so a leading UTF-8 BOM is stripped before parsing.
    # python-frontmatter's ``load`` reads raw bytes and does not remove the
    # BOM itself — with one in place, the opening ``---`` is no longer at the
    # start of the stream and frontmatter is silently dropped.
    text = Path(path).read_text(encoding="utf-8-sig")
    post = frontmatter.loads(text)
    body = _strip_backlinks(post.content.strip())
    variants = _split_variants(body)
    return ParsedNote(
        path=path,
        id=path.stem,
        frontmatter=dict(post.metadata),
        variants=variants,
        raw_body=body,
    )


def _clean_chrome(text: str, *, keep_bold: bool = False) -> str:
    """Strip markdown chrome (horizontal rules, heading prefixes) from ``text``.

    Horizontal-rule lines (``---``/``***``/``___``) are dropped entirely.
    ATX heading markers (``###``) are removed but the heading text is kept,
    so a ``### 产品优势`` line survives as plain ``产品优势``.

    ``keep_bold`` 保留正文里的 ``**加粗**`` 标记。默认剥掉 —— 这是历史行为，
    所有既有消费方（段落/编号列表/legacy 竞品池/测试框架）都依赖它，改默认
    就是全线回归。榜单卡片模式要靠加粗突出关键数据（``**703.7 m³/h**``），
    单独把这个开关打开。
    """
    out: list[str] = []
    for line in text.splitlines():
        if _HR_LINE_RE.match(line):
            continue
        line = _HEADING_PREFIX_RE.sub("", line)
        if not keep_bold:
            line = _BOLD_RE.sub(r"\1", line)
        # Strip any residual ①②③ markers that weren't at column 0 (e.g. nested
        # sub-lists inside a variant body); keeps the text that follows.
        line = _VARIANT_RE.sub("", line)
        out.append(line)
    return "\n".join(out).strip()


def split_variants(body: str, *, keep_bold: bool = False) -> list[str]:
    """Public entry point for variant splitting — see :func:`_split_variants`.

    卡片模式按需重跑一遍 ``keep_bold=True`` 的切分（而不是在 ParsedNote 上
    多存一份），避免整库笔记内存翻倍。切分逻辑与默认路径完全相同，所以
    variant 序号一一对应，采样端可以按同一个 index 取到富文本版本。
    """
    return _split_variants(body, keep_bold=keep_bold)


def _split_variants(body: str, *, keep_bold: bool = False) -> list[str]:
    """Split body on lines starting with ①/②/③/... Returns list of variant texts.

    If no numbered markers found, returns [body] as single variant.
    """
    if not any(marker in body for marker in VARIANT_MARKERS):
        cleaned = _clean_chrome(body, keep_bold=keep_bold)
        return [cleaned] if cleaned else []

    # Split on lines starting with a variant marker — either bare (``① ...``)
    # or wrapped in an ATX heading (``### ① ...``). The regex handles both.
    parts: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if _VARIANT_START_RE.match(line):
            if current:
                parts.append(_clean_chrome("\n".join(current), keep_bold=keep_bold))
                current = []
            current.append(_VARIANT_RE.sub("", line, count=1))
        else:
            current.append(line)
    if current:
        tail = _clean_chrome("\n".join(current), keep_bold=keep_bold)
        if tail:
            parts.append(tail)
    return [p for p in parts if p]
