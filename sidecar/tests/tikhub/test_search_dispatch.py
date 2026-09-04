"""runner.get_adapter 按 mining_data_source_mode 分派；_data_source_mode 读 AppConfig
（monkeypatch csm_core.config.get_config —— get_config 读真实 settings，不受 settings_path 影响）。"""
from types import SimpleNamespace

import pytest

from csm_core.mining import runner
from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter
from csm_core.mining.platforms.tikhub_search import TikHubSearchAdapter


def _cfg(mode):
    return SimpleNamespace(
        mining_data_source_mode=mode,
        monitor=SimpleNamespace(tikhub_base_url="https://api.tikhub.dev"),
    )


@pytest.fixture
def cfg_mode(monkeypatch):
    def _set(mode):
        monkeypatch.setattr("csm_core.config.get_config", lambda: _cfg(mode))
    return _set


@pytest.mark.parametrize("platform", ["douyin", "bilibili", "kuaishou"])
def test_tikhub_mode_returns_tikhub_adapter(platform):
    a = runner.get_adapter(platform, "tikhub_api")
    assert isinstance(a, TikHubSearchAdapter) and a.platform == platform


def test_local_mode_returns_browser_adapters():
    assert isinstance(runner.get_adapter("douyin", "local"), DouyinSearchAdapter)
    assert isinstance(runner.get_adapter("bilibili", "local"), BilibiliSearchAdapter)
    assert isinstance(runner.get_adapter("kuaishou", "local"), KuaishouSearchAdapter)


def test_mode_none_reads_config(cfg_mode):
    cfg_mode("local")
    assert isinstance(runner.get_adapter("douyin"), DouyinSearchAdapter)
    cfg_mode("tikhub_api")
    assert isinstance(runner.get_adapter("douyin"), TikHubSearchAdapter)


def test_data_source_mode_reads_config_and_defaults(cfg_mode, monkeypatch):
    cfg_mode("local")
    assert runner._data_source_mode() == "local"
    cfg_mode("tikhub_api")
    assert runner._data_source_mode() == "tikhub_api"
    cfg_mode("garbage")
    assert runner._data_source_mode() == "tikhub_api"          # 非法值回落默认

    def boom():
        raise RuntimeError("no settings")

    monkeypatch.setattr("csm_core.config.get_config", boom)
    assert runner._data_source_mode() == "tikhub_api"          # 读不到也回落默认


def test_unknown_platform_raises_in_both_modes():
    with pytest.raises(ValueError):
        runner.get_adapter("xhs", "tikhub_api")
    with pytest.raises(ValueError):
        runner.get_adapter("xhs", "local")
