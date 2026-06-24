"""角度派生：有效卖点 + 有效查询 filter（采样/reroll/持久化共用）。"""
from __future__ import annotations
from typing import Any
from .model import Angle
from .taxonomy import AUDIENCES, AUDIENCE_MODULE_MARKER


def effective_sellpoints(angle: Angle | None) -> list[str]:
    """显式卖点 > 人群派生主推维度 > 空。用于注入优先 + 指令侧重。"""
    if angle is None:
        return []
    if angle.sellpoints:
        return list(angle.sellpoints)
    if angle.audience and angle.audience in AUDIENCES:
        dim = AUDIENCES[angle.audience]["主推维度"]
        return [dim] if dim else []
    return []


def effective_filters(source: Any, angle: Angle | None) -> dict:
    """该块的有效查询 filter = source.filter ∪ 角度人群 filter。
    人群 filter 只在 source.module 含「用户人群」标记的块生效。
    采样、reroll、持久化共用此函数，避免逻辑漂移。"""
    base = dict(getattr(source, "filter", None) or {})
    if angle is None or not angle.audience:
        return base
    module = getattr(source, "module", "") or ""
    if AUDIENCE_MODULE_MARKER in module:
        base["人群分类"] = angle.audience
    return base
