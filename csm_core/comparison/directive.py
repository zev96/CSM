"""对比指令块 —— 经 angle_directive 通道注入 LLM 润色 pass 的一段文本。

占位实现，Task A6 补全（含单测）。当前仅为让包 __init__ 的 eager import
成立，使 A1–A5 的 compose 测试可导入。"""
from __future__ import annotations


def build_comparison_directive(*, primary_label: str | None, tone: str | None) -> str:
    raise NotImplementedError  # Task A6
