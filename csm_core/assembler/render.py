"""Public rendering helpers for AssemblyPlan."""
from __future__ import annotations
from .plan import AssemblyPlan


def compose_draft(plan: AssemblyPlan) -> str:
    """Render an AssemblyPlan into the nested-join draft text.

    Slots with no picks are skipped. Picks within a slot are joined by
    blank lines; slots are separated by blank lines.
    """
    parts: list[str] = []
    for slot in plan.slots:
        if not slot.picks:
            continue
        parts.append("\n\n".join(p.text for p in slot.picks))
    return "\n\n".join(parts)
