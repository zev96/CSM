"""Update check + download orchestration."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from csm_core.updater_client.checker import check_for_update
from csm_core.updater_client.downloader import (
    DownloadCancelled, DownloadError, download_with_verification,
)

from .. import __version__
from ..event_bus import bus
from . import config_service

logger = logging.getLogger(__name__)

# 官方发布仓库 —— 普通用户不应该需要配 settings.json 才能检查更新。
# 内测分叉 / 私有分发场景仍可在 settings.json 里覆写 update_repo。
DEFAULT_UPDATE_REPO = "zev96/CSM"

# Lazy-init: shutdown() nulls the pool; next submit_download() recreates.
# Critical for the upgrade path: lifespan finally now actually shuts this
# down (instead of the module-level singleton lingering until process exit),
# matching the audit C4 contract.
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="updater")
    return _executor


def shutdown() -> None:
    """Idempotent shutdown — called from sidecar lifespan finally."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def _read_release_token() -> str:
    """Pull the PAT out of csm_core.updater_client._token.

    The real ``_token.py`` is gitignored and either:
      - injected by CI on release builds (release.yml `Inject PAT` step)
      - copy-pasted by a dev from ``_token.py.example`` for local testing

    Returns "" when the file isn't present — that's the dev default and
    public-repo case. With an empty token, GitHub's anonymous rate limit
    (60 req/h per IP) applies; that's fine for "Check updates" being a
    user-triggered button, not a poll.
    """
    try:
        from csm_core.updater_client._token import TOKEN
    except ImportError:
        return ""
    return TOKEN if isinstance(TOKEN, str) else ""


def check() -> dict[str, Any]:
    """Return JSON-friendly CheckResult.

    Uses ``cfg.update_repo`` if set, otherwise falls back to
    :data:`DEFAULT_UPDATE_REPO` so out-of-the-box installs can check
    updates without any configuration.

    On has_update we additionally fetch manifest.json (a release asset) so
    ``info.expected_sha256`` is filled in. The download endpoint requires
    sha256 — without this side-fetch the frontend would only see metadata
    but not be able to start a verified download.

    Manifest fetch failure is non-fatal: we still surface the update info
    to the UI; the user just won't be able to start the download until the
    release publishes a valid manifest.json.
    """
    cfg = config_service.load()
    repo = cfg.update_repo or DEFAULT_UPDATE_REPO
    result = check_for_update(
        repo=repo,
        token=_read_release_token(),
        current_version=__version__,
        timeout=5.0,
    )
    info_dict: dict[str, Any] | None = None
    if result.info:
        info_dict = asdict(result.info)
        # 拉一次 manifest.json 拿 sha256，让前端 modal 的「更新」按钮能
        # 直接走 /api/updater/download（download body 必须带 64 字符 sha）。
        sha = _try_fetch_sha256(result.info.manifest_url)
        info_dict["expected_sha256"] = sha or ""
    return {
        "has_update": result.has_update,
        "info": info_dict,
        "error": result.error,
        "current_version": __version__,
    }


def _try_fetch_sha256(manifest_url: str) -> str | None:
    """Fetch a release asset's manifest.json and return its ``sha256`` field.

    Returns None (without raising) on any failure — manifest unavailable
    shouldn't break the update-check UX, just disable the download path.
    Expected manifest shape: ``{"sha256": "<64 hex chars>", ...}``.
    """
    try:
        # API URL needs Accept: application/octet-stream to get the asset
        # bytes; browser_download_url works with default Accept.
        headers = {"Accept": "application/octet-stream"}
        # 私有仓库需要带 token —— 没 token 时 anonymous GET 会 404。
        # 详见 GitHub Releases asset download docs：private repo asset
        # 不暴露给公网，必须 Bearer auth。
        tok = _read_release_token()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        resp = httpx.get(
            manifest_url, headers=headers, timeout=5.0, follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning(
                "manifest fetch returned HTTP %s for %s",
                resp.status_code, manifest_url,
            )
            return None
        payload = json.loads(resp.text)
        sha = payload.get("sha256", "")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
        logger.warning("manifest.json has missing/invalid sha256")
        return None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        logger.warning("manifest fetch failed: %s", e)
        return None


def submit_download(*, url: str, expected_sha256: str, target: Path | None = None) -> str:
    """Spawn a download. Progress streams over /api/events/{job_id}."""
    job_id = bus.create_job()
    target = target or _default_target_path(url)
    _get_executor().submit(_run_download, job_id, url, expected_sha256, target)
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

    # 私有仓库 asset 必须带 Authorization；Accept: octet-stream 让 GitHub API
    # 直接返回二进制而不是 JSON 描述。token 缺失（public repo / dev 环境）就
    # 不加 Authorization，走 anonymous 路径。
    headers: dict[str, str] = {"Accept": "application/octet-stream"}
    tok = _read_release_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        sha = download_with_verification(
            url=url,
            target=target,
            expected_sha256=expected_sha256,
            progress_cb=_on_progress,
            headers=headers,
        )
        bus.finish(job_id, target=str(target), sha256=sha)
    except DownloadCancelled:
        bus.fail(job_id, error="cancelled")
    except DownloadError as e:
        bus.fail(job_id, error=f"DownloadError: {e}")
    except Exception as e:
        logger.exception("update download %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
