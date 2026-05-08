"""check_for_update: one-shot orchestration of GitHub client + manifest parse.

Returns a CheckResult that the GUI can interpret without knowing about the
underlying httpx / parser exceptions.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from .github_client import (
    GitHubClient, GitHubAuthError, GitHubNetworkError, GitHubNotFoundError,
    GitHubError,
)
from .manifest import UpdateInfo, parse_release_json, ManifestError

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Outcome of one check_for_update call."""
    has_update: bool
    info: UpdateInfo | None
    error: str | None  # human-readable message, None on success


def check_for_update(
    *, repo: str, token: str, current_version: str,
    timeout: float = 5.0,
) -> CheckResult:
    """Check the latest release of ``repo`` against ``current_version``.

    On any failure (network / auth / parse), returns a CheckResult with
    ``error`` set to a human-readable string. The caller decides whether to
    show the user a notification or stay silent.
    """
    try:
        with GitHubClient(repo=repo, token=token, timeout=timeout) as gh:
            payload = gh.get_latest_release()
    except GitHubAuthError as e:
        return CheckResult(False, None, f"auth failed: {e}")
    except GitHubNotFoundError as e:
        return CheckResult(False, None, f"not found: {e}")
    except GitHubNetworkError as e:
        return CheckResult(False, None, f"network error: {e}")
    except GitHubError as e:
        return CheckResult(False, None, f"github error: {e}")

    try:
        info = parse_release_json(payload)
    except ManifestError as e:
        return CheckResult(False, None, f"manifest error: {e}")

    has_update = info.is_newer_than(current_version)
    return CheckResult(has_update=has_update, info=info, error=None)
