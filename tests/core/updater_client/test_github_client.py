"""GitHubClient: thin httpx wrapper with PAT auth + error mapping."""
from unittest.mock import patch, MagicMock
import httpx
import pytest
from csm_core.updater_client.github_client import (
    GitHubClient, GitHubAuthError, GitHubError, GitHubNetworkError,
    GitHubNotFoundError,
)


def _mock_response(status: int, json_data=None, content: bytes = b""):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_data or {}
    r.content = content
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"http {status}", request=MagicMock(), response=r,
        )
    return r


def test_get_latest_release_happy_path():
    client = GitHubClient(repo="zev96/csm", token="t-fake")
    payload = {"tag_name": "v0.2.0", "assets": []}
    with patch("httpx.Client.get", return_value=_mock_response(200, payload)) as mocked:
        result = client.get_latest_release()
    assert result == payload
    # Token rides on the request, not the shared client headers
    _, kwargs = mocked.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer t-fake"


def test_get_latest_release_401_raises_auth_error():
    client = GitHubClient(repo="zev96/csm", token="bad")
    with patch("httpx.Client.get", return_value=_mock_response(401)):
        with pytest.raises(GitHubAuthError):
            client.get_latest_release()


def test_get_latest_release_403_with_token_both_hops_maps_to_rate_limit():
    """token 403 → 匿名重试也 403:最终响应是匿名的,应报限流而非 auth failed。"""
    client = GitHubClient(repo="zev96/csm", token="rate-limited")
    with patch("httpx.Client.get", return_value=_mock_response(403)) as mocked:
        with pytest.raises(GitHubError, match="rate limit"):
            client.get_latest_release()
    assert mocked.call_count == 2


def test_401_with_token_falls_back_to_anonymous():
    """烙进安装包的 PAT 过期 → GitHub 恒回 401。public 仓库匿名可读,
    客户端必须摘掉凭证重试一次,而不是让更新链路死在过期 token 上。"""
    client = GitHubClient(repo="zev96/csm", token="expired")
    payload = {"tag_name": "v9.9.9", "assets": []}
    with patch(
        "httpx.Client.get",
        side_effect=[_mock_response(401), _mock_response(200, payload)],
    ) as mocked:
        result = client.get_latest_release()
    assert result == payload
    assert mocked.call_count == 2
    first_headers = mocked.call_args_list[0].kwargs["headers"]
    retry_headers = mocked.call_args_list[1].kwargs["headers"]
    assert first_headers["Authorization"] == "Bearer expired"
    assert not (retry_headers or {}).get("Authorization")


def test_401_with_token_anonymous_retry_also_fails():
    """降级重试也 401(如私有仓库)→ 仍抛 GitHubAuthError,且只重试一次。"""
    client = GitHubClient(repo="zev96/private", token="expired")
    with patch(
        "httpx.Client.get",
        side_effect=[_mock_response(401), _mock_response(404)],
    ) as mocked:
        # 匿名撞私有仓库是 404 —— 对调用方表现为 not found
        with pytest.raises(GitHubNotFoundError):
            client.get_latest_release()
    assert mocked.call_count == 2


def test_401_without_token_does_not_retry():
    client = GitHubClient(repo="zev96/csm", token="")
    with patch("httpx.Client.get", return_value=_mock_response(401)) as mocked:
        with pytest.raises(GitHubAuthError):
            client.get_latest_release()
    assert mocked.call_count == 1


def test_403_with_token_falls_back_to_anonymous():
    """403(token 被限流/无效)同样触发匿名降级。"""
    client = GitHubClient(repo="zev96/csm", token="rate-limited")
    payload = {"tag_name": "v9.9.9", "assets": []}
    with patch(
        "httpx.Client.get",
        side_effect=[_mock_response(403), _mock_response(200, payload)],
    ) as mocked:
        assert client.get_latest_release() == payload
    assert mocked.call_count == 2


def test_anonymous_403_maps_to_rate_limit_not_auth_failed():
    """无凭证的 403 = 匿名限流。不能再打出 "auth failed" 字样 ——
    那正是 2026-09 全员故障的错误文案,会让用户以为 bug 复发。"""
    client = GitHubClient(repo="zev96/csm", token="")
    with patch("httpx.Client.get", return_value=_mock_response(403)):
        with pytest.raises(GitHubError, match="rate limit") as ei:
            client.get_latest_release()
    assert not isinstance(ei.value, GitHubAuthError)


def test_network_error_during_anonymous_retry_maps_to_network_error():
    client = GitHubClient(repo="zev96/csm", token="expired")
    with patch(
        "httpx.Client.get",
        side_effect=[_mock_response(401), httpx.ConnectError("dns")],
    ):
        with pytest.raises(GitHubNetworkError):
            client.get_latest_release()


def test_connect_timeout_maps_to_network_error():
    """httpx.ConnectTimeout 不是 ConnectError 子类 —— 曾漏接,一路穿到
    FastAPI 变 500。对国内用户这是连 api.github.com 最常见的失败形态。"""
    client = GitHubClient(repo="zev96/csm", token="")
    with patch("httpx.Client.get", side_effect=httpx.ConnectTimeout("timeout")):
        with pytest.raises(GitHubNetworkError):
            client.get_latest_release()


def test_get_latest_release_404_raises_not_found():
    client = GitHubClient(repo="zev96/csm", token="t")
    with patch("httpx.Client.get", return_value=_mock_response(404)):
        with pytest.raises(GitHubNotFoundError):
            client.get_latest_release()


def test_get_latest_release_network_error():
    client = GitHubClient(repo="zev96/csm", token="t")
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("dns")):
        with pytest.raises(GitHubNetworkError):
            client.get_latest_release()


def test_empty_token_works_for_public_unauth_calls():
    """If TOKEN is empty (e.g. local dev w/o injection), client still constructs."""
    client = GitHubClient(repo="zev96/csm", token="")
    assert client._client is not None
