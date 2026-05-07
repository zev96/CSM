"""check_for_update: orchestrates GitHubClient → manifest.parse → UpdateInfo."""
from unittest.mock import patch, MagicMock
import pytest
from csm_core.updater_client.checker import (
    check_for_update, CheckResult,
)
from csm_core.updater_client.github_client import (
    GitHubAuthError, GitHubNetworkError, GitHubNotFoundError,
)


def _release(version="0.2.0"):
    return {
        "tag_name": f"v{version}",
        "name": f"CSM v{version}",
        "body": "notes",
        "published_at": "2026-05-07T08:00:00Z",
        "assets": [
            {"name": f"CSM-v{version}.zip",
             "size": 1, "browser_download_url": "u1"},
            {"name": "manifest.json",
             "size": 1, "browser_download_url": "u2"},
        ],
    }


def test_check_finds_newer():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.return_value = _release("0.2.0")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.1.0")
    assert isinstance(result, CheckResult)
    assert result.has_update is True
    assert result.info is not None
    assert result.info.version == "0.2.0"
    assert result.error is None


def test_check_already_at_latest():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.return_value = _release("0.2.0")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.2.0")
    assert result.has_update is False
    assert result.info is not None
    assert result.error is None


def test_check_handles_network_error():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.side_effect = GitHubNetworkError("dns")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.1.0")
    assert result.has_update is False
    assert result.info is None
    assert result.error is not None
    assert "network" in result.error.lower() or "dns" in result.error.lower()


def test_check_handles_auth_error():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.side_effect = GitHubAuthError("401")
        result = check_for_update(repo="x/y", token="bad",
                                  current_version="0.1.0")
    assert result.has_update is False
    assert "auth" in result.error.lower()


def test_check_handles_not_found():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.side_effect = GitHubNotFoundError("404")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.1.0")
    assert result.has_update is False
    assert "not" in result.error.lower() or "404" in result.error
