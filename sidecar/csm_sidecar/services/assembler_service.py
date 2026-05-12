"""Assembly-plan reroll: per-pick re-sampling without re-running the LLM.

The legacy GUI exposed reroll via signals on the article controller; the
sidecar replacement is a stateful cache keyed by ``job_id``. When a
generate job completes, ``cache_plan`` stores the AssemblyPlan
in-process; subsequent ``reroll(...)`` calls look it up, run
``csm_core.assembler.reroll.reroll_pick`` against it, recompute the
draft via ``compose_draft``, and return both the updated plan + the
new draft.

The cache is bounded (LRU-evicted) to avoid leaking memory across long
sessions — generate jobs are small dicts but VaultIndex isn't, and we
hold a reference to the entry's plan tree.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from csm_core.assembler.plan import AssemblyPlan
from csm_core.assembler.render import compose_draft
from csm_core.assembler.reroll import NoCandidatesError, reroll_pick
from csm_core.template.loader import load_template

from . import config_service, templates_service, vault_service

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    plan: AssemblyPlan
    template_id: str
    seed: int


# OrderedDict for cheap LRU semantics — re-insert on access bumps the key
# to the back; oldest evicted at the front.
_cache: "OrderedDict[str, _Entry]" = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 50


def cache_plan(job_id: str, plan: AssemblyPlan, *, template_id: str, seed: int) -> None:
    """Stash a freshly-built plan so reroll has something to operate on.

    Called from generate_service immediately after assemble_plan succeeds
    (before the LLM call) so even draft-only jobs retain reroll-ability.
    """
    with _lock:
        _cache[job_id] = _Entry(plan=plan, template_id=template_id, seed=seed)
        _cache.move_to_end(job_id)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)


def get_plan(job_id: str) -> _Entry | None:
    with _lock:
        entry = _cache.get(job_id)
        if entry is not None:
            _cache.move_to_end(job_id)
        return entry


def reroll(job_id: str, block_id: str, pick_index: int) -> dict[str, Any]:
    """Replace one pick in the cached plan, recompute draft, return both."""
    entry = get_plan(job_id)
    if entry is None:
        raise KeyError(f"unknown job_id: {job_id} (plan cache miss)")

    cfg = config_service.load()
    if not cfg.vault_root:
        raise ValueError("AppConfig.vault_root is unset")

    tpl_path = templates_service.resolve_dir() / f"{entry.template_id}.json"
    if not tpl_path.exists():
        raise FileNotFoundError(f"template not found: {entry.template_id}")
    template = load_template(tpl_path)

    # Reuse the most-recently-scanned VaultIndex if it's still around — a
    # fresh scan is cheap (sub-second on small vaults) but pointless when
    # the user just hit reroll seconds after generate completed.
    index = vault_service.cached()
    if index is None:
        index = vault_service.scan(Path(cfg.vault_root))

    try:
        new_plan = reroll_pick(
            entry.plan, block_id, pick_index, template, index,
        )
    except NoCandidatesError as e:
        # 400-like signal — the route translates this to HTTP 409 because
        # 400 already means "bad request shape" and "no candidates left"
        # is closer to "conflict with current state".
        raise NoCandidatesError(str(e)) from e

    draft = compose_draft(new_plan)

    # Persist the new plan back into the cache so chained rerolls work.
    with _lock:
        _cache[job_id] = _Entry(
            plan=new_plan,
            template_id=entry.template_id,
            seed=entry.seed,
        )
        _cache.move_to_end(job_id)

    return {
        "plan": new_plan.model_dump(),
        "draft": draft,
    }


def reset_for_test() -> None:
    """Test-only — wipe the cache between tests."""
    with _lock:
        _cache.clear()
