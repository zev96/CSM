"""Thin httpx wrapper around the GitHub REST API.

We only use one endpoint: GET /repos/{owner}/{repo}/releases/latest.
Wraps it with PAT auth + maps HTTP errors to our own exception hierarchy
so the caller (checker.py) can decide what to do.
"""
from __future__ import annotations
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

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
        self._repo = repo
        self._token = token
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    def get_latest_release(self) -> dict[str, Any]:
        url = f"/repos/{self._repo}/releases/latest"
        anonymous = not self._token
        resp = self._get(url, use_token=bool(self._token))
        if self._token and resp.status_code in (401, 403):
            # GitHub 对「带了无效凭证」的请求一律 401/403,不会降级成匿名
            # —— 哪怕仓库是 public 的。烙进安装包的 PAT 一旦过期,所有装机
            # 会同时失去更新能力,所以这里摘掉凭证匿名重试一次。
            logger.warning(
                "GitHub returned HTTP %s with token auth — retrying anonymously",
                resp.status_code,
            )
            resp = self._get(url, use_token=False)
            anonymous = True
        if resp.status_code == 403 and anonymous:
            # 没带任何凭证的 403 不是鉴权问题,是匿名限流(60 req/h/IP,
            # 公司 NAT 共享出口时容易撞)。走 GitHubError 而非 AuthError,
            # 避免 UI 出现误导性的 "auth failed" 字样。
            raise GitHubError(
                "anonymous rate limit hit (HTTP 403) — try again later")
        if resp.status_code in (401, 403):
            raise GitHubAuthError(f"GitHub returned HTTP {resp.status_code}")
        if resp.status_code == 404:
            raise GitHubNotFoundError(
                f"no releases found for {self._repo}")
        if resp.status_code >= 400:
            raise GitHubError(f"unexpected HTTP {resp.status_code}")
        return resp.json()

    def _get(self, url: str, *, use_token: bool) -> httpx.Response:
        headers = (
            {"Authorization": f"Bearer {self._token}"} if use_token else None
        )
        try:
            return self._client.get(url, headers=headers)
        except httpx.HTTPError as e:
            # httpx.HTTPError 覆盖全部传输层失败(ConnectError、各类
            # Timeout、协议/代理错误)。此前只列了三个具体类,漏掉的
            # ConnectTimeout 会一路穿到 FastAPI 变成 500。
            raise GitHubNetworkError(str(e)) from e

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
