"""把 Angle 渲染成一段中文「角度指令块」喂给 LLM（保守契约）。"""
from __future__ import annotations
from .model import Angle
from .taxonomy import AUDIENCES, SELLPOINT_DIMENSIONS, TONES
from .filters import effective_sellpoints

_DIM_LABEL = {d["key"]: d["label"] for d in SELLPOINT_DIMENSIONS}


def render_angle_directive(angle: Angle | None) -> str | None:
    if angle is None or angle.is_empty():
        return None
    lines: list[str] = ["【写作角度】"]
    if angle.audience and angle.audience in AUDIENCES:
        prof = AUDIENCES[angle.audience]
        lines.append(f"- 目标读者：{angle.audience}（核心痛点：{prof['痛点主题']}）")
    elif angle.audience:
        lines.append(f"- 目标读者：{angle.audience}")
    dims = [d for d in effective_sellpoints(angle) if d in _DIM_LABEL]
    if dims:
        labels = "、".join(_DIM_LABEL[d] for d in dims)
        lines.append(f"- 主打卖点：{labels}（优先展开、突出差异）")
    if angle.tone and angle.tone in TONES:
        lines.append(f"- 语调：{angle.tone} —— {TONES[angle.tone]}")
    lines.append("请据此组织素材的详略与顺序；不得新增或改动任何参数/数字/认证。")
    return "\n".join(lines)
