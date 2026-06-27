"""禁区 lint 引擎：确定性扫描成稿违规措辞/标点。"""
from .model import Category, LintHit, LintReport
from .rules import Rules, build_rules
from .scanner import autofix, build_report, scan

__all__ = [
    "Category", "LintHit", "LintReport", "Rules",
    "build_rules", "scan", "autofix", "build_report",
]
