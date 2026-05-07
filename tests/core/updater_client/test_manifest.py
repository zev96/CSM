"""UpdateInfo + parse GitHub release JSON."""
import pytest
from csm_core.updater_client.manifest import (
    UpdateInfo, parse_release_json, ManifestError,
)


def _release_json(version="0.2.0", manifest_in_assets=True, zip_in_assets=True):
    """Mimic GitHub's /repos/.../releases/latest response."""
    assets = []
    if zip_in_assets:
        assets.append({
            "name": f"CSM-v{version}.zip",
            "size": 232_000_000,
            "url": f"https://api.github.com/repos/x/y/releases/assets/100",
            "browser_download_url": f"https://example.com/CSM-v{version}.zip",
        })
    if manifest_in_assets:
        assets.append({
            "name": "manifest.json",
            "size": 320,
            "url": "https://api.github.com/repos/x/y/releases/assets/200",
            "browser_download_url": "https://example.com/manifest.json",
        })
    return {
        "tag_name": f"v{version}",
        "name": f"CSM v{version}",
        "body": "### Added\n- 系统托盘\n",
        "published_at": "2026-05-07T08:00:00Z",
        "assets": assets,
    }


def test_parse_release_json_minimal():
    info = parse_release_json(_release_json())
    assert isinstance(info, UpdateInfo)
    assert info.version == "0.2.0"
    assert info.tag_name == "v0.2.0"
    # Now uses API URL (assets[].url) for private-repo asset auth.
    assert info.zip_url.startswith("https://api.github.com/")
    assert info.manifest_url.startswith("https://api.github.com/")
    assert "系统托盘" in info.changelog
    assert info.published_at == "2026-05-07T08:00:00Z"


def test_parse_release_falls_back_to_browser_url_when_api_missing():
    """If a fixture / non-GitHub backend lacks 'url', fall back to browser_download_url."""
    payload = {
        "tag_name": "v0.2.0",
        "body": "",
        "published_at": "",
        "assets": [
            {"name": "CSM-v0.2.0.zip", "size": 1,
             "browser_download_url": "https://example.com/CSM-v0.2.0.zip"},
            {"name": "manifest.json", "size": 1,
             "browser_download_url": "https://example.com/manifest.json"},
        ],
    }
    info = parse_release_json(payload)
    assert info.zip_url == "https://example.com/CSM-v0.2.0.zip"
    assert info.manifest_url == "https://example.com/manifest.json"


def test_parse_release_strips_v_prefix():
    info = parse_release_json(_release_json(version="1.0.0"))
    assert info.version == "1.0.0"


def test_parse_release_missing_zip_raises():
    with pytest.raises(ManifestError):
        parse_release_json(_release_json(zip_in_assets=False))


def test_parse_release_missing_manifest_raises():
    with pytest.raises(ManifestError):
        parse_release_json(_release_json(manifest_in_assets=False))


def test_parse_release_garbage_input_raises():
    with pytest.raises(ManifestError):
        parse_release_json({"unrelated": True})


def test_update_info_has_update_when_newer():
    info = UpdateInfo(
        version="0.2.0", tag_name="v0.2.0",
        zip_url="x", manifest_url="y",
        changelog="cl", published_at="t", asset_size=1,
    )
    assert info.is_newer_than("0.1.0") is True
    assert info.is_newer_than("0.2.0") is False
    assert info.is_newer_than("0.3.0") is False


def test_update_info_handles_v_prefix():
    info = UpdateInfo(
        version="0.2.0", tag_name="v0.2.0",
        zip_url="x", manifest_url="y",
        changelog="cl", published_at="t", asset_size=1,
    )
    assert info.is_newer_than("v0.1.0") is True
