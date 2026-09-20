"""AI 味启发式评分 —— 引流 AI 评论生成用它给候选评论打分。"""
from .model import ScorePart
from .ai_flavor import AI_CONNECTIVES, ai_flavor_parts

__all__ = [
    "ScorePart", "AI_CONNECTIVES", "ai_flavor_parts",
]
