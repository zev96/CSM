"""对比指令块 —— 经 angle_directive 通道注入 LLM 润色 pass 的一段文本。"""
from __future__ import annotations


def build_comparison_directive(*, primary_label: str | None, tone: str | None) -> str:
    """横评润色指令：客观对比 + 不贬损 + 参数照抄 + 结论突出主推（若有）+ 语调。"""
    parts = [
        "这是一篇多型号横评文章。请基于给定事实客观对比各型号，"
        "不得使用贬损性措辞，对比表中的参数一律照抄、不得改写或杜撰。",
    ]
    if primary_label:
        parts.append(f"结论段请自然突出 {primary_label} 的事实性优势，但不夸大、不虚构。")
    if tone:
        parts.append(f"整体语调：{tone}。")
    return "".join(parts)
