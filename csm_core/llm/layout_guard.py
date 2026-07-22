"""卡片区排版守卫 —— 保住榜单结构不被润色链抹平。

润色链的既有契约只承诺「保留信息点」，不承诺保留排版。榜单卡片区靠
``### … TOP2. 欧瑞达X9`` 标题行和 ``**市场口碑数据**`` 加粗小节撑起结构，
LLM 很容易在改写时把它们并成一段流水文，用户拿到的就不是榜单了。

所以：prompt 里加硬约束（正向要求），再用指纹比对做兜底（反向验证）。

**指纹只覆盖卡片区**，靠 plan 里已知的卡片标题与小节名定界。早期版本比对
全文的标题/加粗/段落数，结果任何正常润色动作都会踩雷 —— 合并两段引言、
把「## 一、前言」润成「## 一、写在前面」、给行内数据加粗，全都被判成破坏
结构、整轮 pass 作废。那样「保排版」的净效果就是「永远不润色」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LAYOUT_CLAUSE = (
    "【排版硬约束】必须原样保留正文的结构：所有 Markdown 标题行"
    "（### 开头的整行，含 TOP 序号、品牌型号、层级标签）一字不改；"
    "所有加粗小节名（**市场口碑数据** 这类）保持原样、顺序不变、不得合并"
    "或删除；段落划分保持不变。只在每个小节的正文内部润色措辞。"
)


@dataclass(frozen=True)
class CardSignature:
    """本篇的卡片结构特征 —— 来自 plan，不靠正则猜。"""

    titles: tuple[str, ...] = ()      # 卡片标题（品牌型号 / 主推名）
    labels: tuple[str, ...] = ()      # 加粗小节名

    def __bool__(self) -> bool:
        return bool(self.titles or self.labels)


def signature_from_plan(plan) -> CardSignature:
    titles: list[str] = []
    labels: list[str] = []
    for r in getattr(plan, "results", []) or []:
        meta = getattr(r, "meta", {}) or {}
        if not meta.get("card"):
            continue
        if r.kind == "hero_brand" and r.text:
            titles.append(r.text.strip())
        for lab in meta.get("section_labels") or []:
            if lab:
                labels.append(str(lab))
        for p in getattr(r, "picks", []) or []:
            pm = p.meta or {}
            t = pm.get("display_title") or pm.get("title")
            if t:
                titles.append(str(t).strip())
            lab = pm.get("section_label")
            if lab:
                labels.append(str(lab))
    return CardSignature(
        titles=tuple(dict.fromkeys(t for t in titles if t)),
        labels=tuple(dict.fromkeys(labels)),
    )


def _protected_headings(text: str, sig: CardSignature) -> list[str]:
    """正文里属于卡片的标题行 —— 只认包含卡片标题的那些。

    非卡片标题（引言/结尾章节）不受保护：润色改写它们是正常动作。
    """
    out: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if any(t and t in stripped for t in sig.titles):
            out.append(stripped)
    return out


def _label_lines(text: str, sig: CardSignature) -> list[str]:
    """行首出现的卡片小节名。只认白名单里的标签 —— 正文里 ``**703.7 m³/h**``
    这类行内数据标粗不是小节名，不该参与比对。"""
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        for lab in sig.labels:
            if s.startswith(f"**{lab}**"):
                out.append(lab)
                break
    return out


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(any(x == y for y in it) for x in needle)


def check(before: str, after: str, sig: CardSignature | None = None) -> str | None:
    """润色前后的卡片结构比对。返回 None = 通过；否则返回违规说明。

    判定是「原有结构必须还在」而不是「结构必须完全相同」：LLM 补一个小标题
    或多分一段都放行，只有**改写/删除/合并**卡片标题与小节名才拦。
    """
    if not sig:
        return None
    before_h = _protected_headings(before, sig)
    after_h = _protected_headings(after, sig)
    lost = [h for h in before_h if h not in after_h]
    if lost:
        return f"卡片标题行被改写或删除：{lost[:3]}"
    if not _is_subsequence(before_h, after_h):
        return "卡片标题行顺序被打乱"

    before_l = _label_lines(before, sig)
    after_l = _label_lines(after, sig)
    if len(after_l) < len(before_l):
        missing = [x for x in before_l if after_l.count(x) < before_l.count(x)]
        return f"加粗小节被删除或合并：{sorted(set(missing))[:3]}"
    if not _is_subsequence(before_l, after_l):
        return "加粗小节顺序被打乱"
    return None
