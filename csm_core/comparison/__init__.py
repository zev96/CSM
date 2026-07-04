"""多型号横评：确定性骨架 + 对比指令块（零 LLM）。"""
from csm_core.comparison.compose import compose_comparison_draft
from csm_core.comparison.directive import build_comparison_directive

__all__ = ["compose_comparison_draft", "build_comparison_directive"]
