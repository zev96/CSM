"""v0.5.7 — switch kuaishou_search from vanilla httpx to curl_cffi
``impersonate="chrome120"`` so 快手's GraphQL endpoint can't JA3-fingerprint
the request as scripted.

Symptoms before v0.5.7 (with v0.5.6's .graphql-in-bundle fix in place):
the POST landed 200 OK but ``visionSearchPhoto.feeds`` was empty and
``pcursor='no_more'`` — a soft shadow-ban that looks like "no results"
but actually means "we saw the fake TLS handshake and dropped you".

These tests守住 the fix's invariants without requiring a real network
call to 快手:

1. ``_http.build_stealth_client`` exists and returns a curl_cffi Session
2. It's actually configured with ``impersonate='chrome120'``
3. ``kuaishou_search.py`` calls ``build_stealth_client`` (not the vanilla
   httpx variant) — guards against accidental reverts
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_build_stealth_client_returns_curl_cffi_session():
    """The returned client must be a curl_cffi Session — not httpx.Client."""
    from csm_core.mining.platforms._http import build_stealth_client

    client = build_stealth_client(
        cookies_str="userId=123; passToken=abc",
        user_agent="Mozilla/5.0 Test",
        referer="https://www.kuaishou.com/search/video",
    )
    try:
        import curl_cffi.requests as cc_requests
        assert isinstance(client, cc_requests.Session), (
            f"build_stealth_client returned {type(client).__module__}.{type(client).__name__}, "
            "expected curl_cffi.requests.Session — vanilla httpx would NOT be "
            "able to impersonate Chrome's TLS handshake, leaving us back at "
            "the v0.5.6 shadow-ban (200 OK + empty feeds)"
        )
    finally:
        client.close()


def test_build_stealth_client_impersonates_chrome120():
    """The Session must request Chrome 120 impersonation — otherwise
    curl_cffi falls back to its default profile which doesn't reliably
    match Chrome's JA3 fingerprint.

    Reads the underlying ``_impersonate`` field that curl_cffi stores on
    the Session. If curl_cffi renames the attribute in a future version
    this test fires loudly — better than silently degrading to default.
    """
    from csm_core.mining.platforms._http import build_stealth_client

    client = build_stealth_client(
        cookies_str="userId=123",
        user_agent="Mozilla/5.0 Test",
        referer="https://www.kuaishou.com/search/video",
    )
    try:
        impersonate = getattr(client, "_impersonate", None) or getattr(
            client, "impersonate", None
        )
        assert impersonate == "chrome120", (
            f"stealth client impersonate={impersonate!r}, expected 'chrome120' — "
            "without it, curl_cffi falls back to a default profile that 快手 "
            "will still recognize as scripted"
        )
    finally:
        client.close()


def test_build_stealth_client_carries_cookie_and_referer():
    """Cookie + Referer must be passed through into Session.headers so
    the server sees them on every request (not just first)."""
    from csm_core.mining.platforms._http import build_stealth_client

    cookie = "userId=42; passToken=xyz"
    client = build_stealth_client(
        cookies_str=cookie,
        user_agent="Mozilla/5.0 Custom",
        referer="https://www.kuaishou.com/search/video",
        extra_headers={"Content-Type": "application/json"},
    )
    try:
        assert client.headers.get("Cookie") == cookie
        assert client.headers.get("Referer") == "https://www.kuaishou.com/search/video"
        assert client.headers.get("User-Agent") == "Mozilla/5.0 Custom"
        assert client.headers.get("Content-Type") == "application/json"
    finally:
        client.close()


def test_kuaishou_search_uses_stealth_client_not_httpx():
    """Guard: kuaishou_search.py must call ``build_stealth_client``, not
    ``build_httpx_client``. If someone later reverts this in a refactor,
    快手 抓取 will silently fall back to the v0.5.6 shadow-ban state
    (200 OK + 0 cards) — a really nasty regression to debug because
    nothing crashes.
    """
    src = (
        REPO_ROOT / "csm_core" / "mining" / "platforms" / "kuaishou_search.py"
    ).read_text(encoding="utf-8")

    assert "_http.build_stealth_client" in src, (
        "kuaishou_search.py must call _http.build_stealth_client(...) — "
        "the JA3 fingerprint fix from v0.5.7. If you reverted to "
        "build_httpx_client the symptom is 0 视频 + 'completed' status."
    )
    assert "_http.build_httpx_client" not in src, (
        "kuaishou_search.py still references build_httpx_client (vanilla "
        "httpx). That's the variant 快手 server shadow-bans — switch to "
        "build_stealth_client."
    )


def test_curl_cffi_post_accepts_data_kwarg():
    """curl_cffi.Session.post takes ``data=`` (NOT httpx's ``content=``).
    kuaishou_search.py was updated to use ``data=`` in v0.5.7; if anyone
    flips it back to ``content=``, every POST will TypeError at runtime.

    We check the kuaishou_search source rather than the curl_cffi API
    so the test doesn't break if curl_cffi adds a ``content=`` alias.
    """
    src = (
        REPO_ROOT / "csm_core" / "mining" / "platforms" / "kuaishou_search.py"
    ).read_text(encoding="utf-8")

    assert "client.post(_GRAPHQL_ENDPOINT, data=payload)" in src, (
        "kuaishou_search.py must call client.post(..., data=payload) — "
        "curl_cffi's Session.post takes ``data=``, not httpx's ``content=``"
    )
