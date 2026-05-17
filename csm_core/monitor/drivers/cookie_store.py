"""Re-export shim. Real implementation lives in csm_core.browser_infra.cookie_store.

Kept here so existing imports like ``from csm_core.monitor.drivers.cookie_store
import CookieStore`` continue to work after the v0.5 browser_infra extraction.
"""
from csm_core.browser_infra.cookie_store import *  # noqa: F401,F403
from csm_core.browser_infra.cookie_store import CookieStore  # noqa: F401  # explicit re-export
