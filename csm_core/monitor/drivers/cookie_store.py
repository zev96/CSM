"""Thin wrapper around the platform_credentials sqlite table.

Adapters need three things from the credential pool: pick a cookie to
use for the next request, mark it good or bad based on the response,
and a way for the user to add/remove cookies. Everything else (the
fail_count → disable threshold, ordering by least-recently-used) is
hidden behind these methods.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .. import storage


# A cookie is auto-disabled after this many consecutive failures. Tunable
# constant rather than a config knob — the threshold isn't user-facing
# guidance, it's just risk-control hygiene.
AUTO_DISABLE_FAIL_COUNT = 5


@dataclass
class Credential:
    id: int
    platform: str
    label: str
    cookies_text: str
    user_agent: str
    enabled: bool
    fail_count: int


class CookieStore:
    """Stateful helper that picks the next cookie for a platform.

    The store is intentionally a thin layer over ``storage.list_credentials`` /
    ``mark_credential_used``: those functions already implement the
    ordering ("oldest least-failed first") so the store just exposes
    ``pick`` / ``mark_ok`` / ``mark_failed`` for adapter convenience.
    """

    def __init__(self, platform: str):
        self.platform = platform

    def pick(self) -> Credential | None:
        rows = storage.list_credentials(self.platform, enabled_only=True)
        if not rows:
            return None
        r = rows[0]
        return Credential(
            id=r["id"],
            platform=r["platform"],
            label=r["label"] or "",
            cookies_text=r["cookies_text"],
            user_agent=r["user_agent"] or "",
            enabled=bool(r["enabled"]),
            fail_count=int(r["fail_count"]),
        )

    def mark_ok(self, cred: Credential) -> None:
        storage.mark_credential_used(cred.id, success=True)

    def mark_failed(self, cred: Credential) -> None:
        storage.mark_credential_used(cred.id, success=False)
        # Auto-disable when a cookie has clearly gone bad. The user can
        # re-enable via the settings UI after re-pasting fresh cookies.
        if cred.fail_count + 1 >= AUTO_DISABLE_FAIL_COUNT:
            storage.get_conn().execute(
                "UPDATE platform_credentials SET enabled=0 WHERE id=?",
                (cred.id,),
            )

    def add(self, cookies_text: str, label: str = "", user_agent: str = "") -> int:
        return storage.add_credential(self.platform, cookies_text, label, user_agent)

    def list_all(self) -> list[dict[str, Any]]:
        return storage.list_credentials(self.platform, enabled_only=False)

    def remove(self, cred_id: int) -> None:
        storage.delete_credential(cred_id)
