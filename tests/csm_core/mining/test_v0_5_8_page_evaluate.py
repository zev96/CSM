"""v0.5.8 — kuaishou GraphQL POST moved into the patchright Chrome via
``page.evaluate('fetch(...)')`` because curl_cffi impersonate=chrome120
(v0.5.7) was *also* getting shadow-banned. 快手 server checks a composite
fingerprint (TLS + cookie state + device hints + header order), so any
Python-side client gets caught eventually.

Running the POST from the real browser's JS context with
``credentials: 'include'`` makes server see a request indistinguishable
from a normal user XHR — same TLS handshake, same cookie behaviour,
same headers/order. Even if 快手 later tightens fingerprinting, this
path is the *one* the website itself uses, so we'd break together.

This file pins the invariants:
1. kuaishou_search uses page.evaluate (not _http stealth/httpx)
2. Raw response logging is in place (so the next platform-side change
   leaves a diagnostic crumb instead of "completed 0 视频" silence)
3. The webPageArea variable is sent (schema-required field; absent in
   v0.5.0–v0.5.7)
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
KUAISHOU_SEARCH_PY = (
    REPO_ROOT / "csm_core" / "mining" / "platforms" / "kuaishou_search.py"
)


def test_graphql_post_runs_inside_patchright_page():
    """The POST must go through ``page.evaluate(...)`` so it inherits the
    real Chrome's TLS handshake + cookie jar.

    Regression fence: if a later refactor switches back to a Python-side
    HTTP client (httpx / curl_cffi / aiohttp / whatever), 快手 server
    will start shadow-banning again and the symptom is the v0.5.6
    "completed 0 视频" silent failure. This test fires loudly before
    anyone ships that.
    """
    src = KUAISHOU_SEARCH_PY.read_text(encoding="utf-8")

    assert "page.evaluate(" in src, (
        "kuaishou_search.py must call page.evaluate(...) for the GraphQL POST — "
        "v0.5.8 root-cause fix. Server-side composite fingerprint identifies "
        "any out-of-browser Python client; only fetch() from inside the "
        "patchright Chrome looks legitimate."
    )
    # 守 fetch in JS has credentials:'include' — without it the browser
    # won't send the BrowserContext cookies and the GraphQL endpoint sees
    # an anonymous request → 401/empty.
    assert "credentials: 'include'" in src or "credentials:'include'" in src, (
        "fetch() inside page.evaluate must set credentials:'include' so the "
        "BrowserContext cookies actually go on the wire — otherwise GraphQL "
        "treats the request as anonymous and returns empty feeds."
    )


def test_no_python_side_http_client_for_kuaishou_graphql():
    """v0.5.8 deliberately drops both vanilla httpx and curl_cffi from
    the kuaishou GraphQL path. If they sneak back in, the JA3 / composite
    fingerprint shadow-ban returns.
    """
    src = KUAISHOU_SEARCH_PY.read_text(encoding="utf-8")

    # build_stealth_client (curl_cffi) was the v0.5.7 attempt — server
    # caught it too. Don't let a refactor "while I'm here" re-import it.
    assert "_http.build_stealth_client" not in src, (
        "kuaishou_search.py must NOT call _http.build_stealth_client — "
        "v0.5.7 used it but 快手 server's composite fingerprint still "
        "identified curl_cffi. The page.evaluate fetch path replaces it."
    )
    assert "_http.build_httpx_client" not in src, (
        "kuaishou_search.py must NOT call _http.build_httpx_client — "
        "vanilla httpx hit the original JA3 shadow-ban (v0.5.6 symptom)."
    )


def test_raw_response_logging_present():
    """v0.5.8 logs the first 500 chars of server response. Without this,
    the next time something changes server-side we'd be back to debugging
    silent "0 视频" with no idea what server actually returned.

    Cost: one INFO line per page in sidecar.log. Trivial.
    """
    src = KUAISHOU_SEARCH_PY.read_text(encoding="utf-8")

    assert "first500" in src or "body_text[:500]" in src, (
        "kuaishou_search.py must log the raw response body (first ~500 "
        "chars). Otherwise next time the symptom is 'completed 0 视频' "
        "we have no diagnostic crumb and have to ship another debug "
        "release just to see what server returned."
    )


def test_webpagearea_variable_is_sent():
    """v0.5.8 fills in the ``webPageArea`` GraphQL variable that the
    schema accepts but earlier versions left absent. Some 快手 gateways
    do strict variable validation; sending an empty string is the safe
    bet (MediaCrawler does the same in its newer revisions).
    """
    src = KUAISHOU_SEARCH_PY.read_text(encoding="utf-8")

    assert '"webPageArea"' in src, (
        "GraphQL variables payload must include webPageArea — the schema "
        "(see _vendor/mc_kuaishou_search.graphql) declares it; some "
        "server-side validation paths reject the request silently when "
        "it's missing."
    )


def test_kuaishou_search_no_longer_imports_http_module():
    """After v0.5.8 the module no longer needs cookies_from_context or
    either client builder. Keep the import surface minimal so it's
    obvious the module owns the GraphQL flow.
    """
    src = KUAISHOU_SEARCH_PY.read_text(encoding="utf-8")

    assert "from csm_core.mining.platforms import _http" not in src, (
        "kuaishou_search.py shouldn't import _http any more — page.evaluate "
        "handles both cookie passing (credentials:'include') and the POST "
        "itself. If this import comes back, something is reverting to the "
        "v0.5.6/v0.5.7 Python-client path."
    )
