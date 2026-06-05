"""Mining service — submits jobs to a single-worker pool, owns the runner."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, Future
from threading import Lock
from typing import Any

from csm_core.mining import storage as mining_storage
from csm_core.mining.runner import MiningRunner

from ..event_bus import bus as event_bus

logger = logging.getLogger(__name__)


_executor: ThreadPoolExecutor | None = None
_runner: MiningRunner | None = None
_active_job_id: int | None = None
_active_lock = Lock()


def init() -> None:
    """Called from sidecar lifespan. Idempotent."""
    global _executor, _runner
    if _executor is not None:
        return
    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mining-worker")
    _runner = MiningRunner(publish=_publish_to_bus)
    # Sweep orphaned running jobs from a previous run.
    interrupted = mining_storage.mark_interrupted_jobs()
    if interrupted:
        logger.info("mining: marked %d orphaned jobs as interrupted", interrupted)


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def is_busy() -> bool:
    with _active_lock:
        return _active_job_id is not None


def active_job_id() -> int | None:
    with _active_lock:
        return _active_job_id


def submit_job(
    keyword: str,
    platforms: list[str],
    target_per_platform: int,
    brand_keywords: list[str] | None = None,
) -> int:
    global _active_job_id
    if _executor is None or _runner is None:
        raise RuntimeError("mining_service not initialized")
    # Reserve the slot atomically with the check. Create the DB row first
    # (cheap) so the reservation refers to a real job_id.
    job_id = mining_storage.create_job(
        keyword, platforms, target_per_platform, brand_keywords=brand_keywords
    )
    with _active_lock:
        if _active_job_id is not None:
            # Rollback: the job we just created in storage is orphaned, mark it cancelled.
            mining_storage.cancel_job_if_running(job_id)
            raise RuntimeError(f"mining busy on job {_active_job_id}")
        _active_job_id = job_id
    event_bus.create_job(_event_job_id(job_id))
    fut = _executor.submit(_run_with_guard, job_id)
    fut.add_done_callback(lambda f: _on_done(job_id, f))
    return job_id


def cancel_job(job_id: int) -> bool:
    if _runner is None:
        return False
    flipped_storage = mining_storage.cancel_job_if_running(job_id)
    runner_acked = _runner.cancel(job_id)
    return flipped_storage or runner_acked


def _run_with_guard(job_id: int) -> None:
    """The worker entry. _active_job_id was already set by submit_job."""
    global _active_job_id
    try:
        assert _runner is not None
        _runner.run(job_id)
    except Exception as e:
        logger.exception("mining job %d crashed: %s", job_id, e)
        mining_storage.finalize_job(job_id)
    finally:
        with _active_lock:
            _active_job_id = None


def _on_done(job_id: int, _future: Future) -> None:
    event_bus.finish(_event_job_id(job_id))


def _publish_to_bus(kind: str, payload: dict[str, Any]) -> None:
    job_id = payload.get("job_id")
    if job_id is None:
        return
    # event_bus.publish(job_id, kind, **data) — strip job_id from payload
    # before splatting or we get TypeError ("multiple values for job_id").
    data = {k: v for k, v in payload.items() if k != "job_id"}
    event_bus.publish(_event_job_id(job_id), kind, **data)


def _event_job_id(job_id: int) -> str:
    """One bus queue per mining job, keyed by 'mining-<id>'."""
    return f"mining-{job_id}"
