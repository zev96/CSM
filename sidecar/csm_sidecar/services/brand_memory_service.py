"""Read-only brand/model memory API service (Phase 1 Plan 5a).

镜像 skills_service 的只读约定。复用 Plan 1 resolver + Plan 3 render_brand_facts，
零改既有生成链。列表一次 scan_vault + build_brand_registry，对每型号
resolve_memory(复用 index) 取 coverage；详情额外渲染注入预览。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from csm_core.brand_memory.identity import parse_brand_model
from csm_core.brand_memory.inject import ModelScope, render_brand_facts
from csm_core.brand_memory.model import BrandModelMemory
from csm_core.brand_memory.resolver import resolve_memory
from csm_core.vault.brand_registry import BrandRegistry, build_brand_registry
from csm_core.vault.scanner import VaultIndex, scan_vault


def _resolve_one(
    model_full: str, registry: BrandRegistry, index: VaultIndex,
    category: str, own_brands: set[str],
) -> tuple[str, BrandModelMemory] | None:
    brand = registry.brand_of(model_full)
    if brand is None:
        return None
    # registry 存 full-stem（CEWEYDS18）；resolver 期望品牌剥离（DS18）。
    # 边界：frontmatter-only 的未知品牌 parse 不出前缀 → 回退 full-stem，
    # resolver spec-match 落空 → 空记忆（coverage.has_specs=False），不崩。
    parsed = parse_brand_model(model_full)
    resolver_model = parsed[1] if parsed is not None else model_full
    mem = resolve_memory(brand, resolver_model, category, index, own_brands=own_brands)
    return brand, mem


def list_models(
    vault_root: Path, *, category: str, own_brands: set[str],
) -> list[dict[str, Any]]:
    """全 (品牌, 型号) + role + 缺口体检（一次 scan，复用 index）。"""
    index = scan_vault(vault_root)
    registry = build_brand_registry(vault_root)
    out: list[dict[str, Any]] = []
    for model_full in registry.all_models():
        resolved = _resolve_one(model_full, registry, index, category, own_brands)
        if resolved is None:
            continue
        brand, mem = resolved
        out.append({
            "model": model_full,
            "brand": brand,
            "role": mem.role,            # 主推 | 竞品
            "coverage": mem.coverage,
        })
    return out


def get_model_detail(
    vault_root: Path, model_full: str, *,
    category: str, own_brands: set[str],
    variant_cap: int, endorsement_cap: int,
) -> dict[str, Any] | None:
    """单型号完整记忆 + 注入预览；registry 不识别 → None（路由转 404）。"""
    index = scan_vault(vault_root)
    registry = build_brand_registry(vault_root)
    resolved = _resolve_one(model_full, registry, index, category, own_brands)
    if resolved is None:
        return None
    brand, mem = resolved
    scope = ModelScope(brand=brand, model=model_full, role=mem.role, memory=mem)
    preview = render_brand_facts(
        [scope], variant_cap=variant_cap, endorsement_cap=endorsement_cap)
    d = mem.model_dump()
    d["model_full"] = model_full
    d["inject_preview"] = preview
    return d
