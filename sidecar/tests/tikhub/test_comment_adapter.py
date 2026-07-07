from unittest.mock import MagicMock
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.tikhub.comment_adapter import (
    CommentApiAdapter, DOUYIN_SPEC, BILIBILI_SPEC)

def _dtask(cfg=None):
    return MonitorTask(type="douyin_comment", name="t",
                       target_url="https://www.douyin.com/video/7abc",
                       config=cfg or {"my_comment_text": "c5", "top_n": 5})

def test_bad_id_fails():
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: MagicMock(),
                          id_extractor=lambda url: (None, ""))
    assert a.fetch(_dtask()).status == "failed"

def test_douyin_caps_at_50_scan():
    # 每页 20 条 has_more=1 → 若无 50 上限会一直翻。抖音 depth_cap=50。
    client = MagicMock()
    client.get.return_value = {"data": {"status_code": 0, "has_more": 1, "cursor": 20,
        "comments": [{"text": f"c{i}", "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]}}
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("7abc", ""))
    r = a.fetch(_dtask())
    assert client.get.call_count <= 3          # 50 条 / 20 每页 → 最多 3 页
    assert r.status == "ok"
    assert r.metric["scanned_full"] is True

def test_rank_is_global_across_pages():
    # 关键回归:rank 必须是跨页全局位置,不能每页从 1 重来。
    pages = [
        {"data": {"status_code": 0, "has_more": 1, "cursor": 20,
                  "comments": [{"text": f"a{i}", "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]}},
        {"data": {"status_code": 0, "has_more": 0, "cursor": 40,
                  "comments": [{"text": "MINE", "user": {"nickname": "u"}, "digg_count": 0}]}},
    ]
    client = MagicMock(); client.get.side_effect = pages
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(_dtask({"my_comment_text": "MINE", "top_n": 5, "scrape_top_n": 100}))
    assert r.rank == 21                        # page1 有 20 条,MINE 是全局第 21(不是第 1)

def test_douyin_platform_error_fails():
    client = MagicMock()
    client.get.return_value = {"data": {"status_code": 5, "status_msg": "参数不合法", "comments": None}}
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("7abc", ""))
    assert a.fetch(_dtask()).status == "failed"   # status_code!=0 → 整体失败

def test_bilibili_id_type_maps_to_param():
    seen = {}
    client = MagicMock()
    def cap(endpoint, params): seen.update(params); return {"data": {"code": 0, "data": {"cursor": {"is_end": True}, "replies": []}}}
    client.get.side_effect = cap
    a = CommentApiAdapter(BILIBILI_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("BV1xx", "bvid"))
    a.fetch(MonitorTask(type="bilibili_comment", name="t", target_url="x",
                        config={"my_comment_text": "z"}))
    assert seen.get("bv_id") == "BV1xx" and seen.get("mode") == 3
