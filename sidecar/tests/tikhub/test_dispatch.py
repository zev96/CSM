from unittest.mock import MagicMock
from csm_sidecar.services.monitor_loop import MonitorLoop
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.tikhub import build_api_adapters
from csm_core.monitor.tikhub import client as tclient


def _loop(mode, api_adapters=None):
    return MonitorLoop(event_sink=lambda e: None,
                       api_adapters=api_adapters or {}, data_source_mode=mode)


def test_local_mode_uses_local_adapter():
    loop = _loop("local", api_adapters={"douyin_comment": object()})
    assert loop._select_adapter("douyin_comment") is loop._adapters.get("douyin_comment")


def test_api_mode_uses_api_adapter():
    api = object()
    loop = _loop("tikhub_api", api_adapters={"douyin_comment": api})
    assert loop._select_adapter("douyin_comment") is api


def test_api_mode_out_of_scope_falls_back_local():
    loop = _loop("tikhub_api", api_adapters={"douyin_comment": object()})
    assert loop._select_adapter("baidu_keyword") is loop._adapters.get("baidu_keyword")


def test_build_api_adapters_has_five_types():
    ad = build_api_adapters(lambda: MagicMock(), lambda p, c=None: "k")
    assert set(ad) == {"zhihu_question", "douyin_comment", "bilibili_comment",
                       "kuaishou_comment", "xiaohongshu_comment"}


def test_local_mode_still_routes_api_only_type_to_api_adapter():
    """小红书评论留存没有本地路径:即使全局开关是 local,也走 TikHub 适配器。"""
    api = object()
    loop = _loop("local", api_adapters={"xiaohongshu_comment": api, "douyin_comment": object()})
    assert loop._select_adapter("xiaohongshu_comment") is api
    assert loop._uses_api("xiaohongshu_comment") is True
    # 其它类型仍严格按开关:local 下抖音走本地
    assert loop._select_adapter("douyin_comment") is loop._adapters.get("douyin_comment")
    assert loop._uses_api("douyin_comment") is False


def test_api_only_type_without_api_adapter_falls_back_to_placeholder():
    """API 适配器缺席(未注入)时回落注册表占位适配器,而不是 None(unknown task type)。"""
    loop = _loop("local", api_adapters={})
    assert loop._select_adapter("xiaohongshu_comment") is loop._adapters.get("xiaohongshu_comment")
    assert loop._uses_api("xiaohongshu_comment") is False


def test_api_mode_balance_exhausted_short_circuits():
    tclient.reset_balance_latch()
    tclient._trip_balance_latch()
    try:
        events = []
        api = MagicMock()
        loop = MonitorLoop(event_sink=lambda e: events.append(e),
                           api_adapters={"douyin_comment": api}, data_source_mode="tikhub_api")
        task = MonitorTask(id=1, type="douyin_comment", name="t", target_url="x", config={})
        loop._run_one(task)
        api.fetch.assert_not_called()          # 余额闩置位 → 短路,不调 adapter、不发请求
        assert any(e.kind == "failed" and "余额" in (e.error or "") for e in events)
    finally:
        tclient.reset_balance_latch()
