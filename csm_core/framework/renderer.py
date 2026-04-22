"""Render an AssemblyPlan through a Framework into final draft text."""
from __future__ import annotations
import re
from ..assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from .schema import (
    Framework, ParagraphBlock, HeadingBlock, NumberedListBlock,
    BrandReasonListBlock, LiteralBlock,
)
from .trace import FrameworkTrace


class FrameworkRenderError(Exception):
    """Raised when rendering cannot proceed (e.g. missing variable)."""


class FrameworkValidationError(Exception):
    """Raised when framework references structures that don't exist in the plan."""


_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _substitute(text: str, variables: dict[str, str], declared: set[str]) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in declared:
            return m.group(0)
        if name not in variables:
            raise FrameworkRenderError(f"missing required variable '{name}'")
        return variables[name]
    return _VAR_RE.sub(repl, text)


def _validate_slots(plan: AssemblyPlan, framework: Framework) -> dict[str, SlotAssignment]:
    by_id = {s.slot_id: s for s in plan.slots}
    for i, b in enumerate(framework.blocks):
        refs: list[str] = []
        if isinstance(b, (ParagraphBlock, NumberedListBlock)):
            refs = [b.slot]
        elif isinstance(b, BrandReasonListBlock):
            refs = list(b.slots)
        for sid in refs:
            if sid not in by_id:
                raise FrameworkValidationError(
                    f"block[{i}] references unknown slot '{sid}'"
                )
    return by_id


def render_with_framework(
    plan: AssemblyPlan,
    framework: Framework,
    variables: dict[str, str],
    trace: FrameworkTrace | None = None,
) -> str:
    by_id = _validate_slots(plan, framework)
    declared = set(framework.variables)
    parts: list[str] = []

    for i, b in enumerate(framework.blocks):
        out = _render_block(b, i, by_id, variables, declared, trace)
        if out is not None:
            parts.append(out)
    return "\n\n".join(parts)


def _render_block(
    b, index: int,
    by_id: dict[str, SlotAssignment],
    variables: dict[str, str],
    declared: set[str],
    trace: FrameworkTrace | None,
) -> str | None:
    if isinstance(b, HeadingBlock):
        text = _substitute(b.text, variables, declared)
        prefix = "#" * b.level
        if b.index:
            return f"{prefix} {b.index}、{text}"
        return f"{prefix} {text}"

    if isinstance(b, LiteralBlock):
        return _substitute(b.text, variables, declared)

    if isinstance(b, ParagraphBlock):
        slot = by_id[b.slot]
        if not slot.picks:
            if trace is not None:
                trace.skipped_empty_slot(b.slot, index)
            return None
        return "\n\n".join(p.text for p in slot.picks)

    if isinstance(b, NumberedListBlock):
        slot = by_id[b.slot]
        if not slot.picks:
            if trace is not None:
                trace.skipped_empty_slot(b.slot, index)
            return None
        return "\n".join(f"{i + 1}. {p.text}" for i, p in enumerate(slot.picks))

    # BrandReasonListBlock → next task
    raise NotImplementedError(f"block kind {type(b).__name__}")
