"""Tests for CookieStore — multi-account rotation + cooldown.

Covers the behavior the user sees:
- Single-account mode is unchanged (always picks rows[0])
- Multi-account mode round-robins after N picks
- Failure cools the cookie + immediately rotates
- Cooldown filters cookies out of pick()
- Disabled cookies stay out of rotation
"""
from __future__ import annotations
import threading
import time
from pathlib import Path

import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.drivers.cookie_store import CookieStore


@pytest.fixture
def fresh_db(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    yield tmp_path / "monitor.db"
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


def _seed(n: int) -> list[int]:
    """Add ``n`` zhihu cookies, return their ids in insertion order."""
    return [
        storage.add_credential(
            "zhihu_question",
            cookies_text=f"z_c0=token{i}",
            label=f"号 {i+1}",
        )
        for i in range(n)
    ]


# ── Single-account mode (rotation disabled) ────────────────────────────
class TestSingleAccount:
    def test_pick_returns_only_cookie(self, fresh_db):
        _seed(1)
        store = CookieStore("zhihu_question", rotation_enabled=False)
        c = store.pick()
        assert c is not None
        assert c.label == "号 1"

    def test_pick_does_not_rotate_when_disabled(self, fresh_db):
        ids = _seed(3)
        store = CookieStore(
            "zhihu_question", rotation_enabled=False, tasks_per_account=1,
        )
        # 10 picks all land on the same cookie (rows[0] = lowest fail).
        picks = {store.pick().id for _ in range(10)}
        assert picks == {ids[0]}

    def test_returns_none_when_empty(self, fresh_db):
        store = CookieStore("zhihu_question", rotation_enabled=False)
        assert store.pick() is None


# ── Multi-account rotation ─────────────────────────────────────────────
class TestRotation:
    def test_rotates_after_n_picks(self, fresh_db):
        ids = _seed(3)
        store = CookieStore(
            "zhihu_question", rotation_enabled=True, tasks_per_account=2,
        )
        # First 2 picks → cookie A; next 2 → B; next 2 → C; then wrap to A.
        sequence = [store.pick().id for _ in range(8)]
        # Distinct cookies in expected wrap order. First 2 of each must be
        # the same cookie; after exhausting all 3, picks 7-8 wrap to the
        # head of the rotation (back to the first cookie).
        a, b, c = sequence[0], sequence[2], sequence[4]
        assert sequence == [a, a, b, b, c, c, a, a]
        assert {a, b, c} == set(ids)

    def test_tasks_per_account_one_rotates_every_pick(self, fresh_db):
        ids = _seed(3)
        store = CookieStore(
            "zhihu_question", rotation_enabled=True, tasks_per_account=1,
        )
        seq = [store.pick().id for _ in range(6)]
        # Each pick advances → strict round-robin.
        assert seq[0] != seq[1] != seq[2]
        # Two full laps over the 3-cookie ring.
        assert seq[:3] == seq[3:]


# ── Failure + cooldown ─────────────────────────────────────────────────
class TestFailureAndCooldown:
    def test_mark_failed_sets_cooldown_after_threshold(self, fresh_db):
        """Cooldown kicks in only after COOLDOWN_FAIL_THRESHOLD consecutive
        failures — a single transient failure shouldn't park the cookie
        for 30 minutes (especially harmful for single-account users)."""
        from csm_core.monitor.drivers.cookie_store import COOLDOWN_FAIL_THRESHOLD
        from csm_core.monitor.drivers.cookie_store import Credential
        _seed(2)
        store = CookieStore(
            "zhihu_question", rotation_enabled=True,
            tasks_per_account=5, cooldown_seconds=600,
        )
        c = store.pick()
        # Call mark_failed THRESHOLD times in a row on the same cookie,
        # re-reading fail_count from the DB each iteration so we pass
        # an accurate "current state" Credential into mark_failed.
        for _ in range(COOLDOWN_FAIL_THRESHOLD):
            rows = storage.list_credentials("zhihu_question", enabled_only=False)
            cur = next(r for r in rows if r["id"] == c.id)
            store.mark_failed(Credential(
                id=cur["id"], platform=cur["platform"],
                label=cur["label"] or "", cookies_text=cur["cookies_text"],
                user_agent=cur["user_agent"] or "",
                enabled=bool(cur["enabled"]), fail_count=int(cur["fail_count"]),
            ))

        # After threshold, the failed cookie is in cooldown → pick()
        # returns the other one.
        c2 = store.pick()
        assert c2 is not None
        assert c2.id != c.id

    def test_single_failure_does_not_cooldown(self, fresh_db):
        """One transient failure should NOT lock out the cookie — single-
        account users would otherwise lose monitoring for 30 minutes on
        any flake."""
        ids = _seed(1)
        store = CookieStore(
            "zhihu_question", rotation_enabled=False, cooldown_seconds=600,
        )
        c = store.pick()
        store.mark_failed(c)
        # Cookie is still pickable — fail_count is 1 < threshold (3).
        c2 = store.pick()
        assert c2 is not None
        assert c2.id == ids[0]

    def test_cooldown_filters_pick(self, fresh_db):
        ids = _seed(2)
        # Cooldown the first cookie 1 hour in the future via storage API
        # directly (bypassing CookieStore.mark_failed which also bumps
        # fail_count — we want a pure cooldown test).
        storage.set_credential_cooldown(ids[0], 3600)

        store = CookieStore("zhihu_question", rotation_enabled=False)
        c = store.pick()
        # Only the non-cooled cookie comes back.
        assert c is not None
        assert c.id == ids[1]

    def test_cooldown_expires(self, fresh_db):
        ids = _seed(1)
        # 1-second cooldown → eligible again after sleep.
        storage.set_credential_cooldown(ids[0], 1)
        store = CookieStore("zhihu_question", rotation_enabled=False)
        assert store.pick() is None  # still cooling
        time.sleep(1.2)
        assert store.pick() is not None  # now eligible

    def test_auto_disable_after_5_failures(self, fresh_db):
        ids = _seed(2)
        store = CookieStore(
            "zhihu_question", rotation_enabled=False, cooldown_seconds=0,
        )
        # Repeatedly fail the same cookie. The store auto-disables it
        # at fail_count >= 5. cooldown=0 so each pick can re-fetch the
        # same row (otherwise cooldown would short-circuit the loop).
        c0_id = ids[0]
        for _ in range(5):
            # Re-read fail_count from DB each loop so the threshold check
            # in mark_failed (cred.fail_count + 1 >= 5) sees fresh counts.
            rows = storage.list_credentials("zhihu_question", enabled_only=True)
            cur = next(r for r in rows if r["id"] == c0_id)
            from csm_core.monitor.drivers.cookie_store import Credential
            store.mark_failed(Credential(
                id=cur["id"], platform=cur["platform"],
                label=cur["label"] or "", cookies_text=cur["cookies_text"],
                user_agent=cur["user_agent"] or "",
                enabled=bool(cur["enabled"]), fail_count=int(cur["fail_count"]),
            ))

        # The cookie should now be disabled — pick() returns the other one.
        c = store.pick()
        assert c is not None
        assert c.id == ids[1]


# ── Rotation edge cases ────────────────────────────────────────────────
class TestRotationEdges:
    def test_active_cookie_disappears_picks_best_available(self, fresh_db):
        """If the active cookie gets disabled mid-rotation, pick() must
        fall back gracefully to the highest-priority remaining cookie
        rather than refusing to return one."""
        ids = _seed(3)
        store = CookieStore(
            "zhihu_question", rotation_enabled=True, tasks_per_account=10,
        )
        first = store.pick()
        # Disable the active cookie out from under the store.
        storage.get_conn().execute(
            "UPDATE platform_credentials SET enabled=0 WHERE id=?", (first.id,),
        )
        # Next pick must return a different, still-enabled cookie.
        second = store.pick()
        assert second is not None
        assert second.id != first.id
        assert second.id in ids

    def test_single_cookie_with_rotation_enabled(self, fresh_db):
        """Rotation enabled but only 1 cookie → keep returning it.
        Important for users who flip the rotation switch without having
        added a second cookie yet."""
        _seed(1)
        store = CookieStore(
            "zhihu_question", rotation_enabled=True, tasks_per_account=2,
        )
        ids_seen = {store.pick().id for _ in range(5)}
        assert len(ids_seen) == 1
