"""Per-platform concurrency semaphore lifecycle.

Regression guard for the "settings-save during an active run silently doubles
the concurrency cap" bug: apply_settings() calls configure_concurrency(baidu, 1)
on every config save. If that unconditionally installs a fresh Semaphore, an
in-flight worker holds the OLD semaphore (count 0) while a newly-dispatched
worker acquires the NEW one (count 1) → two concurrent runs on the same Chrome
profile, and on release the cap drifts to 2 permanently. Re-configuring with an
unchanged cap must be a no-op.
"""
from __future__ import annotations

from csm_core.browser_infra import rate_limit as rl


def test_configure_concurrency_noop_when_cap_unchanged():
    plat = "test_plat_unchanged"
    rl.configure_concurrency(plat, 1)
    sem1 = rl._get_sem(plat)  # noqa: SLF001
    rl.configure_concurrency(plat, 1)  # same cap → must not swap the object
    sem2 = rl._get_sem(plat)  # noqa: SLF001
    assert sem1 is sem2, "同 cap 重复配置不该换信号量对象（会重置在途计数）"


def test_configure_concurrency_swaps_when_cap_changes():
    plat = "test_plat_changed"
    rl.configure_concurrency(plat, 1)
    sem1 = rl._get_sem(plat)  # noqa: SLF001
    rl.configure_concurrency(plat, 2)  # changed → new semaphore
    sem2 = rl._get_sem(plat)  # noqa: SLF001
    assert sem1 is not sem2


def test_configure_concurrency_preserves_inflight_count_on_noop():
    """在途占用 1 个 slot 时，同 cap 重配不能把可用数复位。"""
    plat = "test_plat_inflight"
    rl.configure_concurrency(plat, 1)
    assert rl.acquire_slot(plat, timeout=1) is True  # 占满（cap=1）
    rl.configure_concurrency(plat, 1)  # 同 cap 重配
    # 若信号量被替换，这里会拿到新对象的空闲 slot → 并发翻倍。必须拿不到。
    assert rl.acquire_slot(plat, timeout=0.2) is False
    rl.release_slot(plat)
