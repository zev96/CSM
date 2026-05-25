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


# NB: ``test_kuaishou_search_uses_stealth_client_not_httpx`` and
# ``test_curl_cffi_post_accepts_data_kwarg`` lived here in v0.5.7. They
# guarded kuaishou_search.py against falling back to vanilla httpx. v0.5.8
# moved past the whole Python-client family — GraphQL POST now runs inside
# the patchright Chrome via ``page.evaluate('fetch(...)')`` because curl_cffi
# impersonate was *also* being identified by 快手's composite fingerprint
# (cookie state + device + headers, not just JA3). The v0.5.7 invariants
# don't apply to the new code path; the v0.5.8 invariants in
# ``test_v0_5_8_page_evaluate.py``守 the new path instead.
#
# ``_http.build_stealth_client`` itself is kept in tree (and still tested
# above) so future B-站 search refactors can use it without re-deriving
# the curl_cffi setup.
