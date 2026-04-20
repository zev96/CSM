"""Pure function to reroll a single slot plus its downstream dependents."""
from __future__ import annotations
import zlib
from collections import deque
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment
from csm_core.assembler.sampler import sample_slot
from csm_core.template.schema import Template, TestResultsAlignedSource
from csm_core.vault.scanner import VaultIndex
from csm_core.vault.brand_registry import BrandRegistry


def _downstream(template: Template, root_id: str) -> list[str]:
    """Return [root_id, ...dependents] in render_order-stable topo sequence.

    Forward edges: A -> B when B.depends_on contains A.
    BFS from root_id; filter/reorder results by template.render_order so
    slots not in render_order are implicitly dropped.
    """
    forward: dict[str, list[str]] = {s.id: [] for s in template.slots}
    for s in template.slots:
        for dep in s.depends_on:
            if dep in forward:
                forward[dep].append(s.id)

    seen: set[str] = set()
    queue: deque[str] = deque([root_id])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        for nxt in forward.get(node, []):
            if nxt not in seen:
                queue.append(nxt)

    return [sid for sid in template.render_order if sid in seen]


def _resolve_aligned_models(
    follow_slot: str,
    assignments: dict[str, SlotAssignment],
) -> list[str]:
    follow_ids = follow_slot.split("+")
    models: list[str] = []
    for fid in follow_ids:
        slot_a = assignments.get(fid)
        if not slot_a:
            continue
        for p in slot_a.picks:
            m = p.meta.get("model")
            if m and m not in models:
                models.append(m)
    return models


def reroll_slot(
    *,
    slot_id: str,
    template: Template,
    index: VaultIndex,
    registry: BrandRegistry,
    current_plan: AssemblyPlan,
    counter: int,
    user_config: dict,
) -> AssemblyPlan:
    """Resample slot_id plus all transitive dependents; preserve other picks."""
    slot_map = {s.id: s for s in template.slots}
    if slot_id not in slot_map:
        raise ValueError(f"unknown slot_id '{slot_id}'")

    # Start from current plan's assignments (shallow copy — we only replace whole entries).
    assignments: dict[str, SlotAssignment] = {s.slot_id: s for s in current_plan.slots}

    derived_key = f"{current_plan.seed}-{slot_id}-{counter}"
    derived_seed = zlib.crc32(derived_key.encode("utf-8"))

    to_refresh = _downstream(template, slot_id)
    warnings: list[str] = list(current_plan.warnings)
    for sid in to_refresh:
        slot = slot_map[sid]
        aligned: list[str] | None = None
        if isinstance(slot.source, TestResultsAlignedSource):
            aligned = _resolve_aligned_models(slot.source.follow_slot, assignments)
        picks = sample_slot(
            slot, index, registry,
            seed=derived_seed, user_config=user_config,
            aligned_models=aligned,
        )
        assignments[sid] = SlotAssignment(slot_id=sid, picks=picks)

    rendered = [assignments[sid] for sid in template.render_order if sid in assignments]
    return AssemblyPlan(
        keyword=current_plan.keyword,
        template_id=current_plan.template_id,
        seed=current_plan.seed,
        slots=rendered,
        warnings=warnings,
    )
