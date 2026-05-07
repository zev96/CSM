"""Parse a GitHub /releases/latest JSON into our UpdateInfo dataclass."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?$")


class ManifestError(Exception):
    """Raised when the GitHub release JSON does not match what we expect."""


@dataclass
class UpdateInfo:
    """Subset of a GitHub release we care about."""
    version: str            # bare X.Y.Z (no v-prefix)
    tag_name: str           # "vX.Y.Z" as GitHub stored it
    zip_url: str            # asset download URL
    manifest_url: str       # asset download URL for manifest.json
    changelog: str          # body markdown
    published_at: str       # ISO timestamp
    asset_size: int         # bytes of the zip

    def is_newer_than(self, other: str) -> bool:
        """Strict semver-tuple compare. v-prefix tolerated on input."""
        a = SEMVER_RE.match(self.version.lstrip("v"))
        b = SEMVER_RE.match(other.lstrip("v"))
        if not a or not b:
            return False
        return tuple(int(x) for x in a.group(1, 2, 3)) > \
               tuple(int(x) for x in b.group(1, 2, 3))


def parse_release_json(payload: dict[str, Any]) -> UpdateInfo:
    """Validate + extract the fields we need from a GitHub release JSON.

    Raises ManifestError if anything required is missing or malformed.
    """
    try:
        tag = payload["tag_name"]
        body = payload.get("body", "") or ""
        published = payload.get("published_at", "") or ""
        assets = payload["assets"]
    except (KeyError, TypeError) as e:
        raise ManifestError(f"missing required release field: {e}") from e

    m = SEMVER_RE.match(tag)
    if not m:
        raise ManifestError(f"tag_name '{tag}' is not valid semver")

    zip_asset = next(
        (a for a in assets if a.get("name", "").endswith(".zip")),
        None,
    )
    if not zip_asset:
        raise ManifestError("release has no .zip asset")

    manifest_asset = next(
        (a for a in assets if a.get("name") == "manifest.json"),
        None,
    )
    if not manifest_asset:
        raise ManifestError("release has no manifest.json asset")

    # Prefer the API URL ("url" field) over browser_download_url. For PRIVATE
    # repos, browser_download_url 302-redirects to a signed S3 URL but our
    # Authorization: Bearer header carries through and breaks the S3 request.
    # The API URL with Accept: application/octet-stream gives the binary
    # directly with the same auth header. Falls back to browser_download_url
    # if the test fixture (or non-GitHub backend) didn't include "url".
    return UpdateInfo(
        version=".".join(m.group(1, 2, 3)),
        tag_name=tag,
        zip_url=zip_asset.get("url") or zip_asset["browser_download_url"],
        manifest_url=manifest_asset.get("url") or manifest_asset["browser_download_url"],
        changelog=body,
        published_at=published,
        asset_size=int(zip_asset.get("size", 0)),
    )
