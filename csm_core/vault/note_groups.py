"""「一篇笔记 = 一个小节」的目录归纳 —— 主推卡「从目录识别」的内核。

竞品卡和主推卡的素材形态是**两种东西**，识别逻辑不能共用：

* 竞品卡：一篇笔记 = 一个竞品，小节是笔记正文里的 ``## H2``。
  → 归纳 H2（``routes/vault.py::card_sections``）。
* 主推卡：一个小节 = **一整篇笔记**，靠 frontmatter 的某个字段区分
  （``模块: 市场口碑数据``）。H2 在这里毫无意义。
  → 归纳「哪个字段能把这批笔记分开、它有哪些取值」，就是本模块。

两个判断都不硬编码字段名，因为资料库的字段命名是用户的事：

**分组字段** 必须能把目录切成「一篇一组」。所以要求：标量（列表字段一篇
会落进多个组，当不了小节）、取值不止一种（``品牌: DARZ`` 全同，分不开）、
覆盖面越全越好。并列时优先取值**不是纯数字**的那个 —— 小节名该是名字，
``模块`` 而不是 ``模块序号``。

**排序字段** 是另一个字段：取值全为数字、且基本一篇一个。有它就按它排，
没有就按扫描顺序。榜单小节的先后直接决定成文排版，字母序导进去就乱了。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .note_parser import ParsedNote


@dataclass(frozen=True)
class GroupedValue:
    """一个候选小节：字段的一个取值。"""

    value: str
    note_count: int          # 取这个值的笔记数（正常是 1）
    with_body: int           # 其中正文非空的篇数 —— 空骨架抽出来是空段
    order: float             # 排序键（排序字段的值，或扫描序）

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "note_count": self.note_count,
            "with_body": self.with_body,
            "order": self.order,
        }


def _scalar(v: Any) -> str | None:
    """frontmatter 值的标量投影。列表/空值返回 None（当不了分组键）。"""
    if v is None or isinstance(v, (list, dict)):
        return None
    s = str(v).strip()
    return s or None


def _as_number(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _field_stats(notes: list[ParsedNote], key: str) -> tuple[int, int, bool]:
    """(覆盖篇数, 去重取值数, 取值是否全为数字)。"""
    values: list[str] = []
    for n in notes:
        s = _scalar((n.frontmatter or {}).get(key))
        if s is not None:
            values.append(s)
    distinct = len(set(values))
    all_numeric = bool(values) and all(_as_number(v) is not None for v in values)
    return len(values), distinct, all_numeric


def field_candidates(notes: list[ParsedNote]) -> list[str]:
    """能当分组字段的 frontmatter 键，按「像小节字段」的程度降序。

    排序键（全部降序）：覆盖全部笔记 > 一篇一个取值（distinct == 篇数）>
    取值不是纯数字 > 去重取值数 > 覆盖篇数。最后用字段名兜底保证确定性 ——
    识别结果要能复现，不能因为 dict 顺序变了就换一个字段。
    """
    if not notes:
        return []
    keys: dict[str, None] = {}
    for n in notes:
        for k in (n.frontmatter or {}):
            keys.setdefault(k, None)

    scored: list[tuple[tuple, str]] = []
    for key in keys:
        covered, distinct, all_numeric = _field_stats(notes, key)
        if distinct < 2:
            # 全同（品牌/产品/素材类型）或没人写 —— 分不开，不是候选。
            continue
        scored.append((
            (
                covered == len(notes),
                distinct == len(notes),
                not all_numeric,
                distinct,
                covered,
            ),
            key,
        ))
    # 两趟稳定排序：先按字段名升序兜底，再按得分降序 —— 同分时保住名字序，
    # 识别结果对同一个目录永远一样。
    scored.sort(key=lambda t: t[1])
    scored.sort(key=lambda t: t[0], reverse=True)
    return [key for _, key in scored]


def order_field_for(notes: list[ParsedNote], group_field: str) -> str | None:
    """给分组字段找一个「序号」伴随字段。找不到返回 None（按扫描序）。

    判定纯结构：取值全为数字、覆盖全部笔记、至少两种取值。同名前缀
    （``模块`` → ``模块序号``）优先，因为那是最强的意图信号。

    ⚠ 遍历必须**排序**、命中也不能「先到先得」：直接 for 一个 set 的话
    字符串哈希随机化会让同前缀的两个候选（``模块序号`` / ``模块排序``）
    跨进程各赢一次，两者给出的小节顺序还可能正好相反 —— 小节先后直接
    决定成文排版，这种不确定性会让「同一个目录识别两次结果不同」。

    也**不要求**一篇一个序号：真实库里手填序号撞车是常见笔误，一撞就整个
    退回文件名序（=字母序），那才是真正看得见的排版事故。撞车时同值的组
    取最小序号，其余仍然正确排开。
    """
    eligible: list[tuple[int, int, str]] = []
    for key in sorted({k for n in notes for k in (n.frontmatter or {})}):
        if key == group_field:
            continue
        covered, distinct, all_numeric = _field_stats(notes, key)
        if not all_numeric or covered != len(notes) or distinct < 2:
            continue
        # 排序键：同名前缀优先 → 取值越细越好 → 字段名（sorted 已保证稳定）
        eligible.append((1 if key.startswith(group_field) else 0, distinct, key))
    if not eligible:
        return None
    eligible.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return eligible[0][2]


def group_notes_by_field(
    notes: list[ParsedNote], field: str, *, order_field: str | None = None,
) -> list[GroupedValue]:
    """按 ``field`` 的取值把笔记归组，按 ``order_field`` 排序。

    同一取值多篇时合并成一组（``note_count`` > 1）—— 那说明目录里有重复
    素材，抽签会在它们之间随机，用户看得到篇数就能判断是不是想要的。
    """
    buckets: dict[str, list[tuple[int, ParsedNote]]] = {}
    for i, n in enumerate(notes):
        s = _scalar((n.frontmatter or {}).get(field))
        if s is None:
            continue
        buckets.setdefault(s, []).append((i, n))

    out: list[GroupedValue] = []
    for value, items in buckets.items():
        orders: list[float] = []
        for scan_pos, n in items:
            num = None
            if order_field:
                raw = _scalar((n.frontmatter or {}).get(order_field))
                num = _as_number(raw) if raw is not None else None
            orders.append(num if num is not None else float(scan_pos))
        out.append(GroupedValue(
            value=value,
            note_count=len(items),
            with_body=sum(1 for _, n in items if (n.raw_body or "").strip()),
            order=min(orders),
        ))
    out.sort(key=lambda g: (g.order, g.value))
    return out
