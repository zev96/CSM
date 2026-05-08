"""GitHubClient: thin httpx wrapper with PAT auth + error mapping."""
from unittest.mock import patch, MagicMock
import httpx
import pytest
from csm_core.updater_client.github_client import (
    GitHubClient, GitHubAuthError, GitHubNetworkError, GitHubNotFoundError,
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
    # Token was wired into the client
    assert "Authorization" in client._client.headers


def test_get_latest_release_401_raises_auth_error():
    client = GitHubClient(repo="zev96/csm", token="bad")
    with patch("httpx.Client.get", return_value=_mock_response(401)):
        with pytest.raises(GitHubAuthError):
            client.get_latest_release()


def test_get_latest_release_403_raises_auth_error():
    client = GitHubClient(repo="zev96/csm", token="rate-limited")
    with patch("httpx.Client.get", return_value=_mock_response(403)):
        with pytest.raises(GitHubAuthError):
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
