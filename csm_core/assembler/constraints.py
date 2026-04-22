"""Orchestrate block-level sampling.

For paragraph blocks with depends_on, the dependency graph is
respected (topological order over paragraph ids). Non-paragraph
blocks run in declaration order and never participate in the
dependency graph.
"""
from __future__ import annotations
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..template.schema import (
    Template, ParagraphBlock, TestResultsAlignedSource,
)
from .plan import AssemblyPlan, BlockResult
from .sampler import sample_block


def _collect_paragraph_ids(blocks) -> list[str]:
    out: list[str] = []
    def walk(items):
        for b in items:
            if isinstance(b, ParagraphBlock):
                out.append(b.id)
                walk(b.children)
    walk(blocks)
    return out


def _resolve_aligned_models(
    block_id: str, source: TestResultsAlignedSource,
    results_by_id: dict[str, BlockResult],
) -> list[str]:
    follow_ids = source.follow_slot.split("+")
    models: list[str] = []
    for fid in follow_ids:
        r = results_by_id.get(fid)
        if not r:
            continue
        for p in r.picks:
            m = p.meta.get("model")
            if m and m not in models:
                models.append(m)
    return models


def assemble_plan(
    *, keyword: str, template: Template,
    index: VaultIndex, registry: BrandRegistry,
    seed: int, user_config: dict[str, int],
) -> AssemblyPlan:
    results_by_id: dict[str, BlockResult] = {}
    warnings: list[str] = []

    def sample_paragraph_tree(p: ParagraphBlock) -> BlockResult:
        aligned = None
        if isinstance(p.source, TestResultsAlignedSource):
            aligned = _resolve_aligned_models(p.id, p.source, results_by_id)
        r = sample_block(
            p, index, registry, seed=seed, user_config=user_config,
            aligned_models=aligned,
        )
        missing = [pk for pk in r.picks if pk.meta.get("missing")]
        if missing:
            warnings.append(
                f"block '{p.id}': {len(missing)} 测试数据缺失 "
                f"({[pk.note_id for pk in missing]})"
            )
        capped = next((pk for pk in r.picks if pk.meta.get("capped")), None)
        if capped is not None:
            note_text = (
                f"请求 {capped.meta['requested']} 条，"
                f"池内仅 {capped.meta['available']} 条可用"
            )
            r.note = note_text
            warnings.append(f"block '{p.id}': {note_text}")
        results_by_id[p.id] = r
        r.children = [sample_paragraph_tree(c) for c in p.children]
        return r

    top: list[BlockResult] = []
    for b in template.blocks:
        if isinstance(b, ParagraphBlock):
            top.append(sample_paragraph_tree(b))
        else:
            r = sample_block(b, index, registry, seed=seed, user_config=user_config)
            results_by_id[b.id] = r
            top.append(r)

    return AssemblyPlan(
        keyword=keyword, template_id=template.id, seed=seed,
        results=top, warnings=warnings,
    )
