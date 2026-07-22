"""Orchestrate block-level sampling.

For paragraph blocks with depends_on, the dependency graph is
respected (topological order over paragraph ids). Non-paragraph
blocks run in declaration order and never participate in the
dependency graph.
"""
from __future__ import annotations
import random
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..template.schema import (
    Template, ParagraphBlock, TestResultsAlignedSource, TestFrameworkBlock,
)
from csm_core.angle.model import Angle
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


def _resolve_follow_models(
    follow_slot: str, results_by_id: dict[str, BlockResult],
) -> list[str]:
    """Walk a ``hero_a+pool_a`` follow_slot string and return the models
    those blocks selected, in order. Hero blocks contribute 1 model;
    pool blocks contribute their picks in order; other blocks are
    ignored. Duplicates are de-duplicated while preserving order.

    For competitor_pool picks we prefer ``meta['title']`` over
    ``meta['model']`` because the latter is the raw ``型号`` frontmatter
    value, which often carries a "竞品-" category prefix (e.g.
    ``型号: 竞品-米家3C``). Using the raw value would:
        1. Break the brand-result lookup (it filters on ``型号: 米家3C``
           in the results module — no match for ``竞品-米家3C``).
        2. Leak the "竞品-" prefix into inline-substituted prose like
           "测试排名：CEWEY DS18 > 竞品-米家3C > …".
    ``_clean_competitor_title`` already strips the prefix on the way in;
    the cleaned form lives on ``meta['title']``.
    """
    seen: set[str] = set()
    models: list[str] = []
    for fid in follow_slot.split("+"):
        fid = fid.strip()
        if not fid:
            continue
        r = results_by_id.get(fid)
        if r is None:
            continue
        if r.kind == "hero_brand":
            # Hero blocks store the model on text or in meta — try both.
            m = r.meta.get("model") or (r.text.strip() if r.text else "")
            if m and m not in seen:
                seen.add(m)
                models.append(m)
        elif r.kind == "competitor_pool":
            for p in r.picks:
                # Prefer the cleaned title (without "竞品-" prefix);
                # fall back to raw model only if title is missing.
                m = p.meta.get("title") or p.meta.get("model") or p.note_id
                if m and m not in seen:
                    seen.add(m)
                    models.append(m)
        else:
            # Generic — try meta.title first (cleaned), then model.
            for p in r.picks:
                m = p.meta.get("title") or p.meta.get("model")
                if m and m not in seen:
                    seen.add(m)
                    models.append(m)
    return models


def _sample_test_framework(
    block: TestFrameworkBlock, *,
    index: VaultIndex, registry: BrandRegistry,
    seed: int, results_by_id: dict[str, BlockResult],
    warnings: list[str],
) -> BlockResult:
    """Sample a TestFrameworkBlock — random N test items × per-brand fill.

    Returns a ``BlockResult`` whose ``text`` is the concatenated, slot-
    filled markdown. The renderer treats this as a ``literal``-shaped
    output (just emits ``text`` verbatim).
    """
    from csm_core.test_framework import (
        sample_test_framework_block, TestFrameworkConfig,
    )

    follow_models = _resolve_follow_models(block.follow_slot, results_by_id)
    if not follow_models:
        warnings.append(
            f"block '{block.id}': follow_slot {block.follow_slot!r} 没有解析出任何"
            f" 产品 — 槽位会显示「缺数据：未选中产品」"
        )

    pick_count = block.pick_count
    if hasattr(pick_count, "model_dump"):  # PickCountSpec
        spec = pick_count.model_dump()
        if spec.get("random_between"):
            lo, hi = spec["random_between"]
            pick_count = random.Random(f"{seed}-{block.id}-pc").randint(lo, hi)
        elif spec.get("default") is not None:
            pick_count = int(spec["default"])
        else:
            pick_count = 3
    else:
        pick_count = int(pick_count or 3)

    cfg = TestFrameworkConfig(
        framework_module=block.framework_module,
        results_module=block.results_module,
        pick_count=pick_count,
        hero_slot=block.hero_slot,
        competitor_slots=tuple(block.competitor_slots),
        unique_notes="unique_notes" in (block.constraints or []),
        number_style=block.number_style,
    )
    rng = random.Random(f"{seed}-{block.id}")
    text, sub_warnings = sample_test_framework_block(
        cfg=cfg, follow_models=follow_models,
        vault=index, brand_of=registry.brand_of, rng=rng,
    )
    for w in sub_warnings:
        warnings.append(f"block '{block.id}': {w}")

    return BlockResult(
        block_id=block.id, kind="test_framework", text=text,
        meta={
            "framework_module": block.framework_module,
            "results_module": block.results_module,
            "follow_slot": block.follow_slot,
            "pick_count": pick_count,
        },
    )


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


def draw_versions(
    template: Template, *, seed: int,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """每个版本组抽一次签，返回 {group_id: option}。

    - 命名空间 ``{seed}::version::{gid}`` 与块 RNG key ``{seed}-{block.id}``
      不可能撞串（后者不含 ``::``），所以版本抽签不会与任何块的随机流相关。
    - ``overrides`` 优先（生成表单指定版本 / 「重新随机」锁版本时传入）；
      非法值直接忽略，退回抽签，不让脏输入把生成打挂。
    - 被禁用的 option 不进抽签池（素材没铺齐的版本先别抽中）。
    """
    choices: dict[str, str] = {}
    overrides = overrides or {}
    for group in template.version_groups:
        forced = overrides.get(group.id)
        if forced and forced in group.options:
            choices[group.id] = forced
            continue
        pool = group.enabled_options()
        rng = random.Random(f"{seed}::version::{group.id}")
        choices[group.id] = rng.choice(pool)
    return choices


def assemble_plan(
    *, keyword: str, template: Template,
    index: VaultIndex, registry: BrandRegistry,
    seed: int, user_config: dict[str, int],
    core_keyword: str | None = None,
    angle: Angle | None = None,
    note_weights: dict[str, float] | None = None,
    version_overrides: dict[str, str] | None = None,
    version_seed: int | None = None,
) -> AssemblyPlan:
    """Assemble a draft plan.

    ``keyword`` is the full search term (long-tail) — used for SEO title
    generation. ``core_keyword`` is the bare product noun extracted from
    it ("无线吸尘器" out of "无线吸尘器哪款好用") — used inside the
    rendered draft for ``{keyword}`` substitution and brand-title append.
    When omitted, the extractor runs to derive it automatically; pass it
    explicitly when the user has manually overridden the auto-detection.

    ``version_seed`` 让版本抽签用一个与 ``seed`` 不同的种子。批量候选靠
    它保持「K 个候选同版本」：候选各自 seed 间隔 1000（素材各自随机），
    但版本抽签统一用批次基准 seed —— 否则候选会落在不同结构上，而评分
    是绝对次数扣分制（不按篇幅归一），长版本会被系统性打低分，候选对比
    失去意义。缺省 = 跟随 ``seed``。
    """
    from csm_core.keyword import extract_core
    if core_keyword is None:
        core_keyword = extract_core(keyword)
    results_by_id: dict[str, BlockResult] = {}
    warnings: list[str] = []

    version_choices = draw_versions(
        template,
        seed=version_seed if version_seed is not None else seed,
        overrides=version_overrides,
    )
    active_blocks = [
        b for b in template.blocks if template.is_visible(b, version_choices)
    ]

    def sample_paragraph_tree(p: ParagraphBlock) -> BlockResult:
        aligned = None
        if isinstance(p.source, TestResultsAlignedSource):
            aligned = _resolve_aligned_models(p.id, p.source, results_by_id)
        r = sample_block(
            p, index, registry, seed=seed, user_config=user_config,
            aligned_models=aligned, angle=angle, note_weights=note_weights,
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
    # 跨池竞品排除：深浅双池（TOP2-3 详细 / TOP4-10 简略）不能重复出同一款
    # 产品。必须在**采样期**排除 —— 渲染期无 RNG 无索引，发现重复只能丢卡，
    # 榜单就静默缩水，而且 pick 下标会与渲染项错位（reroll 寻址跟着崩）。
    picked_competitor_keys: set[str] = set()
    for b in active_blocks:
        if isinstance(b, ParagraphBlock):
            top.append(sample_paragraph_tree(b))
        elif isinstance(b, TestFrameworkBlock):
            r = _sample_test_framework(
                b, index=index, registry=registry,
                seed=seed, results_by_id=results_by_id,
                warnings=warnings,
            )
            results_by_id[b.id] = r
            top.append(r)
        else:
            r = sample_block(
                b, index, registry, seed=seed, user_config=user_config,
                angle=angle, note_weights=note_weights,
                exclude_competitor_keys=picked_competitor_keys,
            )
            if r.meta.get("card") and r.kind == "competitor_pool":
                picked_competitor_keys.update(r.meta.get("competitor_keys") or [])
                for w in r.meta.get("roster_warnings") or []:
                    warnings.append(f"block '{b.id}': {w}")
            if r.note:
                warnings.append(f"block '{b.id}': {r.note}")
            results_by_id[b.id] = r
            top.append(r)

    return AssemblyPlan(
        keyword=keyword, core_keyword=core_keyword,
        template_id=template.id, seed=seed,
        results=top, warnings=warnings, angle=angle,
        version_choices=version_choices,
    )
