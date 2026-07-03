"""成稿评分服务：读 config → lint 扫描 + score_article → dict。纯计算不写盘。"""
from __future__ import annotations

from typing import Any

from csm_core.lint import build_report, build_rules
from csm_core.scoring import score_article

from . import config_service


def score_text(
    text: str, *, factcheck_violations: int = 0, completeness_missing: int = 0,
) -> dict[str, Any]:
    cfg = config_service.load()
    if not cfg.scoring.enabled:
        return {"total": None, "parts": []}
    lint_report = build_report(text or "", build_rules(cfg.lint))
    return score_article(
        text or "", lint_report=lint_report,
        factcheck_violations=factcheck_violations,
        completeness_missing=completeness_missing,
        config=cfg.scoring,
    ).model_dump()
