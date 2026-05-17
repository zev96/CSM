"""Regression test: monitor.drivers and monitor.rate_limit re-export shims work.

After moving browser primitives up to csm_core/browser_infra/, every old
import path must still resolve to the same object as the new path.
A single failure here means an outside caller (or the bundled exe) breaks.
"""
import importlib


def _assert_same_object(old_path: str, new_path: str, attr: str) -> None:
    old_mod = importlib.import_module(old_path)
    new_mod = importlib.import_module(new_path)
    assert getattr(old_mod, attr) is getattr(new_mod, attr), (
        f"{old_path}.{attr} is not {new_path}.{attr} — shim re-export broken"
    )


def test_cookie_store_reexport():
    _assert_same_object(
        "csm_core.monitor.drivers.cookie_store",
        "csm_core.browser_infra.cookie_store",
        "CookieStore",
    )


def test_ua_pool_reexport_module_loads():
    # ua_pool has functions, not a single class — just verify both modules
    # have the same set of public attributes.
    old = importlib.import_module("csm_core.monitor.drivers.ua_pool")
    new = importlib.import_module("csm_core.browser_infra.ua_pool")
    old_public = {a for a in dir(old) if not a.startswith("_")}
    new_public = {a for a in dir(new) if not a.startswith("_")}
    # Old shim should export at least what new module exports.
    missing = new_public - old_public
    # Allow extras (re-export `*` may pull module-level names) but no missing.
    assert not missing, f"missing on shim: {missing}"


def test_rate_limit_reexport():
    for sym in ("RequestPacer", "CircuitBreaker", "get_pacer", "get_breaker"):
        _assert_same_object(
            "csm_core.monitor.rate_limit",
            "csm_core.browser_infra.rate_limit",
            sym,
        )


def test_patchright_pool_reexport():
    for sym in ("ensure_browsers_path", "get_page", "shutdown"):
        _assert_same_object(
            "csm_core.monitor.drivers.patchright_pool",
            "csm_core.browser_infra.patchright_pool",
            sym,
        )


def test_interactive_login_reexport_loads():
    # Just verify importing the shim doesn't ImportError.
    importlib.import_module("csm_core.monitor.drivers.interactive_login")
    importlib.import_module("csm_core.browser_infra.interactive_login")
