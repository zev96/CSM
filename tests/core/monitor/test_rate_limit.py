"""Tests for rate_limit — semaphores, pacer, breaker."""
from __future__ import annotations
import time
import threading

import pytest

# 直接指向真实实现模块:csm_core.monitor.rate_limit 已是 re-export shim
# (`from ...browser_infra.rate_limit import *`),而 `import *` 不导出下划线私有名,
# 故 shim 上没有 _sems/_max_concurrent/_pacers/_breakers。这些并发信号量/限速器/
# 熔断器的模块级单例真身都在 browser_infra.rate_limit,测试须复位真身。
from csm_core.browser_infra import rate_limit


@pytest.fixture(autouse=True)
def _reset_module_state():
    # Each test gets a clean view of the module-level singletons.
    rate_limit._sems.clear()
    rate_limit._max_concurrent.clear()
    rate_limit._pacers.clear()
    rate_limit._breakers.clear()


class TestConcurrency:
    def test_acquire_blocks_when_full(self):
        rate_limit.configure_concurrency("zhihu_question", 1)
        assert rate_limit.acquire_slot("zhihu_question", timeout=0.1) is True
        # Second acquire with the same cap of 1 must time out.
        assert rate_limit.acquire_slot("zhihu_question", timeout=0.1) is False
        rate_limit.release_slot("zhihu_question")

    def test_slot_context_manager_releases(self):
        rate_limit.configure_concurrency("xyz", 1)
        with rate_limit.slot("xyz", timeout=0.5):
            pass
        # Slot should be available again immediately after.
        assert rate_limit.acquire_slot("xyz", timeout=0.1) is True
        rate_limit.release_slot("xyz")

    def test_slot_raises_on_timeout(self):
        rate_limit.configure_concurrency("xyz", 1)
        rate_limit.acquire_slot("xyz")
        with pytest.raises(TimeoutError):
            with rate_limit.slot("xyz", timeout=0.05):
                pass
        rate_limit.release_slot("xyz")


class TestPacer:
    def test_first_call_does_not_sleep(self):
        p = rate_limit.RequestPacer(delay_min=0.05, delay_max=0.1)
        slept = p.wait()
        assert slept == 0.0

    def test_subsequent_call_inserts_delay(self):
        p = rate_limit.RequestPacer(delay_min=0.05, delay_max=0.05)
        p.wait()  # primes _last_request_at
        start = time.monotonic()
        p.wait()
        elapsed = time.monotonic() - start
        # Delay should be ~0.05s (single-value range pins it tight).
        assert 0.04 <= elapsed <= 0.5  # generous upper for slow CI


class TestBreaker:
    def test_opens_after_threshold(self):
        b = rate_limit.CircuitBreaker(failure_threshold=3, window_seconds=60, cool_off_seconds=60)
        assert b.allow() is True
        b.record_failure()
        b.record_failure()
        assert b.allow() is True  # only 2 failures, still closed
        b.record_failure()
        assert b.allow() is False  # 3 failures => open

    def test_success_resets(self):
        b = rate_limit.CircuitBreaker(failure_threshold=2, cool_off_seconds=60)
        b.record_failure()
        b.record_failure()
        assert b.allow() is False
        b.record_success()
        assert b.allow() is True

    def test_cool_off_reopens(self):
        b = rate_limit.CircuitBreaker(failure_threshold=1, cool_off_seconds=0.05)
        b.record_failure()
        assert b.allow() is False
        time.sleep(0.07)
        # Half-open: one allow() returns True and resets the gate.
        assert b.allow() is True
