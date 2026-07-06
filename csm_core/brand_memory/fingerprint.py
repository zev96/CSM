"""型号参数指纹 —— 只对『会传导的事实』（参数 specs + 认证 certs）建线。

scripts / tests / endorsements / intro 的变化**不算**事实变更（§7.1）：指纹只覆盖
注入/白名单关心的参数与认证，避免『改了话术』被误报成『参数变了』。占位值
（is_placeholder，缺口体检常态）不参与——占位不是事实。
"""
from __future__ import annotations

import hashlib
import json

from csm_core.brand_memory.model import BrandModelMemory


def spec_fingerprint(memory: BrandModelMemory) -> tuple[str, str]:
    """返回 ``(sha256hex, canonical_specs_json)``。

    canonical = ``{"specs": sorted [[field, raw]] 非占位对, "certs": sorted list}``。
    排序保证顺序无关；分隔符固定，跨进程稳定可比。
    """
    specs = sorted(
        [sv.field, sv.raw]
        for sv in memory.specs.values()
        if not sv.is_placeholder
    )
    certs = sorted(memory.certs)
    canonical = json.dumps(
        {"specs": specs, "certs": certs},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest, canonical


def diff_canonical(old_json: str | None, new_json: str) -> list[dict]:
    """比两份 canonical specs_json，产出 ``[{field, old, new}]``。

    - specs 逐字段增（old=None）/ 删（new=None）/ 改（都在且不等）；
    - certs 整体作为一条 ``field='认证'``（old/new = 顿号连接的串，空则 None）。

    ``old_json`` 为空或解析失败 → 返回 ``[]``（视作首建，调用方决定是否报变更）。
    """
    try:
        old = json.loads(old_json) if old_json else None
    except (ValueError, TypeError):
        old = None
    # None / 空 / 坏 JSON / 合法但非对象（数组、标量）都视作首建 —— 兑现 docstring
    # 承诺的优雅降级，不让 old.get() 在非 dict 上硬崩（对抗审查发现）。
    if not isinstance(old, dict):
        return []
    try:
        new = json.loads(new_json)
    except (ValueError, TypeError):
        new = {}
    if not isinstance(new, dict):
        new = {}

    changes: list[dict] = []
    old_specs = {f: r for f, r in old.get("specs", [])}
    new_specs = {f: r for f, r in new.get("specs", [])}
    for field in sorted(set(old_specs) | set(new_specs)):
        ov, nv = old_specs.get(field), new_specs.get(field)
        if ov != nv:
            changes.append({"field": field, "old": ov, "new": nv})

    old_certs = list(old.get("certs", []))
    new_certs = list(new.get("certs", []))
    if old_certs != new_certs:
        changes.append({
            "field": "认证",
            "old": "、".join(old_certs) if old_certs else None,
            "new": "、".join(new_certs) if new_certs else None,
        })
    return changes
