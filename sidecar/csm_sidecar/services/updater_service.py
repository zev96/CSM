"""Update check + download orchestration."""
from __future__ import annotations

import json
import logging
import sys
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

    Since v0.8.1 official release builds ship WITHOUT a token — the repo is
    public and anonymous reads work. (v0.8.0 及更早版本由 CI 注入 PAT,
    2026-09 那批 token 过期导致全员更新检查 401,详见 CHANGELOG。)
    The gitignored ``_token.py`` remains supported for private forks /
    local testing via ``_token.py.example``.

    Returns "" when the file isn't present — that's the default. With an
    empty token, GitHub's anonymous rate limit (60 req/h per IP) applies;
    that's fine for "Check updates" being a user-triggered button, not a
    poll.
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
        manifest = _try_fetch_manifest(result.info.manifest_url) or {}
        info_dict["expected_sha256"] = _valid_sha(manifest.get("sha256")) or ""
        info_dict["lite"] = False
        # 增量包：release 挂了 *-lite.upd（不含 Chromium）且本机已装的
        # binaries/ms-playwright/chromium-XXXX 与 manifest 登记的一致 → 用它
        # 替换 zip_url / 体积 / sha，前端与下载路由零改动。任一条件不满足
        # 就退回完整包（与 ≤0.8.3 行为完全一致）。
        lite = manifest.get("lite")
        if isinstance(lite, dict) and result.info.lite_url:
            lite_sha = _valid_sha(lite.get("sha256"))
            if lite_sha and _lite_applicable(lite.get("chromium_dirs")):
                info_dict["zip_url"] = result.info.lite_url
                info_dict["asset_size"] = int(lite.get("asset_size") or result.info.lite_size or 0)
                info_dict["expected_sha256"] = lite_sha
                info_dict["lite"] = True
    return {
        "has_update": result.has_update,
        "info": info_dict,
        "error": result.error,
        "current_version": __version__,
    }


def _valid_sha(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) == 64 else None


def install_root() -> Path | None:
    """打包运行时的安装根目录（csm-sidecar.exe 所在目录，与
    ``binaries/ms-playwright`` 同级，同 browser_infra.patchright_pool 的约定）。
    dev（非 frozen）下返回 None —— 增量包只对真实安装有意义。"""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def _lite_applicable(chromium_dirs: Any) -> bool:
    """manifest 登记的每个 chromium-XXXX 目录都已存在于本机安装 → 可用增量包。"""
    if not isinstance(chromium_dirs, list) or not chromium_dirs:
        return False
    root = install_root()
    if root is None:
        return False
    base = root / "binaries" / "ms-playwright"
    for name in chromium_dirs:
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            return False
        if not (base / name).is_dir():
            logger.info("lite update not applicable: %s missing under %s", name, base)
            return False
    return True


def _try_fetch_manifest(manifest_url: str) -> dict[str, Any] | None:
    """Fetch a release asset's manifest.json and return the parsed dict.

    Returns None (without raising) on any failure — manifest unavailable
    shouldn't break the update-check UX, just disable the download path.
    Expected manifest shape: ``{"sha256": "<64 hex chars>", ...}``.
    """
    try:
        tok = _read_release_token()
        resp = _fetch_asset(manifest_url, tok)
        if tok and resp.status_code in (401, 403):
            # 过期 PAT：GitHub 不会把带无效凭证的请求降级成匿名。public
            # 仓库匿名可读，摘掉凭证重试一次（与 GitHubClient 同一策略）。
            logger.warning(
                "manifest fetch got HTTP %s with token — retrying anonymously",
                resp.status_code,
            )
            resp = _fetch_asset(manifest_url, "")
        if resp.status_code != 200:
            logger.warning(
                "manifest fetch returned HTTP %s for %s",
                resp.status_code, manifest_url,
            )
            return None
        payload = json.loads(resp.text)
        return payload if isinstance(payload, dict) else None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        logger.warning("manifest fetch failed: %s", e)
        return None


def _try_fetch_sha256(manifest_url: str) -> str | None:
    """完整包的 sha256（manifest 顶层 ``sha256``）；缺失 / 非法 → None。"""
    payload = _try_fetch_manifest(manifest_url)
    if payload is None:
        return None
    sha = _valid_sha(payload.get("sha256"))
    if sha is None:
        logger.warning("manifest.json has missing/invalid sha256")
    return sha


def _fetch_asset(url: str, tok: str) -> httpx.Response:
    """GET a release asset via the API URL.

    Accept: octet-stream makes GitHub return the asset bytes instead of the
    JSON descriptor. Authorization is only attached when ``tok`` is set —
    private repos need it; public repos work anonymously.
    """
    headers = {"Accept": "application/octet-stream"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return httpx.get(url, headers=headers, timeout=5.0, follow_redirects=True)


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
        try:
            sha = download_with_verification(
                url=url,
                target=target,
                expected_sha256=expected_sha256,
                progress_cb=_on_progress,
                headers=headers,
            )
        except DownloadError as e:
            if not (tok and e.status_code in (401, 403)):
                raise
            # 过期 PAT 同款降级:public 仓库资产匿名可下,摘凭证重试一次。
            logger.warning(
                "download got HTTP %s with token — retrying anonymously",
                e.status_code,
            )
            headers.pop("Authorization", None)
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
