"""标题守卫 —— 润色链不得新增/改写/删除文章标题。

标题是**用户定的**：首页起飞条填的，或从「换标题」候选里选的。候选那条路
已经硬约束了「必须一字不差包含关键词」（``csm_core.title.generator``：
prompt 规则 + ``validate_title`` 校验 + 保留关键词的机械兜底）。

润色链只该改正文。但 prompt 把标题当写作指引给了 LLM（``【标题】…``，
「围绕标题开篇点题、贯穿全文」），没有任何东西禁止它顺手写一个自己的 H1、
或者把原标题揉进正文里删掉。而**正文首行的 H1 恰恰是全链路认定的文章标题**
（``export.markdown.ensure_title`` 见到 H1 就原样返回、``extract_title``
从它取标题、前端 ``effectiveTitle`` 同口径）。于是 LLM 写的标题就成了文章
标题 —— 用户看到的是「润色把我的标题改了」，而且那个标题不受关键词约束，
SEO 关键词被悄悄改没或删掉。

两种情形分开处理：

- **用户定了标题** → 原样钉住（改写就还原、删掉就补回、自造就换回）。
- **用户没定标题**（默认流程：只填了关键词）→ 链可以自己拟一个，但**必须
  一字不差含关键词**，否则整行移除、退回导出层用关键词兜底。

和 ``layout_guard`` 一个路子：prompt 里下硬约束（正向要求），落库前做确定性
纠正（反向兜底）。差别在处置力度 —— 排版守卫整轮 pass 回退，标题守卫只动
标题那一行，正文的润色成果照常保留。
"""
from __future__ import annotations

import re

TITLE_CLAUSE = (
    "【标题硬约束】文章标题由用户确定，不归你写："
    "正文第一行若是 `# ` 开头的标题行，必须一字不改地原样保留（含其中的关键词）；"
    "正文里若本来没有标题行，也不要自己新增一个。"
    "不得改写、扩写、缩写、翻译或删除标题。"
)


def keyword_title_clause(keyword: str) -> str:
    """用户没定标题时的约束 —— 链可以拟标题，但不许动关键词。"""
    return (
        "【标题硬约束】如果你要给正文加标题行，标题里必须**一字不差、连续完整**地"
        f"包含关键词「{keyword}」（不得拆开、替换、增删其中任何一个字）；"
        "做不到就不要加标题行。"
    )


# 只认真正的 H1。``## 一、品牌分析`` 是章节标题，不是文章标题 —— 判据与
# ``export.markdown.ensure_title`` / 前端 ``leadingTitle`` 保持一致。
_H1_RE = re.compile(r"^#\s+(.*)$")


def _norm(s: str | None) -> str:
    """**仅用于比较**的归一化 —— 空白压成单空格。

    绝不能拿它的结果回写：``str.split()`` 会把全角空格 U+3000、连续空格
    都折掉，而关键词里带全角空格（中文输入法全角模式很常见）时，回写就等于
    **守卫自己改了关键词** —— 正撞「不能修改删除关键词」这条需求。
    """
    return " ".join((s or "").split())


def _single_line(s: str | None) -> str:
    """回写用的规整 —— 只压掉换行（H1 是单行结构），行内空白原样保留。

    首尾只剥 ASCII 空白：``str.strip()`` 会把全角空格 U+3000、NBSP 也剥掉，
    而关键词首尾就带着它们时，剥了就等于守卫改了关键词的字节。
    """
    return " ".join((s or "").splitlines()).strip(" \t\r\n")


def leading_h1(text: str | None) -> tuple[int, str] | None:
    """正文的文章标题 —— 返回 ``(行号, 标题文字)``，没有则 None。

    跳过前导空行；第一个非空行不是 H1 就判定「没有标题」（后面的 ``#`` 是
    正文里的东西，不是文章标题）。
    """
    lines = (text or "").split("\n")
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##"):
            return None
        m = _H1_RE.match(line)
        return (i, m.group(1).strip()) if m else None
    return None


def _find_h1(text: str, wanted_norm: str) -> list[int]:
    """正文任意位置上标题为 *wanted_norm* 的**所有** H1 行号。

    跳过围栏代码块内部：``` ``` ``` 里的 ``# foo`` 是代码不是标题，把它当标题
    搬走会把代码块掏空（静默改内容，比漏纠正糟得多）。
    """
    out: list[int] = []
    in_fence = False
    for i, raw in enumerate((text or "").split("\n")):
        line = raw.strip()
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or line.startswith("##"):
            continue
        m = _H1_RE.match(line)
        if m and _norm(m.group(1)) == wanted_norm:
            out.append(i)
    return out


def _replace_line(text: str, index: int, new_line: str) -> str:
    lines = text.split("\n")
    lines[index] = new_line
    return "\n".join(lines)


def _drop_line(text: str, index: int) -> str | None:
    """删掉第 *index* 行（连同其后的空行）。删完没正文了就返回 None。"""
    lines = text.split("\n")
    del lines[index]
    while lines and index < len(lines) and not lines[index].strip():
        del lines[index]
    if not any(line.strip() for line in lines):
        return None       # 只剩标题的输出：删了就是空文档，宁可留着
    return "\n".join(lines)


def _hoist(text: str, indices: list[int], title_line: str) -> str:
    """把散落在正文里的标题行**全部**摘掉，再把标题放回最前面。

    只摘第一处的话，LLM 把标题重复写了两遍时输出里还是两个 H1 —— 正是这个
    分支要消灭的形态。
    """
    lines = text.split("\n")
    for index in sorted(indices, reverse=True):
        del lines[index]
        while index < len(lines) and not lines[index].strip():
            del lines[index]
    body = "\n".join(lines).lstrip("\n")
    return f"{title_line}\n\n{body}"


def enforce(
    before: str,
    after: str,
    *,
    title: str | None = None,
    keyword: str | None = None,
) -> tuple[str, str | None]:
    """把 *after* 的标题拉回用户的标题。返回 ``(修正后的正文, 违规说明|None)``。

    - 输入有标题 → 输出必须是同一个：被改写就还原、被挪走就提回开头、
      被删掉就补回。
    - 输入没标题（毛坯文的常态，``compose_draft`` 不产 H1）：
      有用户标题 → LLM 自造的标题换成用户的；
      没有用户标题 → 自造的标题至少要一字不差含关键词，否则整行移除。
    - 两边都没标题 → **一个字都不动**。链输出不带标题是今天的行为（标题是
      单独字段，导出时 ``ensure_title`` 才补），硬塞 H1 会让字数、查重、
      事实核对的输入统统变样。
    """
    src = leading_h1(before)
    got = leading_h1(after)
    # 回写一律用原串（只压换行），比较才用 _norm —— 见 _norm 的 docstring。
    expected_raw = _single_line(src[1] if src is not None else title)
    expected = _norm(expected_raw)

    if src is not None:
        if got is not None:
            # 字节相同才算没动。只比 _norm 的话，LLM 把标题里的全角空格换成
            # 半角（关键词最容易被「顺手规范化」掉的形态）会被判成没动 ——
            # 而那正是这条守卫要防的「改了关键词」。差别只在空白时照样重写
            # 那一行：文本本就等价，没有误报风险，换来的是字节级保真。
            if got[1] == expected_raw:
                return after, None
            if _norm(got[1]) == expected:
                return (
                    _replace_line(after, got[0], f"# {expected_raw}"),
                    "润色改动了标题里的空白 —— 已还原原字符",
                )
            return (
                _replace_line(after, got[0], f"# {expected_raw}"),
                f"润色把标题改写成了「{got[1]}」—— 已还原",
            )
        # 标题可能被挪到开篇段之后了 —— 那是「移动」不是「删除」，提回开头，
        # 别再补一个（会出现两个 H1）。
        at = _find_h1(after, expected)
        if at:
            return (
                _hoist(after, at, f"# {expected_raw}"),
                "润色把标题挪到了正文中间 —— 已提回开头",
            )
        return f"# {expected_raw}\n\n{after}", "润色把标题删除了 —— 已补回"

    # 输入没有标题
    if got is None:
        return after, None
    if expected:
        if _norm(got[1]) == expected:
            return after, None
        return (
            _replace_line(after, got[0], f"# {expected_raw}"),
            f"润色自造了标题「{got[1]}」—— 已换回用户的标题",
        )
    # 用户没定标题：链可以自己拟，但关键词必须一字不差留着。
    if keyword and keyword not in got[1]:
        dropped = _drop_line(after, got[0])
        if dropped is None:
            # 删了就是空文档，宁可留着 —— 但别静默，这稿的标题确实不合规。
            return after, f"润色自造的标题「{got[1]}」不含关键词「{keyword}」—— 正文只有标题，未移除"
        return (
            dropped,
            f"润色自造的标题「{got[1]}」不含关键词「{keyword}」—— 已移除",
        )
    return after, None
