"""成稿确定性评分：禁区 lint + AI 味启发式 + 核对信号 → 0-100。"""
from .model import ScorePart, ScoreReport
from .ai_flavor import AI_CONNECTIVES, ai_flavor_parts
from .score import score_article

__all__ = [
    "ScorePart", "ScoreReport", "AI_CONNECTIVES", "ai_flavor_parts",
    "score_article",
]
