"""禁区 lint 服务：读 config 覆盖 → 引擎 scan/autofix → dict。纯计算、不写盘。"""
from __future__ import annotations
from typing import Any

from csm_core.lint import build_report, build_rules

from . import config_service


def scan_text(text: str) -> dict[str, Any]:
    cfg = config_service.load()
    lint_cfg = cfg.lint
    if not lint_cfg.enabled:
        return {"hits": [], "fixed_text": text or ""}
    rules = build_rules(lint_cfg)
    return build_report(text or "", rules).model_dump()
