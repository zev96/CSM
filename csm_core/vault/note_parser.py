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
# 上面那张标签名白名单永远追不上资料库 —— 作者随时会造新标签（实测漏了
# ``**关联素材**``、``**相关技术笔记**``、``**返回首页**``，19 篇引言笔记因此
# 把「关联素材: [[..]] | [[..]]」整行录进了成稿）。所以再加一条**按结构**认的
# 规则：一行的值除了 wiki 链接、加粗和分隔符什么都没有 —— 也就是「这行只是
# 指向别的笔记」—— 那它是导航/引用，不是文章正文（``[[..]]`` 是 Obsidian
# 语法，出现在成稿里永远是错的）。标签可有可无：``**关联素材**: [[a]] | [[b]]``
# 与裸的 ``[[a]] | [[b]]`` 同样算。
#
# ⚠ 值里必须**至少有一个** wiki 链接（lookahead），否则 ``解决方案:`` 这种
# 空值标签行会被误判；链接后面还跟着说明文字的（``- **选购指南**: [[电机性能选购]]
# - 电机类型对比``）也不匹配 —— 那是索引笔记的正文。
# ⚠ 三处写法是为了线性时间，别「顺手简化」回去（改动前先跑 ReDoS 计时）：
#   1. 先决 lookahead 放**最前**且用 ``[^\n]*`` —— 没有 wiki 链接的普通正文行
#      （绝大多数）一次扫描即否决，不会带着各种标签切分反复试。
#   2. 冒号后**不留** ``\s*`` —— 空白交给下面循环里的 ``\s`` 吃。两处都能吃
#      同一段空白时，N 个空格就有 N 个切分点，每点再扫一遍 = O(N²)（实测
#      2 万空格的行要 1.2 秒）。
#   3. 循环用占有量词 ``++`` —— 后面只跟 ``$``，吐字符永远换不来匹配成功，
#      所以禁止回溯与原语义逐字节等价，纯赚。需 Python ≥3.11（本项目下限）。
_LINK_ONLY_LINE_RE = re.compile(
    r"^(?=[^\n]*\[\[)"                                   # 先决条件：这行有 wiki 链接
    r"\s*(?:[-*+>]\s*)*"                                 # 可选项目符号 / 引用符
    # 可选「标签:」。{1,16} 只约束**裸标签**；``**加粗标签**`` 无论多长都会走
    # 下面循环里的 ``\*\*…\*\*`` 分支（冒号也在分隔符类里），所以长加粗标签
    # 照样认得出 —— 这是好事，别照着这行注释以为有 16 字硬上限。
    r"(?:(?:\*\*)?[^:：\n\[\]]{1,16}(?:\*\*)?\s*[:：])?"
    r"(?:\[\[[^\]\n]+\]\]|\*\*[^*\n]+\*\*|[|｜、,，;；:：/·—\s>→-])++$"
)


def _is_tail_chrome(line: str) -> bool:
    """这一行能否算「尾部说明块」的一部分（空行 / 分隔线 / 已知标记 / 纯链接行）。"""
    if not line.strip():
        return True
    if _HR_LINE_RE.match(line):
        return True
    if _BACKLINK_LINE_RE.search(line):
        return True
    return bool(_LINK_ONLY_LINE_RE.match(line))


@dataclass
class ParsedNote:
    path: Path
    id: str
    frontmatter: dict[str, Any]
    variants: list[str] = field(default_factory=list)
    raw_body: str = ""


def _strip_backlinks(body: str) -> str:
    """Drop the Obsidian navigation / backlink tail from ``body``.

    切到**不动点**：一趟切割会让原本被挡住的说明块行暴露成新的尾行，所以要
    反复切到不再变化为止。单趟是**顺序敏感**的，而说明块内部顺序并不固定
    （主推位把取材/红线排在返回之上，竞品位反过来）—— 比如 ``**关联素材**``
    排在散文型的 ``**红线**`` 之上时，单趟只会切到红线那行，关联素材原样留在
    正文里，正是本次要修的那个 bug 换个版式复发。逐趟收敛后与顺序无关，
    和 ``_BACKLINK_LINE_RE`` 当年扩成「按最先出现的任意标记切」是同一个不变量。
    """
    seen = body
    # 每趟严格变短，故必然收敛；上界只是防病态输入下的死循环。
    for _ in range(len(body.splitlines()) + 1):
        nxt = _strip_backlinks_once(seen)
        if nxt == seen:
            break
        seen = nxt
    return seen


def _strip_backlinks_once(body: str) -> str:
    """单趟切割 —— 见 :func:`_strip_backlinks` 的不动点循环。

    两条判据，取**最先命中**的那一行作为切点，该行起到 EOF 全部丢弃：

    1. 已知标记（``_BACKLINK_LINE_RE``）—— 无条件切。这些标签的值本身常是
       散文（``**红线**: - 气态CCM为F3…``），不能要求后面全是说明块。
    2. 纯链接行（``_LINK_ONLY_LINE_RE``）—— **只在尾部**才切：从末尾往回数，
       必须一路都是说明块/空行/分隔线才算数。

    第 2 条的尾部限定不是保守，是必须：索引类笔记（``用户人群总索引``、
    ``吸尘器科普内容索引``）和拆解分析文档正文**中间**也有 ``**痛点文件**:
    [[..]]`` / ``> 配套文档：[[..]]`` 这种行，后面还跟着整篇正文 —— 在那里
    一刀切到 EOF 会把笔记清空。

    ⚠ 边界要说准，别把它当万能：本规则只认「值全是 wiki 链接和分隔符」这一种
    形态。**散文型**说明块（``**使用注意**：…``、开头整段的 ``⚠️ 取用前必读
    [[..]]``）仍只能靠第 1 条的标签名单，名单外的写法照漏，而且它们常排在正文
    **开头**，结构上也不该按尾部规则切。

    实测全库仍有 25 篇正文带 ``[[..]]``，其中 **3 篇是带 ``素材类型`` 的真素材**
    （``整机推荐文案`` 2 篇 + ``标题模块总索引``），别误以为剩下的全是索引文档 ——
    现装模板的可达集碰不到它们，但新建一个指向 ``整机推荐文案`` 目录的块就会把
    开头那段告示写进成稿。治本在资料库侧（把告示移出正文或改成 frontmatter），
    不是继续加解析规则。
    """
    lines = body.splitlines()
    # 尾部说明块的起点：从最后一行往回吃，直到遇上真正的正文行。
    tail_start = len(lines)
    while tail_start > 0 and _is_tail_chrome(lines[tail_start - 1]):
        tail_start -= 1
    for i, line in enumerate(lines):
        if _BACKLINK_LINE_RE.search(line) or (
            i >= tail_start and _LINK_ONLY_LINE_RE.match(line)
        ):
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
