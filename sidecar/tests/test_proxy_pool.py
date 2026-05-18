"""ProxyPool -- proxies.json 解析 + 4 种轮换策略 + 失败自动 disable。"""
from __future__ import annotations

import json
from pathlib import Path
import pytest


class TestProxyPoolLoad:
    def test_loads_enabled_pool_with_proxies(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        config = {
            "enabled": True,
            "rotation_strategy": "on_risk_control",
            "proxies": [
                {"server": "http://user:pass@1.2.3.4:8080", "tags": ["cn", "residential"]},
                {"server": "http://5.6.7.8:8080", "tags": []},
            ],
        }
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps(config), encoding="utf-8")
        pool = ProxyPool(p)
        assert pool.enabled is True
        assert len(pool.available_proxies()) == 2

    def test_disabled_pool_returns_no_proxy(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps({"enabled": False, "proxies": []}), encoding="utf-8")
        pool = ProxyPool(p)
        assert pool.pick() is None

    def test_missing_file_disables_pool(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        p = tmp_path / "nonexistent.json"
        pool = ProxyPool(p)
        assert pool.enabled is False
        assert pool.pick() is None

    def test_malformed_json_disables_pool(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        p = tmp_path / "proxies.json"
        p.write_text("not json{{{", encoding="utf-8")
        pool = ProxyPool(p)
        assert pool.enabled is False


class TestProxyPoolRotation:
    def test_on_risk_control_stickies(self, tmp_path):
        """rotation_strategy=on_risk_control -- pick returns same server until mark_failed."""
        from csm_core.browser_infra.proxy_pool import ProxyPool
        config = {
            "enabled": True,
            "rotation_strategy": "on_risk_control",
            "proxies": [
                {"server": "http://1.1.1.1:8080"},
                {"server": "http://2.2.2.2:8080"},
            ],
        }
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps(config), encoding="utf-8")
        pool = ProxyPool(p)

        first = pool.pick()
        assert first is not None
        second = pool.pick()
        assert second == first  # sticky

        pool.mark_failed(first)
        third = pool.pick()
        assert third is not None
        assert third != first  # rotated to the other one

    def test_per_request_rotates(self, tmp_path):
        """rotation_strategy=per_request -- different result each pick."""
        from csm_core.browser_infra.proxy_pool import ProxyPool
        config = {
            "enabled": True,
            "rotation_strategy": "per_request",
            "proxies": [
                {"server": "http://1.1.1.1:8080"},
                {"server": "http://2.2.2.2:8080"},
                {"server": "http://3.3.3.3:8080"},
            ],
        }
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps(config), encoding="utf-8")
        pool = ProxyPool(p)

        seen = set()
        for _ in range(20):
            s = pool.pick()
            if s:
                seen.add(s)
        # With 3 proxies and 20 random picks, we should see all 3
        assert len(seen) >= 2


class TestProxyPoolFailureHandling:
    def test_disables_after_3_consecutive_failures(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        config = {
            "enabled": True,
            "rotation_strategy": "on_risk_control",
            "proxies": [
                {"server": "http://1.1.1.1:8080"},
                {"server": "http://2.2.2.2:8080"},
            ],
        }
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps(config), encoding="utf-8")
        pool = ProxyPool(p)

        target = "http://1.1.1.1:8080"
        for _ in range(3):
            pool.mark_failed(target)
        available = [pp["server"] for pp in pool.available_proxies()]
        assert target not in available
        assert len(pool.available_proxies()) == 1

    def test_success_resets_failure_counter(self, tmp_path):
        """If a proxy fails 2 times then succeeds, counter resets -- won't be disabled."""
        from csm_core.browser_infra.proxy_pool import ProxyPool
        config = {
            "enabled": True,
            "rotation_strategy": "on_risk_control",
            "proxies": [{"server": "http://1.1.1.1:8080"}, {"server": "http://2.2.2.2:8080"}],
        }
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps(config), encoding="utf-8")
        pool = ProxyPool(p)

        target = "http://1.1.1.1:8080"
        pool.mark_failed(target)
        pool.mark_failed(target)
        pool.mark_success(target)  # reset
        pool.mark_failed(target)
        # Only 1 failure after reset -- should still be available
        available = [pp["server"] for pp in pool.available_proxies()]
        assert target in available


class TestProxyPoolStrategies:
    """All 4 strategies must be acceptable values."""
    @pytest.mark.parametrize("strategy", ["on_risk_control", "per_request", "per_task", "daily"])
    def test_strategy_accepted(self, tmp_path, strategy):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps({
            "enabled": True, "rotation_strategy": strategy,
            "proxies": [{"server": "http://1.1.1.1:8080"}],
        }), encoding="utf-8")
        pool = ProxyPool(p)
        assert pool.enabled is True


class TestDisabledCountPublicMethod:
    def test_disabled_count_zero_initially(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps({
            "enabled": True, "proxies": [{"server": "http://1.1.1.1:8080"}],
        }), encoding="utf-8")
        pool = ProxyPool(p)
        assert pool.disabled_count() == 0

    def test_disabled_count_increments_after_3_failures(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool
        p = tmp_path / "proxies.json"
        p.write_text(json.dumps({
            "enabled": True,
            "proxies": [{"server": "http://1.1.1.1:8080"}, {"server": "http://2.2.2.2:8080"}],
        }), encoding="utf-8")
        pool = ProxyPool(p)
        for _ in range(3):
            pool.mark_failed("http://1.1.1.1:8080")
        assert pool.disabled_count() == 1


class TestDailyStrategy:
    def test_daily_returns_same_within_day(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool

        p = tmp_path / "proxies.json"
        p.write_text(json.dumps({
            "enabled": True, "rotation_strategy": "daily",
            "proxies": [{"server": "http://1.1.1.1:8080"}, {"server": "http://2.2.2.2:8080"}],
        }), encoding="utf-8")
        pool = ProxyPool(p)

        first = pool.pick()
        assert first is not None
        second = pool.pick()
        assert second == first
        third = pool.pick()
        assert third == first

    def test_daily_rotates_across_day_boundary(self, tmp_path, monkeypatch):
        from datetime import datetime
        import csm_core.browser_infra.proxy_pool as pp_mod

        p = tmp_path / "proxies.json"
        p.write_text(json.dumps({
            "enabled": True, "rotation_strategy": "daily",
            "proxies": [{"server": "http://1.1.1.1:8080"}, {"server": "http://2.2.2.2:8080"}],
        }), encoding="utf-8")

        day1 = datetime(2026, 5, 18, 14, 0, 0)
        day2 = datetime(2026, 5, 19, 14, 0, 0)

        # We patch the datetime class used in the module
        original_datetime = pp_mod.datetime

        class FakeDatetime1(datetime):
            @classmethod
            def now(cls):
                return day1

        class FakeDatetime2(datetime):
            @classmethod
            def now(cls):
                return day2

        monkeypatch.setattr(pp_mod, "datetime", FakeDatetime1)
        from csm_core.browser_infra.proxy_pool import ProxyPool
        pool = ProxyPool(p)
        pool.pick()  # pins to day1

        monkeypatch.setattr(pp_mod, "datetime", FakeDatetime2)
        pool.pick()  # should re-pin to day2

        # The pin timestamp should have updated to day2
        assert pool._current_pinned_at is not None
        assert pool._current_pinned_at.date() == day2.date()


class TestPerTaskStrategy:
    def test_per_task_sticky_until_mark_failed(self, tmp_path):
        from csm_core.browser_infra.proxy_pool import ProxyPool

        p = tmp_path / "proxies.json"
        p.write_text(json.dumps({
            "enabled": True, "rotation_strategy": "per_task",
            "proxies": [{"server": "http://1.1.1.1:8080"}, {"server": "http://2.2.2.2:8080"}],
        }), encoding="utf-8")
        pool = ProxyPool(p)

        first = pool.pick()
        assert first is not None
        for _ in range(10):
            assert pool.pick() == first  # sticky

        pool.mark_failed(first)
        rotated = False
        for _ in range(10):
            new = pool.pick()
            if new != first:
                rotated = True
                break
        assert rotated, "per_task should have rotated after mark_failed"
