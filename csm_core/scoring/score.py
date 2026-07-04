"""score_article：组合 lint/AI味/核对信号 → ScoreReport（0-100，确定性）。"""
from __future__ import annotations

from csm_core.config import ScoringConfig
from csm_core.lint.model import LintReport

from .ai_flavor import ai_flavor_parts
from .model import ScorePart, ScoreReport

_JUDGMENT_CATS = {"meta_speak", "absolute", "traffic"}   # 4 分/处
_MECH_POINTS = 2.0                                        # emoji/dash/quote
_JUDGMENT_POINTS = 4.0
_LINT_CAP = 30.0
_FACTCHECK_POINTS, _FACTCHECK_CAP = 6.0, 18.0
_COMPLETENESS_POINTS, _COMPLETENESS_CAP = 4.0, 12.0


def score_article(
    text: str, *,
    lint_report: LintReport,
    factcheck_violations: int = 0,
    completeness_missing: int = 0,
    config: ScoringConfig | None = None,
) -> ScoreReport:
    cfg = config or ScoringConfig()
    parts: list[ScorePart] = []

    n_judge = sum(1 for h in lint_report.hits if h.category in _JUDGMENT_CATS)
    n_mech = len(lint_report.hits) - n_judge
    lint_pts = min(_LINT_CAP, n_judge * _JUDGMENT_POINTS + n_mech * _MECH_POINTS)
    if lint_pts:
        parts.append(ScorePart(
            key="lint", label="禁区命中", points=lint_pts,
            detail=f"判断类 {n_judge} 处、机械类 {n_mech} 处"))

    parts.extend(ai_flavor_parts(text, extra_words=cfg.extra_ai_words))

    if factcheck_violations:
        parts.append(ScorePart(
            key="factcheck", label="事实核对违规",
            points=min(_FACTCHECK_CAP, factcheck_violations * _FACTCHECK_POINTS),
            detail=f"越界 {factcheck_violations} 处"))
    if completeness_missing:
        parts.append(ScorePart(
            key="completeness", label="完整性缺失",
            points=min(_COMPLETENESS_CAP, completeness_missing * _COMPLETENESS_POINTS),
            detail=f"缺失 {completeness_missing} 处"))

    total = max(0.0, round(100.0 - sum(p.points for p in parts), 1))
    return ScoreReport(total=total, parts=sorted(parts, key=lambda p: -p.points))
