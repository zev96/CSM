"""Scan an entire Obsidian Vault directory and build a queryable index."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .note_parser import ParsedNote, parse_note


def match_value(actual: Any, wanted: Any) -> bool:
    """模板 filter 的单条判定：frontmatter 值 ``actual`` 是否满足 ``wanted``。

    模板里的筛选值一律是字符串（下拉/输入框出来的），而 frontmatter 是
    YAML —— 类型对不上就永远筛不出来，且失败是静默的（空池）：

    * ``核心关键词: [模板二, 主推位, 品牌实力]`` 这类**列表**是标签集合，
      单值筛选的语义只可能是「含这个标签」。严格相等的话，界面上明明列出
      了「品牌实力」这个取值，选了却一篇都匹配不到。
    * ``模板序号: 2`` 是 **int**、``日期: 2026-06-26`` 是 ``date`` —— 都和
      字符串筛选值严格比不等。

    判定语义：**按每篇笔记自己的类型来** —— 列表看成员，其余按 ``str()``
    归一后比对。这样「一篇笔记是否满足这条筛选」由它自身的写法决定，和
    diagnosis 的反查（``explain_empty_query``）口径一致，反查说「你要的值在
    字段 X 里」时，去筛 X 就真能筛出来。

    ⚠️ 口径说明（不是「零影响」）：第一步 ``actual == wanted`` 与旧代码逐字
    节相同，所以旧代码匹配到的笔记一篇都不会丢 —— 放宽只会「加」不会「减」。
    但「加」在两种情形下会改变**本来非空**的筛选结果，而不只是「空池→有」：
      * 同一个键在同目录里混型（有的笔记写成标量、有的写成列表），标量命中
        之外又补进列表命中的笔记；
      * 该键是数字/日期而筛选值字符串此前比不等。
    经核对，现有全部模板对真实库都只筛标量字符串键（素材类型/模块/核心关键
    词在其目录内均为标量），放宽对它们逐字节等价；但不能声称对任意库、任意
    模板都零影响。
    """
    if actual is None:
        return wanted is None
    if actual == wanted:
        return True
    if isinstance(actual, list):
        return any(str(item) == str(wanted) for item in actual)
    # dict/其它结构没有合理的单值语义，str() 后自然也匹配不到正常筛选值 ——
    # 不特判，交给字符串比对（``str({...})`` 不会等于用户填的普通值）。
    return str(actual) == str(wanted)


@dataclass
class VaultIndex:
    root: Path
    notes: list[ParsedNote] = field(default_factory=list)
    by_id: dict[str, ParsedNote] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def get(self, note_id: str) -> ParsedNote | None:
        return self.by_id.get(note_id)

    def by_module(self, module: str) -> list[ParsedNote]:
        """Return notes whose path contains the module path parts in order.

        The module string is a '/'-separated sequence of directory names that
        must appear as an ordered (not necessarily contiguous) subsequence of
        the note's relative path parts under ``root``.
        """
        wanted = [p for p in module.replace("\\", "/").split("/") if p]
        matches: list[ParsedNote] = []
        for n in self.notes:
            try:
                rel_parts = n.path.relative_to(self.root).parts[:-1]
            except ValueError:
                continue
            i = 0
            for part in rel_parts:
                if i < len(wanted) and part == wanted[i]:
                    i += 1
            if i == len(wanted):
                matches.append(n)
        return matches

    def query(
        self,
        *,
        module: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[ParsedNote]:
        candidates = self.by_module(module) if module else list(self.notes)
        if not filters:
            return candidates
        return [
            n for n in candidates
            if all(match_value(n.frontmatter.get(k), v) for k, v in filters.items())
        ]


def _values_of(notes: list[ParsedNote], key: str) -> list[str]:
    """该批笔记里 ``key`` 出现过的去重取值（列表展开、保持出现顺序）。"""
    seen: dict[str, None] = {}
    for n in notes:
        v = (n.frontmatter or {}).get(key)
        if v is None or v == "":
            continue
        for item in (v if isinstance(v, list) else [v]):
            if item is None or item == "":
                continue
            seen.setdefault(str(item), None)
    return list(seen)


def _keys_of(notes: list[ParsedNote]) -> list[str]:
    """该批笔记 frontmatter 里出现过的字段名（去重、保持出现顺序）。"""
    seen: dict[str, None] = {}
    for n in notes:
        for k in (n.frontmatter or {}):
            seen.setdefault(k, None)
    return list(seen)


def _preview(items: list[str], cap: int = 8) -> str:
    head = "、".join(f"「{x}」" for x in items[:cap])
    return head + (f" 等 {len(items)} 种" if len(items) > cap else "")


def explain_empty_query(
    index: VaultIndex, module: str | None, filters: dict[str, Any] | None,
) -> str:
    """空池归因 —— 一句话说清「明明有素材，为什么筛不出来」。

    "没有符合条件的素材" 本身不可行动：目录里躺着 8 篇，用户看得见，报错
    却只说没有。真正要回答的是「差在哪」，而这三件事索引里都查得到：目录
    到底空不空、筛选字段在不在、字段的实际取值是什么。

    最值钱的是最后一句反查：把要筛的值拿去所有字段里搜一遍，命中就直接
    报出「它在『模块』这个字段里」—— 填错字段名是这个 UI 最容易犯的错。
    """
    scope = index.by_module(module) if module else index.notes
    if not scope:
        return "该目录下一篇素材都没有 —— 检查目录名是否写错，或素材还没建。"
    if not filters:
        return ""

    total = f"该目录下有 {len(scope)} 篇素材"
    for key, wanted in filters.items():
        if wanted == "":
            # 编辑器里「选了字段还没选值」会留下 {字段: ""}，直接点名它，
            # 别去列该字段的取值让人以为是值填错了。
            return f"{total}，但「{key}」这条筛选只选了字段、没填值。"
        if any(match_value(n.frontmatter.get(key), wanted) for n in scope):
            continue                      # 这条不是凶手，看下一条
        vals = _values_of(scope, key)
        if not vals:
            return (
                f"{total}，但没有一篇写了「{key}」这个字段。"
                f"该目录用到的字段：{_preview(_keys_of(scope))}。"
            )
        # 反查：值本身在哪些字段里出现过。全列出来不猜 —— 同一个值常常既在
        # 标量字段（模块）又在标签列表（核心关键词）里，替用户选一个反而误导。
        elsewhere = [
            other for other in _keys_of(scope)
            if other != key
            and any(match_value(n.frontmatter.get(other), wanted) for n in scope)
        ]
        hint = ""
        if elsewhere:
            where = "、".join(f"「{k}」" for k in elsewhere[:3])
            which = "该填它" if len(elsewhere) == 1 else "该填其中之一"
            hint = f"你要的「{wanted}」在字段{where}里 —— 筛选字段大概{which}。"
        return f"{total}，「{key}」的实际取值是：{_preview(vals)}。{hint}"

    return f"{total}，每条筛选单独都能命中，但没有素材同时满足全部条件。"


def parse_one(md_path: Path) -> tuple[ParsedNote | None, str | None]:
    """单文件解析：返回 (note, warning)，二者恰有其一非 None。

    与 scan_vault 的逐文件逻辑等价：缺 frontmatter → (None, 警告)；
    解析异常 → (None, 警告)。供全量扫与增量索引共用。
    """
    try:
        note = parse_note(md_path)
    except Exception as exc:
        return None, f"{md_path.name}: 解析失败 — {exc}"
    if not note.frontmatter:
        return None, f"{md_path.name}: 缺少 frontmatter"
    return note, None


def scan_vault(root: Path) -> VaultIndex:
    index = VaultIndex(root=root)
    for md_path in sorted(root.rglob("*.md")):
        note, warning = parse_one(md_path)
        if warning:
            index.warnings.append(warning)
        if note is not None:
            index.notes.append(note)
            index.by_id[note.id] = note
    return index
