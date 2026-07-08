from unittest.mock import MagicMock
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.tikhub.comment_adapter import (
    CommentApiAdapter, DOUYIN_SPEC, BILIBILI_SPEC, KUAISHOU_SPEC)

# 检索深度(当前 100)。测试从 spec 读它,改深度只动后端一处、测试自适应。
DEPTH = DOUYIN_SPEC.depth_cap

def _dtask(cfg=None):
    return MonitorTask(type="douyin_comment", name="t",
                       target_url="https://www.douyin.com/video/7abc",
                       config=cfg or {"my_comment_text": "c5", "top_n": 5})

def test_bad_id_fails():
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: MagicMock(),
                          id_extractor=lambda url: (None, ""))
    assert a.fetch(_dtask()).status == "failed"

def test_douyin_scans_up_to_depth_when_not_found():
    # 只检索前 DEPTH 名:找不到目标时最多翻到 DEPTH 条(每页 20)。
    client = MagicMock()
    client.get.side_effect = lambda e, p: {"data": {"status_code": 0, "has_more": 1,
        "cursor": p["cursor"] + 20,
        "comments": [{"text": f"c{p['cursor']+i}", "user": {"nickname": "u"}, "digg_count": 0}
                     for i in range(20)]}}
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("7abc", ""))
    r = a.fetch(_dtask({"my_comment_text": "NOPE_NOT_PRESENT", "top_n": 5}))
    assert r.status == "ok"
    assert r.metric["matched"] is False
    assert r.metric["total_fetched"] == DEPTH
    assert client.get.call_count == DEPTH // 20     # DEPTH 是每页 20 的整数倍
    assert r.metric["exhausted"] is False           # has_more 仍为真 → 没进前 DEPTH(可能超N或被删)
    assert r.metric["depth_cap"] == DEPTH           # 前端读它作为"前 N 名"的 N


def test_douyin_finds_comment_within_depth():
    # 命中在前 DEPTH(第 30 位):正常报排名。
    def page(endpoint, params):
        base = params["cursor"]
        comments = [{"text": ("MINE_30" if base + i + 1 == 30 else f"other{base+i+1}"),
                     "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]
        return {"data": {"status_code": 0, "has_more": 1, "cursor": base + 20, "comments": comments}}
    client = MagicMock(); client.get.side_effect = page
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(_dtask({"my_comment_text": "MINE_30", "top_n": 5}))
    assert r.status == "ok"
    assert r.metric["matched"] is True
    assert r.rank == 30
    assert client.get.call_count == 2           # 第30条在第2页,命中即停


def test_douyin_beyond_depth_not_matched_not_exhausted():
    # 关键语义:评论排在第 DEPTH+7 位(超出前 DEPTH)。只扫前 DEPTH → matched=False。
    # exhausted=False(评论区还有更多)→ 前端应显示"超出N名以外或被删",不是"无"。
    beyond = DEPTH + 7
    def page(endpoint, params):
        base = params["cursor"]
        comments = [{"text": ("MINE_BEYOND" if base + i + 1 == beyond else f"other{base+i+1}"),
                     "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]
        return {"data": {"status_code": 0, "has_more": 1, "cursor": base + 20, "comments": comments}}
    client = MagicMock(); client.get.side_effect = page
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(_dtask({"my_comment_text": "MINE_BEYOND", "top_n": 5}))
    assert r.status == "ok"
    assert r.metric["matched"] is False         # 不在前 DEPTH → 判未命中(=超出N)
    assert r.rank == -1
    assert r.metric["total_fetched"] == DEPTH
    assert r.metric["exhausted"] is False       # has_more 仍真 → "超出N",非"翻遍全区"


def test_douyin_underfilled_pages_do_not_false_fail():
    # D1 回归:API 每页只回 15 条(<count)且 has_more 恒真、目标不在。max_pages=(DEPTH//10)+2,
    # 欠填页也能翻够 DEPTH,不会在到达 depth 前撞熔断把任务误判成 failed。
    def page(endpoint, params):
        base = params["cursor"]
        comments = [{"text": f"u{base+i}", "user": {"nickname": "u"}, "digg_count": 0}
                    for i in range(15)]                 # 每页 15 条(欠填)
        return {"data": {"status_code": 0, "has_more": 1, "cursor": base + 15, "comments": comments}}
    client = MagicMock(); client.get.side_effect = page
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(_dtask({"my_comment_text": "ABSENT_TARGET", "top_n": 5}))
    assert r.status == "ok"                              # 关键:没被熔断成 failed
    assert r.metric["matched"] is False
    assert r.metric["total_fetched"] == DEPTH            # 欠填页也翻够了 depth
    assert client.get.call_count <= (DEPTH // 10) + 2


def test_comment_missing_my_text_fails_before_any_http():
    # D2:未填评论文本必然判 failed,必须在任何付费请求之前就返回(0 次 client.get)。
    client = MagicMock()
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(MonitorTask(type="douyin_comment", name="t", target_url="x",
                            config={"top_n": 5}))       # 无 my_comment_text
    assert r.status == "failed"
    client.get.assert_not_called()                      # 关键:没烧一分钱


def test_douyin_exhausted_true_at_exact_depth_boundary():
    # D3(边界):评论区恰好 == depth 且末页 has_more=0。旧 len<depth 判 False(错),
    # 用 scrape_top_n=40 把 depth 压到 40:2 页×20、末页到底、目标缺 → exhausted 应为 True。
    pages = [
        {"data": {"status_code": 0, "has_more": 1, "cursor": 20,
                  "comments": [{"text": f"a{i}", "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]}},
        {"data": {"status_code": 0, "has_more": 0, "cursor": 40,
                  "comments": [{"text": f"b{i}", "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]}},
    ]
    client = MagicMock(); client.get.side_effect = pages
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(_dtask({"my_comment_text": "GHOST", "top_n": 5, "scrape_top_n": 40}))
    assert r.metric["matched"] is False
    assert r.metric["total_fetched"] == 40              # == depth
    assert r.metric["exhausted"] is True                # 末页 has_more=0 → 确已到底
    # 低于 cap 的深度也要如实透传给前端(前端 scanDepth=depth_cap 决定"超N名外/N+")
    assert r.metric["depth_cap"] == 40


def test_douyin_stops_paging_once_found():
    # 命中即停(成本):目标在第 21 条(第 2 页),has_more 永远为真,抓到第 2 页就停。
    def page(endpoint, params):
        base = params["cursor"]
        comments = [{"text": ("TARGET" if base + i + 1 == 21 else f"o{base+i+1}"),
                     "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]
        return {"data": {"status_code": 0, "has_more": 1, "cursor": base + 20, "comments": comments}}
    client = MagicMock(); client.get.side_effect = page
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(_dtask({"my_comment_text": "TARGET", "top_n": 5}))
    assert r.rank == 21
    assert client.get.call_count == 2


def test_douyin_exhausted_true_when_whole_section_scanned():
    # 整个评论区只有 30 条(第2页 has_more=0),找不到目标 → exhausted=True(翻到底了),
    # 用于区分"翻遍全区仍没有(疑似限流/仅自己可见)"与"只翻了前 N 条没翻够"。
    pages = [
        {"data": {"status_code": 0, "has_more": 1, "cursor": 20,
                  "comments": [{"text": f"o{i}", "user": {"nickname": "u"}, "digg_count": 0} for i in range(20)]}},
        {"data": {"status_code": 0, "has_more": 0, "cursor": 40,
                  "comments": [{"text": f"p{i}", "user": {"nickname": "u"}, "digg_count": 0} for i in range(10)]}},
    ]
    client = MagicMock(); client.get.side_effect = pages
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("x", ""))
    r = a.fetch(_dtask({"my_comment_text": "GHOST", "top_n": 5}))
    assert r.metric["matched"] is False
    assert r.metric["total_fetched"] == 30
    assert r.metric["exhausted"] is True

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

def test_kuaishou_pcursor_stops_at_no_more():
    client = MagicMock()
    client.get.return_value = {"data": {"result": 1, "pcursor": "no_more",
        "rootComments": [{"content": "hi", "author_name": "a", "likedCount": 2}]}}
    a = CommentApiAdapter(KUAISHOU_SPEC, client_factory=lambda: client,
                          id_extractor=lambda url: ("photoid", ""))
    r = a.fetch(MonitorTask(type="kuaishou_comment", name="t", target_url="x",
                            config={"my_comment_text": "hi", "top_n": 5}))
    assert client.get.call_count == 1        # pcursor=no_more → 单页停
    assert r.status == "ok" and r.rank == 1
