"""Thin wrapper around the platform_credentials sqlite table.

Adapters need three things from the credential pool: pick a cookie to
use for the next request, mark it good or bad based on the response,
and a way for the user to add/remove cookies. Everything else (the
fail_count → disable threshold, ordering by least-recently-used, the
multi-account rotation policy) is hidden behind these methods.

Rotation semantics:
    - **Single-account mode** (rotation_enabled=False): always returns
      the highest-priority enabled cookie. Same behavior the store
      shipped with — backwards compatible.
    - **Multi-account mode** (rotation_enabled=True): tracks the
      currently-active cookie in memory plus a per-platform task
      counter. After ``tasks_per_account`` consecutive picks, the next
      ``pick`` advances to the next enabled cookie. On ``mark_failed``
      the active cookie is forced to cool off for ``cooldown_seconds``
      and rotation immediately advances.

Memory rotation state is intentionally **not** persisted: a sidecar
restart resets to "pick best available" which is the right behavior
(stale active-cookie pointers across restarts cause confusing UX).
"""
from __future__ import annotations
from dataclasses import dataclass
from threading import Lock
from typing import Any

from csm_core.monitor import storage


# A cookie is auto-disabled after this many consecutive failures. Tunable
# constant rather than a config knob — the threshold isn't user-facing
# guidance, it's just risk-control hygiene.
AUTO_DISABLE_FAIL_COUNT = 5

# Default cooldown when the caller doesn't pass one explicitly. Matches
# the MonitorConfig default; the real value is plumbed in from settings
# at the adapter level so users who set 60min in the UI get 60min.
DEFAULT_COOLDOWN_SECONDS = 30 * 60

# How many consecutive failures before we actually start cooling the
# cookie down. 1 was too aggressive for single-account users — a single
# transient /unhuman blip would lock them out for 30 minutes. With
# threshold=3 we tolerate two flukes, only park the cookie if the
# pattern repeats (which is when cooldown is actually warranted).
COOLDOWN_FAIL_THRESHOLD = 3


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

    Construction is cheap — the store keeps a tiny in-memory cursor
    (``_active_id`` + ``_active_uses``) plus a lock so a concurrent
    fetch + scheduler tick can't race the counter.

    Args:
        platform: e.g. ``"zhihu_question"`` — the value of
            ``platform_credentials.platform``.
        rotation_enabled: enable multi-account round-robin. False keeps
            behavior identical to the pre-rotation version.
        tasks_per_account: when ``rotation_enabled``, advance to the
            next cookie after this many ``pick()`` calls land on the
            same one. Clamped to >=1 (0 would mean "never rotate" but
            we'd rather make rotation_enabled=False the explicit knob).
        cooldown_seconds: how long ``mark_failed`` parks a cookie before
            it can be picked again. Persists across sidecar restarts
            via ``platform_credentials.cooldown_until``.
    """

    def __init__(
        self,
        platform: str,
        *,
        rotation_enabled: bool = False,
        tasks_per_account: int = 2,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self.platform = platform
        self.rotation_enabled = bool(rotation_enabled)
        self.tasks_per_account = max(1, int(tasks_per_account))
        self.cooldown_seconds = max(0, int(cooldown_seconds))
        # In-memory rotation cursor. ``_active_id == None`` means "no
        # active selection yet; pick the highest-priority available on
        # next pick()". This naturally re-seeds after the active cookie
        # gets disabled or cooled-down.
        self._active_id: int | None = None
        self._active_uses: int = 0
        self._lock = Lock()

    # ── Pick ───────────────────────────────────────────────────────────
    def pick(self) -> Credential | None:
        """Return the cookie the next fetch should use, or None if none available.

        Single-account mode: returns ``rows[0]`` from
        ``list_credentials(skip_cooldown=True)`` — same shape as before
        the rotation feature.

        Multi-account mode:
            - If no active cookie set, pick the best available and
              start a counter at 1.
            - If active cookie still in pool and uses < N, reuse it
              and bump counter.
            - Otherwise advance: pick the next cookie *after* the
              current active id in the priority list (wrap to head if
              we're at the tail), counter resets to 1.
        """
        rows = storage.list_credentials(
            self.platform, enabled_only=True, skip_cooldown=True,
        )
        if not rows:
            return None

        with self._lock:
            if not self.rotation_enabled:
                # Single-account path: storage ordering already picks
                # the least-failed least-recently-used row; just return
                # it. Don't update the rotation cursor — leaving it
                # untouched means flipping rotation on later starts
                # fresh.
                return _row_to_cred(rows[0])

            # Multi-account path
            available_ids = [r["id"] for r in rows]
            if self._active_id not in available_ids:
                # Active cookie went cold (disabled / cooldown) or first
                # call — pick the best and start fresh.
                chosen = rows[0]
                self._active_id = chosen["id"]
                self._active_uses = 1
                return _row_to_cred(chosen)

            if self._active_uses < self.tasks_per_account:
                # Stay on current active.
                self._active_uses += 1
                chosen = next(r for r in rows if r["id"] == self._active_id)
                return _row_to_cred(chosen)

            # Rotation due: advance to the next available cookie after
            # _active_id in priority order, wrapping. This gives a
            # deterministic round-robin rather than "always jump back
            # to the lowest-fail-count one" — important for actually
            # spreading load.
            cur_idx = available_ids.index(self._active_id)
            next_idx = (cur_idx + 1) % len(available_ids)
            chosen_row = rows[next_idx]
            self._active_id = chosen_row["id"]
            self._active_uses = 1
            return _row_to_cred(chosen_row)

    # ── Outcome reporting ─────────────────────────────────────────────
    def mark_ok(self, cred: Credential) -> None:
        storage.mark_credential_used(cred.id, success=True)

    def mark_failed(self, cred: Credential) -> None:
        storage.mark_credential_used(cred.id, success=False)
        # Auto-disable after N consecutive failures — the user can flip
        # the row back to enabled in the Cookie pool UI once they paste
        # a fresh cookie string. Disabling rather than deleting keeps
        # the label / fail history visible for debugging.
        if cred.fail_count + 1 >= AUTO_DISABLE_FAIL_COUNT:
            storage.get_conn().execute(
                "UPDATE platform_credentials SET enabled=0 WHERE id=?",
                (cred.id,),
            )

        # Cooldown bookkeeping — only kicks in after a consistent run
        # of failures. A single transient failure (zhihu flake, network
        # blip) shouldn't lock the cookie out for 30 minutes, especially
        # for single-account users who have no spare to rotate to.
        # We use the in-DB fail_count *after* the bump we just did
        # (mark_credential_used incremented it on the SQL side), which
        # equals cred.fail_count + 1.
        new_fail_count = cred.fail_count + 1
        if self.cooldown_seconds > 0 and new_fail_count >= COOLDOWN_FAIL_THRESHOLD:
            storage.set_credential_cooldown(cred.id, self.cooldown_seconds)

        # In rotation mode, advance immediately so the next pick() goes
        # to a fresh cookie rather than retrying the failed one (it'll
        # be filtered out by skip_cooldown anyway, but resetting the
        # cursor avoids one wasted DB round-trip).
        if self.rotation_enabled:
            with self._lock:
                if self._active_id == cred.id:
                    self._active_id = None
                    self._active_uses = 0

    # ── CRUD passthroughs ─────────────────────────────────────────────
    def add(self, cookies_text: str, label: str = "", user_agent: str = "") -> int:
        return storage.add_credential(self.platform, cookies_text, label, user_agent)

    def list_all(self) -> list[dict[str, Any]]:
        return storage.list_credentials(self.platform, enabled_only=False)

    def remove(self, cred_id: int) -> None:
        storage.delete_credential(cred_id)


def _row_to_cred(row: dict[str, Any]) -> Credential:
    return Credential(
        id=row["id"],
        platform=row["platform"],
        label=row["label"] or "",
        cookies_text=row["cookies_text"],
        user_agent=row["user_agent"] or "",
        enabled=bool(row["enabled"]),
        fail_count=int(row["fail_count"]),
    )
