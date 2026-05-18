"""Tests for:
- _call_adapter_with_status in runner (RiskControlException → risk_control,
  login-wall URL → needs_login, normal → unchanged)
- GET /api/mining/credentials route
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from csm_core.mining.models import SearchOutcome, ProgressUpdate
from csm_core.mining import runner as mining_runner
from csm_core.monitor.drivers.risk_detector import RiskControlException, RiskSignal


# ── Helper factories ──────────────────────────────────────────────────────────

def _make_page(url: str) -> MagicMock:
    page = MagicMock()
    page.url = url
    return page


def _cancel() -> threading.Event:
    return threading.Event()


def _noop_card(c):
    pass


def _noop_progress(pu):
    pass


# ── _call_adapter_with_status: RiskControlException → risk_control ────────────

class _RiskAdapter:
    platform = "douyin"

    def search(self, **kwargs):
        raise RiskControlException(
            RiskSignal(layer="dom", detail="#captcha-mask"),
            progress=5,
        )


def test_risk_control_exception_yields_risk_control_status():
    outcome = mining_runner._call_adapter_with_status(
        _RiskAdapter(),
        keyword="test",
        target_count=10,
        on_card=_noop_card,
        on_progress=_noop_progress,
        cancel_event=_cancel(),
    )
    assert outcome.status == "risk_control"
    assert outcome.cards_emitted == 0
    assert outcome.status_detail is not None
    assert "dom" in outcome.status_detail
    assert "captcha" in outcome.status_detail


# ── _call_adapter_with_status: login-wall URL → needs_login ──────────────────

class _ZeroResultAdapter:
    platform = "douyin"

    def search(self, **kwargs):
        return SearchOutcome(platform="douyin", status="done", cards_emitted=0)


def test_login_wall_url_upgrades_to_needs_login():
    outcome = mining_runner._call_adapter_with_status(
        _ZeroResultAdapter(),
        keyword="test",
        target_count=10,
        on_card=_noop_card,
        on_progress=_noop_progress,
        cancel_event=_cancel(),
        get_current_url=lambda: "https://passport.douyin.com/web/login",
    )
    assert outcome.status == "needs_login"
    assert outcome.status_detail is not None
    assert "passport.douyin.com" in outcome.status_detail


def test_login_wall_url_kuaishou_id_host():
    outcome = mining_runner._call_adapter_with_status(
        _ZeroResultAdapter(),
        keyword="test",
        target_count=10,
        on_card=_noop_card,
        on_progress=_noop_progress,
        cancel_event=_cancel(),
        get_current_url=lambda: "https://id.kuaishou.com/pass/kuaishou/login",
    )
    assert outcome.status == "needs_login"
    assert "id.kuaishou.com" in (outcome.status_detail or "")


# ── _call_adapter_with_status: normal outcome stays unchanged ─────────────────

class _GoodAdapter:
    platform = "bilibili"

    def search(self, **kwargs):
        return SearchOutcome(platform="bilibili", status="done", cards_emitted=3)


def test_normal_outcome_stays_done():
    outcome = mining_runner._call_adapter_with_status(
        _GoodAdapter(),
        keyword="test",
        target_count=10,
        on_card=_noop_card,
        on_progress=_noop_progress,
        cancel_event=_cancel(),
        get_current_url=lambda: "https://search.bilibili.com/all?keyword=test",
    )
    assert outcome.status == "done"
    assert outcome.cards_emitted == 3
    assert outcome.status_detail is None


def test_cancelled_zero_result_not_upgraded_to_needs_login():
    """Cancelled outcomes keep status=cancelled even if URL looks like login wall."""
    class CancelledAdapter:
        platform = "douyin"

        def search(self, **kwargs):
            return SearchOutcome(platform="douyin", status="cancelled", cards_emitted=0)

    outcome = mining_runner._call_adapter_with_status(
        CancelledAdapter(),
        keyword="test",
        target_count=10,
        on_card=_noop_card,
        on_progress=_noop_progress,
        cancel_event=_cancel(),
        get_current_url=lambda: "https://passport.douyin.com/web/login",
    )
    assert outcome.status == "cancelled"


# ── GET /api/mining/credentials route ────────────────────────────────────────

class TestMiningCredentialsRoute:
    def test_credentials_endpoint_unknown_platform_400(self, client):
        r = client.get("/api/mining/credentials?platform=zhihu")
        assert r.status_code == 400
        assert "zhihu" in r.json()["detail"]

    def test_credentials_endpoint_returns_expected_keys(self, client, monitor_db: Path):
        r = client.get("/api/mining/credentials?platform=douyin")
        assert r.status_code == 200
        data = r.json()
        assert "has_cookies" in data
        assert "last_used" in data
        assert data["platform"] == "douyin"

    def test_credentials_endpoint_bilibili(self, client, monitor_db: Path):
        r = client.get("/api/mining/credentials?platform=bilibili")
        assert r.status_code == 200
        assert r.json()["platform"] == "bilibili"

    def test_credentials_endpoint_kuaishou(self, client, monitor_db: Path):
        r = client.get("/api/mining/credentials?platform=kuaishou")
        assert r.status_code == 200
        assert r.json()["platform"] == "kuaishou"

    def test_credentials_no_cookies_by_default(self, client, monitor_db: Path):
        """Fresh DB → no credentials → has_cookies=False."""
        r = client.get("/api/mining/credentials?platform=douyin")
        assert r.status_code == 200
        assert r.json()["has_cookies"] is False
        assert r.json()["last_used"] is None
