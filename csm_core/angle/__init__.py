"""角度智能组装 — 词表 + 派生（Phase 2a）。"""
from .model import Angle
from .filters import effective_filters, effective_sellpoints
from .directive import render_angle_directive

__all__ = [
    "Angle", "effective_filters", "effective_sellpoints", "render_angle_directive",
]
