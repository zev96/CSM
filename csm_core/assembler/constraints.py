"""Orchestrate sampling over a template DAG (topological order)."""
from __future__ import annotations
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..template.schema import Template, TestResultsAlignedSource
from .plan import AssemblyPlan, SlotAssignment
from .sampler import sample_slot


def _topo_order(template: Template) -> list[str]:
    """Return slot ids in topological order (deps first)."""
    in_deg = {s.id: 0 for s in template.slots}
    graph: dict[str, list[str]] = {s.id: [] for s in template.slots}
    for s in template.slots:
        for dep in s.depends_on:
            graph[dep].append(s.id)
            in_deg[s.id] += 1
    queue = [sid for sid, d in in_deg.items() if d == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt in graph[node]:
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                queue.append(nxt)
    return order


def _resolve_aligned_models(
    slot_id: str,
    source: TestResultsAlignedSource,
    assignments: dict[str, SlotAssignment],
) -> list[str]:
    follow_ids = source.follow_slot.split("+")
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


def assemble_plan(
    *,
    keyword: str,
    template: Template,
    index: VaultIndex,
    registry: BrandRegistry,
    seed: int,
    user_config: dict[str, int],
) -> AssemblyPlan:
    order = _topo_order(template)
    slot_map = {s.id: s for s in template.slots}
    assignments: dict[str, SlotAssignment] = {}
    warnings: list[str] = []

    for slot_id in order:
        slot = slot_map[slot_id]
        aligned: list[str] | None = None
        if isinstance(slot.source, TestResultsAlignedSource):
            aligned = _resolve_aligned_models(slot.id, slot.source, assignments)
        picks = sample_slot(
            slot, index, registry, seed=seed, user_config=user_config,
            aligned_models=aligned,
        )
        missing = [p for p in picks if p.meta.get("missing")]
        if missing:
            warnings.append(
                f"slot '{slot.id}': {len(missing)} 测试数据缺失 ({[p.note_id for p in missing]})"
            )
        assignments[slot_id] = SlotAssignment(slot_id=slot_id, picks=picks)

    rendered_slots = [assignments[sid] for sid in template.render_order]
    return AssemblyPlan(
        keyword=keyword,
        template_id=template.id,
        seed=seed,
        slots=rendered_slots,
        warnings=warnings,
    )
