"""Browser / cookie driver helpers shared by platform adapters."""
from .drission_pool import get_page, shutdown
from .cookie_store import CookieStore

__all__ = ["get_page", "shutdown", "CookieStore"]
