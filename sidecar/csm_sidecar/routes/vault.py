"""Vault scanning + note query routes."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from csm_core.vault.brand_registry import build_brand_registry

from ..auth import RequireToken
from ..services import config_service, fact_service, vault_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vault"], dependencies=[RequireToken])


class VaultScanRequest(BaseModel):
    # Optional — if absent we use AppConfig.vault_root. Letting callers
    # override is useful for "preview a different folder before saving"
    # flows in settings.
    root: str | None = Field(default=None, description="Vault root directory")


class VaultScanResponse(BaseModel):
    root: str
    note_count: int
    warnings: list[str]


@router.post("/api/vault/scan", response_model=VaultScanResponse)
def scan_vault(body: VaultScanRequest) -> VaultScanResponse:
    root_str = body.root or config_service.load().vault_root
    if not root_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no vault_root configured; pass body.root or set AppConfig.vault_root",
        )
    root = Path(root_str)
    if not root.exists() or not root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"vault root not found: {root}",
        )
    index = vault_service.scan(root)
    # 事实传导（§7.2）：重建索引后检测型号参数变更，入 pending 队列供前端拉
    # /api/facts/changes → 通知。fail-safe：检测失败不影响扫描结果。
    try:
        fact_service.detect_changes(index, build_brand_registry(root))
    except Exception:
        logger.debug("vault scan fact detect failed", exc_info=True)
    return VaultScanResponse(**vault_service.index_summary(index))


@router.get("/api/vault/dirs")
def list_dirs() -> dict[str, Any]:
    """List leaf directories under vault_root that directly contain .md files.

    Mirrors ``csm_gui.widgets.slot_tree_widget._scan_vault_dirs`` —
    返回的是「叶子目录」（其它已收录目录的父目录会被剥掉），用于级联文件夹
    选择器。前端拿到后按 ``/`` 拆分组成树。
    """
    cfg = config_service.load()
    root_str = cfg.vault_root
    if not root_str:
        return {"root": "", "dirs": []}
    root = Path(root_str)
    if not root.exists() or not root.is_dir():
        return {"root": str(root), "dirs": []}

    skip_dirs = {".git", ".obsidian", "node_modules", "__pycache__", ".venv"}
    candidates: list[str] = []
    try:
        for p in sorted(root.rglob("*")):
            if not p.is_dir():
                continue
            try:
                rel_parts = p.relative_to(root).parts
            except ValueError:
                continue
            if any(part.startswith(".") or part in skip_dirs for part in rel_parts):
                continue
            try:
                if not any(c.suffix == ".md" for c in p.iterdir() if c.is_file()):
                    continue
            except OSError:
                continue
            candidates.append("/".join(rel_parts))
            if len(candidates) >= 500:
                break
    except OSError:
        pass

    cset = set(candidates)
    leaves = sorted(
        d for d in candidates
        if not any(other.startswith(d + "/") for other in cset)
    )
    return {"root": str(root), "dirs": leaves}


@router.get("/api/vault/notes")
def list_notes(
    module: str | None = Query(default=None, description="Module path filter, e.g. '营销资料库/标题模块'"),
) -> dict[str, Any]:
    """List notes from the most recent scan. Returns 409 if no scan yet."""
    index = vault_service.cached()
    if index is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no vault index yet; call POST /api/vault/scan first",
        )
    notes = index.query(module=module) if module else index.notes
    return {
        "root": str(index.root),
        "module": module,
        "count": len(notes),
        "notes": [vault_service.note_to_dict(n) for n in notes],
    }


class CardSectionSpec(BaseModel):
    label: str
    h2: str = ""
    required: bool = True


class CardCoverageRequest(BaseModel):
    """竞品卡覆盖度检查入参 —— 与 CompetitorPoolBlock 的卡片配置同形。"""

    module: str
    filter: dict[str, Any] = Field(default_factory=dict)
    sections: list[CardSectionSpec] = Field(default_factory=list)
    tier_key: str = "层级标签"


@router.post("/api/vault/card_coverage")
def card_coverage(body: CardCoverageRequest) -> dict[str, Any]:
    """竞品卡的覆盖度对照表 —— 写模板时就能看到谁缺料、型号写歪没有。

    生成期的告警只说「缺什么」，不说「绑到了谁」；这里把「文件 → 判定身份
    → 每个小节命中的 H2 原文」整张表摊开，型号写法不一致、H2 名对不上、
    文件名 stem 撞车都当场可见（stem 撞车会让重随串到别家竞品、反馈权重
    合桶，因为全仓按文件名寻址）。

    先做一次增量刷新再查 —— 运营刚在共享盘补完素材就点检查，读缓存会看到
    旧结果。
    """
    from collections import defaultdict

    from csm_core.assembler.cards import _note_sections, find_card_section
    from csm_core.brand_memory.identity import (
        normalize_model_key, note_identity, strip_competitor_prefix,
    )
    from csm_core.template.schema import CompetitorSection

    if not body.module.strip():
        # 空 module 在 VaultIndex.query 里等于「整个资料库」—— 几千篇笔记逐篇
        # 解析 H2 再全量回传，界面直接卡死，而且结论全是噪音。
        raise HTTPException(status_code=400, detail="请先给竞品池选目录")
    blank = [i + 1 for i, s in enumerate(body.sections) if not s.label.strip()]
    if blank:
        raise HTTPException(
            status_code=400, detail=f"第 {blank} 个小节还没填名字",
        )
    if not body.sections:
        raise HTTPException(status_code=400, detail="请先添加小节")

    cfg = config_service.load()
    try:
        index = vault_service.get(Path(cfg.vault_root))
    except Exception as e:      # 目录不存在 / 权限问题
        raise HTTPException(status_code=400, detail=f"扫描资料库失败：{e}") from e

    specs = [
        CompetitorSection(label=s.label, h2=s.h2, required=s.required)
        for s in body.sections
    ]
    notes = index.query(module=body.module, filters=body.filter)

    # stem 冲突按全仓统计（笔记 id 是全库唯一的寻址键），但只上报与本池命中
    # 笔记相关的那些 —— 全仓 README.md 同名是常态，全报会刷出一片无关红字。
    stems: dict[str, list[str]] = defaultdict(list)
    for n in index.notes:
        stems[n.id].append(str(n.path))
    scoped_stems = {n.id for n in notes}

    rows: list[dict[str, Any]] = []
    no_identity: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for note in sorted(notes, key=lambda n: str(n.path)):
        fm = note.frontmatter or {}
        ident = note_identity(note.id, fm)
        has_ids = bool(str(fm.get("品牌") or "").strip()) and bool(
            str(fm.get("型号") or "").strip()
        )
        if not ident or not has_ids:
            no_identity.append(str(note.path))
            continue
        brand, raw_model = ident
        key = f"{normalize_model_key(brand)}::{normalize_model_key(raw_model)}"
        found = _note_sections(note)
        matched: dict[str, str | None] = {}
        for spec in specs:
            hit = find_card_section(found, spec.topic())
            matched[spec.label] = hit.raw_title if hit and hit.body.strip() else None
        missing_required = [
            s.label for s in specs if s.required and matched.get(s.label) is None
        ]
        row = {
            "path": str(note.path),
            "stem": note.id,
            "brand": brand,
            "model": strip_competitor_prefix(raw_model),
            "identity_key": key,
            "tier": str(fm.get(body.tier_key) or "").strip(),
            "h2_present": [s.raw_title for s in found],
            "matched": matched,
            "missing_required": missing_required,
            "eligible": not missing_required,
            "stem_conflict": len(stems.get(note.id, [])) > 1,
        }
        rows.append(row)
        groups[key].append(row)

    competitors = [
        {
            "identity_key": key,
            "title": (
                f"{cards[0]['brand']} {cards[0]['model']}"
                if not cards[0]["model"].startswith(cards[0]["brand"])
                else cards[0]["model"]
            ),
            "eligible": any(c["eligible"] for c in cards),
            "card_count": len(cards),
            "eligible_card_count": sum(1 for c in cards if c["eligible"]),
            "tiers": sorted({c["tier"] for c in cards if c["tier"]}),
        }
        for key, cards in groups.items()
    ]
    # 疑似同款：型号只差连字符/下划线 → 会各占一个排位
    loose: dict[str, list[str]] = defaultdict(list)
    for c in competitors:
        loose[c["identity_key"].replace("-", "").replace("_", "")].append(c["title"])
    near_duplicates = [v for v in loose.values() if len(v) > 1]

    return {
        "module": body.module,
        "filter": body.filter,
        "note_count": len(notes),
        "eligible_count": sum(1 for c in competitors if c["eligible"]),
        "competitors": sorted(competitors, key=lambda c: c["title"]),
        "rows": rows,
        "notes_missing_identity": no_identity,
        "stem_conflicts": sorted(
            [
                {"stem": k, "paths": v}
                for k, v in stems.items()
                if len(v) > 1 and k in scoped_stems
            ],
            key=lambda d: d["stem"],
        ),
        "near_duplicates": near_duplicates,
    }


@router.get("/api/vault/attributes")
def list_attributes(
    module: str | None = Query(
        default=None,
        description="Scope to notes whose path is under this module, e.g. '营销资料库/产品模块/吸尘器'",
    ),
) -> dict[str, Any]:
    """Aggregate distinct frontmatter keys across the (optionally scoped) note set.

    Drives the BlockEditor 筛选 dropdown: instead of having the user type
    attribute names like "素材类型" from memory, the UI shows a select
    populated from the actual keys present in the Vault.

    For each key we also collect a *sample* of its distinct values (capped
    at 20 per key — beyond that the dropdown would be a wall of text, and
    free-text input is more useful for high-cardinality keys like titles).

    Returns 409 if no scan has been run yet (same convention as /notes).
    """
    index = vault_service.cached()
    if index is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no vault index yet; call POST /api/vault/scan first",
        )
    notes = index.query(module=module) if module else index.notes

    # key -> ordered set of stringified values (preserve insertion order to
    # be visually stable; users see "the values as they appear in disk").
    seen: dict[str, dict[str, None]] = {}
    counts: dict[str, int] = {}
    for n in notes:
        fm = n.frontmatter or {}
        for k, v in fm.items():
            if v is None or v == "":
                continue
            counts[k] = counts.get(k, 0) + 1
            bucket = seen.setdefault(k, {})
            # Lists in frontmatter (e.g. `tags: [a, b]`) — explode each entry.
            if isinstance(v, list):
                for item in v:
                    if item is None or item == "":
                        continue
                    bucket.setdefault(str(item), None)
            else:
                bucket.setdefault(str(v), None)

    attributes = [
        {
            "key": k,
            "note_count": counts[k],
            "value_count": len(seen[k]),
            # Cap to 20 per key —— a long dropdown of every distinct title
            # would be useless; UI falls back to free-text when truncated.
            "sample_values": list(seen[k].keys())[:20],
        }
        for k in sorted(seen.keys(), key=lambda x: (-counts[x], x))
    ]
    return {
        "root": str(index.root),
        "module": module,
        "count": len(notes),
        "attributes": attributes,
    }
