"""Stream-download a file + verify SHA256.

Designed for the GUI: emits progress periodically via a callback, supports
cooperative cancellation via a polling lambda, and atomically deletes the
target on any failure (including SHA mismatch and user cancel) so the
client never sees a half-written zip.

For private-repo GitHub release assets, callers should pass:
    headers={"Authorization": f"Bearer {token}",
             "Accept": "application/octet-stream"}
"""
from __future__ import annotations
import hashlib
import logging
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

CHUNK_SIZE = 8192   # bytes — keeps mem usage flat
PROGRESS_INTERVAL = 256 * 1024  # ~256 KB between callbacks


class DownloadError(Exception):
    """Network failure / HTTP error / SHA mismatch."""


class DownloadCancelled(Exception):
    """User cancelled the download mid-stream."""


def download_with_verification(
    *,
    url: str,
    target: Path,
    expected_sha256: str,
    progress_cb: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> str:
    """Download ``url`` to ``target`` and verify SHA256.

    ``progress_cb(done_bytes, total_bytes)`` is called every ``PROGRESS_INTERVAL``
    bytes. ``is_cancelled()`` is polled every chunk; if it returns True we
    raise ``DownloadCancelled`` and delete any partial file.

    ``headers`` is optional; when set, passed through to httpx.stream(). Used
    by callers that need to authenticate the request (e.g. private-repo
    GitHub release assets need ``Authorization: Bearer <PAT>``).

    Returns the actual computed SHA256 hex string on success.

    Raises:
        DownloadError on network / HTTP / SHA failure
        DownloadCancelled on cooperative cancel
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    total = 0
    bytes_since_progress = 0

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers or {}) as resp:
                if resp.status_code >= 400:
                    raise DownloadError(
                        f"HTTP {resp.status_code} from {url}")
                content_length = int(resp.headers.get("content-length", 0))
                with open(target, "wb") as f:
                    for chunk in resp.iter_bytes(CHUNK_SIZE):
                        if is_cancelled and is_cancelled():
                            raise DownloadCancelled()
                        if not chunk:
                            continue
                        f.write(chunk)
                        hasher.update(chunk)
                        total += len(chunk)
                        bytes_since_progress += len(chunk)
                        if progress_cb and bytes_since_progress >= PROGRESS_INTERVAL:
                            progress_cb(total, content_length or total)
                            bytes_since_progress = 0
                # Final progress at 100%
                if progress_cb:
                    progress_cb(total, content_length or total)
    except httpx.HTTPError as e:
        _cleanup(target)
        raise DownloadError(str(e)) from e
    except DownloadCancelled:
        _cleanup(target)
        raise
    except DownloadError:
        _cleanup(target)
        raise

    actual_sha = hasher.hexdigest()
    if actual_sha != expected_sha256:
        _cleanup(target)
        raise DownloadError(
            f"sha256 mismatch — expected {expected_sha256}, got {actual_sha}"
        )
    return actual_sha


def _cleanup(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as e:
        logger.warning("downloader: failed to clean %s — %s", path, e)
