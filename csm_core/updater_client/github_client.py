"""Thin httpx wrapper around the GitHub REST API.

We only use one endpoint: GET /repos/{owner}/{repo}/releases/latest.
Wraps it with PAT auth + maps HTTP errors to our own exception hierarchy
so the caller (checker.py) can decide what to do.
"""
from __future__ import annotations
from typing import Any

import httpx

DEFAULT_TIMEOUT = 5.0  # seconds


class GitHubError(Exception):
    """Base class for GitHub API errors surfaced to the rest of CSM."""


class GitHubAuthError(GitHubError):
    """401 / 403 — token missing, expired, or rate-limited."""


class GitHubNotFoundError(GitHubError):
    """404 — repo doesn't exist or no releases yet."""


class GitHubNetworkError(GitHubError):
    """DNS / TCP / TLS failure or timeout."""


class GitHubClient:
    """GitHub release reader. Token-optional (anonymous works for public repos)."""

    def __init__(self, repo: str, token: str = "",
                 timeout: float = DEFAULT_TIMEOUT):
        """``repo`` is "<owner>/<name>" (e.g. "zev96/csm")."""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._repo = repo
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def get_latest_release(self) -> dict[str, Any]:
        url = f"/repos/{self._repo}/releases/latest"
        try:
            resp = self._client.get(url)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError) as e:
            raise GitHubNetworkError(str(e)) from e
        if resp.status_code in (401, 403):
            raise GitHubAuthError(f"GitHub returned HTTP {resp.status_code}")
        if resp.status_code == 404:
            raise GitHubNotFoundError(
                f"no releases found for {self._repo}")
        if resp.status_code >= 400:
            raise GitHubError(f"unexpected HTTP {resp.status_code}")
        return resp.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
