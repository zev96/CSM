"""Per-platform rate limiting and randomized request spacing.

Two independent things live here:

1. ``acquire_slot`` / ``release_slot`` — bounds the number of in-flight
   workers per platform. Set in ``MonitorConfig.concurrency_per_platform``
   (default 2). Without this, having ten Zhihu tasks all schedule at
   ``09:00`` would fire ten near-simultaneous requests, which is exactly
   what risk control is looking for.

2. ``RequestPacer`` — between-request jitter. ``next_delay()`` returns a
   random sleep duration drawn from the user's configured window
   (default 5–15s). The pacer is not a token bucket because we don't
   actually want strict rate enforcement; we want the pattern of
   request timing to look human. Uniform jitter over a wide range is
   more effective than steady ticks at a fixed RPS.

The global circuit breaker (``CircuitBreaker``) is a separate concern:
when a platform fails N times in a rolling window, all that platform's
tasks pause for a cool-off period. That stops cascading bans across an
account pool when one cookie has gone bad.
"""
from __future__ import annotations
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field


# Per-platform semaphores, lazily created. Using a dict keyed by
# platform name keeps the API simple — callers pass the string the
# adapter declares as ``platform`` and we hand back a bounded slot.
_sem_lock = threading.Lock()
_sems: dict[str, threading.Semaphore] = {}
_max_concurrent: dict[str, int] = {}


def configure_concurrency(platform: str, max_in_flight: int) -> None:
    """Set or update the concurrency cap for a platform.

    Safe to call repeatedly (e.g. when the user edits the setting). If
    we already issued slots, the new cap takes effect for fresh acquires
    only — in-flight workers are not interrupted.
    """
    if max_in_flight < 1:
        raise ValueError("max_in_flight must be ≥ 1")
    with _sem_lock:
        # 上限没变就别换信号量对象：apply_settings 每次保存设置都会调
        # configure_concurrency(baidu, 1)。若无脑装一个新 Semaphore，正在跑的
        # worker 还握着旧对象（count 0），新派发的 worker 却能拿到新对象的空闲
        # slot → 同一 Chrome 副本上并发两个任务，且旧 holder 释放进新对象后
        # 上限永久漂到 2。同 cap = no-op。
        if _max_concurrent.get(platform) == max_in_flight and platform in _sems:
            return
        _max_concurrent[platform] = max_in_flight
        _sems[platform] = threading.Semaphore(max_in_flight)


def _get_sem(platform: str) -> threading.Semaphore:
    with _sem_lock:
        sem = _sems.get(platform)
        if sem is None:
            # Default 2 — same as MonitorConfig.concurrency_per_platform.
            sem = threading.Semaphore(2)
            _sems[platform] = sem
            _max_concurrent[platform] = 2
        return sem


def acquire_slot(platform: str, timeout: float | None = None) -> bool:
    """Block until a slot is available. Returns False on timeout."""
    return _get_sem(platform).acquire(timeout=timeout)


def release_slot(platform: str) -> None:
    _get_sem(platform).release()


class slot:
    """Context-manager wrapper around acquire/release.

    Usage::

        with slot("zhihu_question"):
            adapter.fetch(task)
    """

    def __init__(self, platform: str, timeout: float | None = None):
        self.platform = platform
        self.timeout = timeout
        self._acquired = False

    def __enter__(self) -> "slot":
        if not acquire_slot(self.platform, self.timeout):
            raise TimeoutError(f"timed out waiting for slot on {self.platform}")
        self._acquired = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._acquired:
            release_slot(self.platform)


# ── Per-platform request pacing ─────────────────────────────────────────────
@dataclass
class RequestPacer:
    """Tracks last-request time for one platform; returns sleeps to insert.

    Adapters call ``wait()`` immediately before issuing each HTTP call.
    The pacer combines the user's configured min/max window with the
    elapsed time since the previous request, so back-to-back fast calls
    automatically wait longer than calls spaced naturally apart.
    """

    delay_min: float = 5.0
    delay_max: float = 15.0
    _last_request_at: float = field(default=0.0)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def wait(self) -> float:
        """Sleep enough to honor the configured spacing. Return slept seconds."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at if self._last_request_at else self.delay_max
            target = random.uniform(self.delay_min, self.delay_max)
            sleep_for = max(0.0, target - elapsed)
            self._last_request_at = now + sleep_for
        if sleep_for > 0:
            time.sleep(sleep_for)
        return sleep_for

    def configure(self, delay_min: float, delay_max: float) -> None:
        if delay_min < 0 or delay_max < delay_min:
            raise ValueError("invalid delay window")
        self.delay_min = delay_min
        self.delay_max = delay_max


# Singleton pacers per platform. Adapters retrieve them via
# ``get_pacer(platform)`` rather than holding their own — a fresh pacer
# every fetch would always hit the "no last request" branch and skip the
# spacing entirely.
_pacers_lock = threading.Lock()
_pacers: dict[str, RequestPacer] = {}


def get_pacer(platform: str) -> RequestPacer:
    with _pacers_lock:
        p = _pacers.get(platform)
        if p is None:
            p = RequestPacer()
            _pacers[platform] = p
        return p


def configure_pacing(platform: str, delay_min: float, delay_max: float) -> None:
    get_pacer(platform).configure(delay_min, delay_max)


# ── Circuit breaker ─────────────────────────────────────────────────────────
@dataclass
class CircuitBreaker:
    """Open after ``failure_threshold`` failures in ``window_seconds``.

    While open, all ``allow()`` calls return False until ``cool_off_seconds``
    have passed since the last failure. The breaker is per-platform —
    one platform's instability shouldn't pause monitoring of another.
    """

    failure_threshold: int = 5
    window_seconds: float = 3600.0
    cool_off_seconds: float = 1800.0
    _failures: deque[float] = field(default_factory=deque)
    _opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_success(self) -> None:
        with self._lock:
            self._failures.clear()
            self._opened_at = None

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._failures.append(now)
            self._evict_old(now)
            if len(self._failures) >= self.failure_threshold:
                self._opened_at = now

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            self._evict_old(now)
            if self._opened_at is None:
                return True
            if now - self._opened_at >= self.cool_off_seconds:
                # Cool-off elapsed — half-open: allow one through, the
                # next record_failure will trip again immediately if the
                # underlying issue isn't fixed.
                self._opened_at = None
                self._failures.clear()
                return True
            return False

    def _evict_old(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()


_breakers_lock = threading.Lock()
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(platform: str) -> CircuitBreaker:
    with _breakers_lock:
        b = _breakers.get(platform)
        if b is None:
            b = CircuitBreaker()
            _breakers[platform] = b
        return b
