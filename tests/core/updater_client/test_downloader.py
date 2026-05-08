"""Streaming downloader with SHA256 verification + optional headers."""
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx
import pytest
from csm_core.updater_client.downloader import (
    download_with_verification, DownloadError, DownloadCancelled,
)


def _mock_streaming_response(content: bytes, status: int = 200):
    """Mimic an httpx.Client.stream() context manager response."""
    resp = MagicMock()
    resp.status_code = status
    resp.iter_bytes.return_value = iter(
        [content[i:i+8192] for i in range(0, len(content), 8192)] or [b""]
    )
    resp.headers = {"content-length": str(len(content))}
    return resp


def _patch_stream(content: bytes, status: int = 200):
    """Patch httpx.Client to yield a streaming response."""
    resp = _mock_streaming_response(content, status)
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = None
    return patch("httpx.Client.stream", return_value=cm)


def test_download_writes_file_and_returns_sha(tmp_path: Path):
    content = b"hello world" * 100
    expected_sha = hashlib.sha256(content).hexdigest()
    out = tmp_path / "out.zip"

    with _patch_stream(content):
        sha = download_with_verification(
            url="https://x/y.zip",
            target=out,
            expected_sha256=expected_sha,
        )
    assert sha == expected_sha
    assert out.read_bytes() == content


def test_download_sha_mismatch_raises_and_deletes(tmp_path: Path):
    content = b"actual content" * 50
    out = tmp_path / "out.zip"

    with _patch_stream(content):
        with pytest.raises(DownloadError, match="sha256"):
            download_with_verification(
                url="https://x/y.zip",
                target=out,
                expected_sha256="0" * 64,
            )
    assert not out.exists()


def test_download_progress_callback(tmp_path: Path):
    content = b"a" * 10000
    sha = hashlib.sha256(content).hexdigest()
    out = tmp_path / "out.zip"
    progress_calls = []

    with _patch_stream(content):
        download_with_verification(
            url="x", target=out, expected_sha256=sha,
            progress_cb=lambda done, total: progress_calls.append((done, total)),
        )
    assert progress_calls
    last = progress_calls[-1]
    assert last[0] == last[1] == 10000


def test_download_cancellation(tmp_path: Path):
    content = b"x" * 100000
    sha = hashlib.sha256(content).hexdigest()
    out = tmp_path / "out.zip"

    cancelled = [False]
    def is_cancelled():
        if not cancelled[0]:
            cancelled[0] = True
            return False
        return True

    with _patch_stream(content):
        with pytest.raises(DownloadCancelled):
            download_with_verification(
                url="x", target=out, expected_sha256=sha,
                is_cancelled=is_cancelled,
            )
    assert not out.exists()


def test_download_http_error_raises(tmp_path: Path):
    out = tmp_path / "out.zip"
    with _patch_stream(b"", status=500):
        with pytest.raises(DownloadError):
            download_with_verification(
                url="x", target=out, expected_sha256="0" * 64,
            )


def test_download_passes_headers_to_stream(tmp_path: Path):
    """Optional headers (e.g. PAT auth) should propagate to httpx.stream call."""
    content = b"auth-bytes" * 100
    sha = hashlib.sha256(content).hexdigest()
    out = tmp_path / "out.zip"
    custom_headers = {"Authorization": "Bearer fake-token-123"}

    with _patch_stream(content) as mock_stream:
        download_with_verification(
            url="https://api.github.com/repos/x/y/releases/assets/123",
            target=out,
            expected_sha256=sha,
            headers=custom_headers,
        )
    # httpx.Client.stream was called with the custom headers
    call_args = mock_stream.call_args
    # headers is a kwarg
    passed_headers = call_args.kwargs.get("headers", {})
    assert passed_headers.get("Authorization") == "Bearer fake-token-123"
