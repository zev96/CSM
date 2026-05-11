"""Update check + download orchestration."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from csm_core.updater_client.checker import check_for_update
from csm_core.updater_client.downloader import (
    DownloadCancelled, DownloadError, download_with_verification,
)

from .. import __version__
from ..event_bus import bus
from . import config_service

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="updater")


def check() -> dict[str, Any]:
    """Return JSON-friendly CheckResult. Empty repo = "no update repo configured"."""
    cfg = config_service.load()
    if not cfg.update_repo:
        return {
            "has_update": False,
            "info": None,
            "error": "no update_repo configured",
            "current_version": __version__,
        }
    result = check_for_update(
        repo=cfg.update_repo,
        token="",  # public-repo only for v1; auth tokens come later
        current_version=__version__,
        timeout=5.0,
    )
    return {
        "has_update": result.has_update,
        "info": asdict(result.info) if result.info else None,
        "error": result.error,
        "current_version": __version__,
    }


def submit_download(*, url: str, expected_sha256: str, target: Path | None = None) -> str:
    """Spawn a download. Progress streams over /api/events/{job_id}."""
    job_id = bus.create_job()
    target = target or _default_target_path(url)
    _executor.submit(_run_download, job_id, url, expected_sha256, target)
    return job_id


def _default_target_path(url: str) -> Path:
    """Land downloads in <config_dir>/updates/. Filename = last URL segment."""
    name = url.rstrip("/").rsplit("/", 1)[-1] or "update.bin"
    return config_service.get_path().parent / "updates" / name


def _run_download(job_id: str, url: str, expected_sha256: str, target: Path) -> None:
    target = Path(target)

    def _on_progress(done: int, total: int) -> None:
        percent = (done / total) if total else 0.0
        bus.publish(
            job_id, "progress",
            done=done, total=total,
            percent=round(percent * 100, 1),
        )

    try:
        sha = download_with_verification(
            url=url,
            target=target,
            expected_sha256=expected_sha256,
            progress_cb=_on_progress,
        )
        bus.finish(job_id, target=str(target), sha256=sha)
    except DownloadCancelled:
        bus.fail(job_id, error="cancelled")
    except DownloadError as e:
        bus.fail(job_id, error=f"DownloadError: {e}")
    except Exception as e:
        logger.exception("update download %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
