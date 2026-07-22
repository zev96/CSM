"""排版结构指纹 —— 保住卡片区不被润色链抹平。

润色链的既有契约只承诺「保留信息点」，不承诺保留排版。榜单卡片区靠
``### … TOP2. 欧瑞达X9`` 标题行和 ``**市场口碑数据**`` 加粗小节撑起结构，
LLM 很容易在改写时把它们并成一段流水文，用户拿到的就不是榜单了。

所以：prompt 里加硬约束（正向要求），再用指纹比对做兜底（反向验证）。
指纹只看结构、不看措辞 —— 标题行原文、加粗小节名、段落数。任一项对不上
就判定这轮润色破坏了结构，调用方回退到上一版文本。**保结构优先于保润色**。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")
# 独立成分的加粗小节名：一行开头的 **xxx**（后面可跟全角冒号或换行）。
_BOLD_LABEL_RE = re.compile(r"^\s*\*\*([^*\n]{1,40})\*\*\s*[：:]?", re.MULTILINE)

LAYOUT_CLAUSE = (
    "【排版硬约束】必须原样保留正文的结构：所有 Markdown 标题行"
    "（### 开头的整行，含 TOP 序号、品牌型号、层级标签）一字不改；"
    "所有加粗小节名（**市场口碑数据** 这类）保持原样、顺序不变、不得合并"
    "或删除；段落划分保持不变。只在每个小节的正文内部润色措辞。"
)


@dataclass(frozen=True)
class LayoutFingerprint:
    headings: tuple[str, ...]
    labels: tuple[str, ...]
    paragraphs: int

    def diff(self, other: "LayoutFingerprint") -> str | None:
        """返回人话差异说明；结构一致时返回 None。"""
        if self.headings != other.headings:
            lost = [h for h in self.headings if h not in other.headings]
            if lost:
                return f"标题行被改写或删除：{lost[:3]}"
            return "标题行数量或顺序变了"
        if self.labels != other.labels:
            lost = [x for x in self.labels if x not in other.labels]
            if lost:
                return f"加粗小节被改写或删除：{lost[:3]}"
            return "加粗小节顺序变了"
        if other.paragraphs < self.paragraphs:
            return f"段落被合并：{self.paragraphs} → {other.paragraphs}"
        return None


def fingerprint(text: str) -> LayoutFingerprint:
    headings = tuple(
        m.group(0).strip() for m in
        (_HEADING_RE.match(line) for line in (text or "").splitlines())
        if m
    )
    labels = tuple(m.group(1).strip() for m in _BOLD_LABEL_RE.finditer(text or ""))
    paragraphs = len([p for p in re.split(r"\n\s*\n", text or "") if p.strip()])
    return LayoutFingerprint(headings, labels, paragraphs)


def check(before: str, after: str) -> str | None:
    """润色前后结构比对。返回 None = 通过；否则返回违规说明。"""
    return fingerprint(before).diff(fingerprint(after))
