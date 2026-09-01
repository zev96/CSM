"""过期 PAT 的匿名降级重试 — updater_service 侧的两条路径。

背景(2026-09-01 全员更新失败):CI 曾把 CSM_RELEASE_PAT 烙进安装包,
token 过期后 GitHub 对带无效凭证的请求恒回 401(不降级匿名),所有装机
同时失去更新能力。修复 = 带 token 收到 401/403 时摘掉凭证重试一次
(public 仓库匿名本来就能读 release 与资产)。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx

from csm_core.updater_client.downloader import DownloadError
from csm_sidecar.services import updater_service


def _resp(status: int, text: str = "") -> httpx.Response:
    return httpx.Response(status_code=status, text=text)


SHA = "a" * 64
MANIFEST = f'{{"sha256": "{SHA}"}}'


# ── _try_fetch_sha256 ───────────────────────────────────────────────────────
def test_manifest_fetch_falls_back_to_anonymous_on_401(monkeypatch):
    monkeypatch.setattr(updater_service, "_read_release_token", lambda: "expired")
    calls: list[dict | None] = []

    def fake_get(url, headers=None, **kw):
        calls.append(headers)
        if headers and "Authorization" in headers:
            return _resp(401)
        return _resp(200, MANIFEST)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert updater_service._try_fetch_sha256("https://api.github.com/x") == SHA
    assert len(calls) == 2
    assert "Authorization" in calls[0]
    assert "Authorization" not in calls[1]


def test_manifest_fetch_no_token_does_not_retry(monkeypatch):
    monkeypatch.setattr(updater_service, "_read_release_token", lambda: "")
    calls: list[dict | None] = []

    def fake_get(url, headers=None, **kw):
        calls.append(headers)
        return _resp(401)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert updater_service._try_fetch_sha256("https://api.github.com/x") is None
    assert len(calls) == 1


# ── _run_download ───────────────────────────────────────────────────────────
def test_download_falls_back_to_anonymous_on_401(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(updater_service, "_read_release_token", lambda: "expired")
    fake_bus = MagicMock()
    monkeypatch.setattr(updater_service, "bus", fake_bus)
    seen_headers: list[dict] = []

    def fake_download(*, url, target, expected_sha256, progress_cb=None, headers=None, **kw):
        seen_headers.append(dict(headers or {}))
        if headers and "Authorization" in headers:
            raise DownloadError("HTTP 401 from x", status_code=401)
        return expected_sha256

    monkeypatch.setattr(updater_service, "download_with_verification", fake_download)
    updater_service._run_download("job-1", "https://x/y.zip", SHA, tmp_path / "y.zip")

    assert len(seen_headers) == 2
    assert "Authorization" in seen_headers[0]
    assert "Authorization" not in seen_headers[1]
    fake_bus.finish.assert_called_once()
    fake_bus.fail.assert_not_called()


def test_download_non_auth_error_does_not_retry(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(updater_service, "_read_release_token", lambda: "expired")
    fake_bus = MagicMock()
    monkeypatch.setattr(updater_service, "bus", fake_bus)
    calls = {"n": 0}

    def fake_download(**kw):
        calls["n"] += 1
        raise DownloadError("sha256 mismatch")

    monkeypatch.setattr(updater_service, "download_with_verification", fake_download)
    updater_service._run_download("job-2", "https://x/y.zip", SHA, tmp_path / "y.zip")

    assert calls["n"] == 1
    fake_bus.fail.assert_called_once()
