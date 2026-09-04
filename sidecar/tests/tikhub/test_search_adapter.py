"""TikHubSearchAdapter 行为测试：翻页 / 每页重试 / 402 / 硬顶 80 / 翻页硬闸 / 全重复页停 /
空过滤页不停 / 后页失败降 done / normalize 异常不穿透 / 取消 / 无 key / 日志不含 keyword。"""
import dataclasses
import json
import logging
import threading

import httpx
import pytest

from csm_core.mining.platforms import tikhub_search as S
from csm_core.monitor.tikhub import client as tclient
from csm_core.monitor.tikhub.client import TikHubClient
from csm_core.monitor.tikhub.errors import TikHubError


@pytest.fixture(autouse=True)
def _reset_latch_and_sleep(monkeypatch):
    tclient.reset_balance_latch()
    monkeypatch.setattr(S, "_RETRY_SLEEP_S", 0.0)     # 重试不真睡
    yield
    tclient.reset_balance_latch()


def _dy_page(aweme_ids, *, has_more: int, next_cursor: int):
    """最小抖音 v2 响应：只含 _extract_cards / douyin_next_body 需要的字段。"""
    cards = [{
        "type": 1,
        "data": {"aweme_info": {
            "aweme_id": aid, "desc": f"d{aid}", "author": {"nickname": "n", "uid": 1},
            "statistics": {"digg_count": 1, "play_count": 2}, "video": {"duration": 1000},
            "create_time": 1735635697, "aweme_type": 0,
        }},
    } for aid in aweme_ids]
    return {"code": 200, "data": {
        "business_data": cards,
        "business_config": {"has_more": has_more, "backtrace": "bt",
                            "next_page": {"cursor": next_cursor, "search_id": "sid"}},
    }}


def _adapter(handler, spec=S.DOUYIN_SEARCH_SPEC, key="k"):
    def cf():
        if not key:
            raise TikHubError("未配置 TikHub API Key，请到设置页粘贴")
        return TikHubClient(base_url="https://api.tikhub.dev", api_key=key,
                            _transport=httpx.MockTransport(handler))
    return S.TikHubSearchAdapter(spec, cf)


def _run(adapter, target=50, cancel=None, filters=None, max_attempts=None):
    cards, progress = [], []
    out = adapter.search(
        keyword="k", target_count=target,
        on_card=cards.append, on_progress=progress.append,
        cancel_event=cancel or threading.Event(), filters=filters, max_attempts=max_attempts,
    )
    return out, cards, progress


def _cursor(req) -> int:
    return int(json.loads(req.read())["cursor"])


def test_douyin_two_pages_propagate_cursor_and_search_id():
    bodies = []

    def h(req):
        body = json.loads(req.read())
        bodies.append(body)
        if body["cursor"] == 0:
            return httpx.Response(200, json=_dy_page(["1", "2"], has_more=1, next_cursor=8))
        return httpx.Response(200, json=_dy_page(["3"], has_more=0, next_cursor=0))

    out, cards, _ = _run(_adapter(h), target=10)
    assert out.status == "done" and out.cards_emitted == 3
    assert [c.platform_video_id for c in cards] == ["1", "2", "3"]
    assert [c.rank_in_search for c in cards] == [1, 2, 3]
    assert bodies[0]["cursor"] == 0 and bodies[0]["search_id"] == ""
    assert bodies[1]["cursor"] == 8 and bodies[1]["search_id"] == "sid" and bodies[1]["backtrace"] == "bt"


def test_dedup_within_run():
    h = lambda req: httpx.Response(200, json=_dy_page(["1", "1", "2"], has_more=0, next_cursor=0))
    out, cards, _ = _run(_adapter(h))
    assert out.cards_emitted == 2 and [c.platform_video_id for c in cards] == ["1", "2"]


def test_page_failure_retries_then_succeeds():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"code": 429})
        return httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))

    out, cards, _ = _run(_adapter(h))
    assert out.status == "done" and out.cards_emitted == 1
    assert calls["n"] == 3


def test_first_page_failure_exhausts_retries_then_failed():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(500, json={"code": 500})

    out, cards, progress = _run(_adapter(h))
    assert out.status == "failed" and out.cards_emitted == 0
    assert calls["n"] == S.PAGE_RETRIES
    assert "TikHub" in out.error_message
    assert progress[-1].phase == "failed"


def test_later_page_failure_after_cards_is_done_with_note():
    calls = {"n": 0}

    def h(req):
        if _cursor(req) == 0:
            return httpx.Response(200, json=_dy_page(["1", "2"], has_more=1, next_cursor=8))
        calls["n"] += 1
        return httpx.Response(500, json={"code": 500})

    out, cards, progress = _run(_adapter(h))
    assert out.status == "done" and out.cards_emitted == 2 and len(cards) == 2
    assert calls["n"] == S.PAGE_RETRIES                     # 第 2 页重试耗尽
    assert "第 2 页" in out.error_message
    assert progress[-1].phase == "done" and "第 2 页" in progress[-1].note


def test_402_on_first_page_fails_immediately_and_trips_latch():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(402, json={"code": 402})

    out, _, _ = _run(_adapter(h))
    assert out.status == "failed" and calls["n"] == 1
    assert tclient.balance_exhausted() is True


def test_tripped_latch_does_not_block_a_fresh_search():
    """余额闩全局预检已移除(job 级短路移交 runner)——即使闩在开搜前已经被
    (比如另一个平台的 402)置位，本适配器自己的这次 search() 仍应正常发出请求，
    不再抢先短路整个 job。真正的 402 仍会在请求中途通过 client 再次触发闩。"""
    tclient._trip_balance_latch()
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))

    out, cards, _ = _run(_adapter(h))
    assert out.status == "done" and calls["n"] == 1
    assert out.cards_emitted == 1


def test_hard_cap_80_even_if_more_available():
    def h(req):
        base = _cursor(req)
        ids = [str(base + i) for i in range(20)]
        return httpx.Response(200, json=_dy_page(ids, has_more=1, next_cursor=base + 20))

    out, cards, _ = _run(_adapter(h), target=200)
    assert out.status == "done" and out.cards_emitted == S.HARD_CAP == 80
    assert len(cards) == 80


def test_max_pages_guard_stops_runaway_pagination():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        # 每页 1 张新卡且总说 has_more → 靠 MAX_PAGES 硬闸停
        return httpx.Response(200, json=_dy_page([str(calls["n"])], has_more=1, next_cursor=calls["n"]))

    out, cards, _ = _run(_adapter(h), target=80)
    assert out.status == "done"
    assert calls["n"] == S.MAX_PAGES and len(cards) == S.MAX_PAGES


def test_all_duplicate_page_stops_pagination():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page(["1", "2"], has_more=1, next_cursor=calls["n"] * 8))

    out, cards, _ = _run(_adapter(h), target=80)
    assert out.status == "done" and out.cards_emitted == 2
    assert calls["n"] == 2                                  # 第 2 页全是重复卡 → 停


def test_empty_filtered_page_does_not_stop_when_next_exists():
    def h(req):
        if _cursor(req) == 0:
            return httpx.Response(200, json=_dy_page([], has_more=1, next_cursor=8))   # 整页被过滤为空
        return httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))

    out, cards, _ = _run(_adapter(h))
    assert out.status == "done" and out.cards_emitted == 1


def test_normalize_exception_on_first_page_is_failed_not_raised():
    def boom(raw, f):
        raise RuntimeError("bad shape")

    spec = dataclasses.replace(S.DOUYIN_SEARCH_SPEC, normalize=boom)
    h = lambda req: httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))
    out, cards, progress = _run(_adapter(h, spec=spec))
    assert out.status == "failed" and out.cards_emitted == 0 and "解析" in out.error_message
    assert progress[-1].phase == "failed"


def test_normalize_exception_after_cards_is_done():
    state = {"n": 0}
    real = S.DOUYIN_SEARCH_SPEC.normalize

    def flaky(raw, f):
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("bad shape")
        return real(raw, f)

    spec = dataclasses.replace(S.DOUYIN_SEARCH_SPEC, normalize=flaky)

    def h(req):
        if _cursor(req) == 0:
            return httpx.Response(200, json=_dy_page(["1"], has_more=1, next_cursor=8))
        return httpx.Response(200, json=_dy_page(["2"], has_more=0, next_cursor=0))

    out, cards, _ = _run(_adapter(h, spec=spec))
    assert out.status == "done" and out.cards_emitted == 1 and "第 2 页" in out.error_message


# ── A2：normalize 返回值必须在 try 内被具体化/校验 ──────────────────────────

def test_normalize_returns_none_is_done_with_zero_hits_note():
    """normalize 返回 None(而不是空 list)—— 不能让下游 for 循环 TypeError 穿透
    search()，应等价于 0 张卡的一页正常收尾。"""
    spec = dataclasses.replace(S.DOUYIN_SEARCH_SPEC, normalize=lambda raw, f: None)
    h = lambda req: httpx.Response(200, json=_dy_page([], has_more=0, next_cursor=0))
    out, cards, progress = _run(_adapter(h, spec=spec))
    assert out.status == "done" and out.cards_emitted == 0 and len(cards) == 0
    assert "0 条命中" in out.error_message


def test_normalize_returns_non_videocard_items_are_filtered():
    """normalize 混入非 VideoCard 元素(如裸 object()/字符串)—— 必须被过滤掉，
    不能让 card.platform_video_id 之类的属性访问穿透 search()。"""
    spec = dataclasses.replace(S.DOUYIN_SEARCH_SPEC, normalize=lambda raw, f: [object(), "x"])
    h = lambda req: httpx.Response(200, json=_dy_page([], has_more=0, next_cursor=0))
    out, cards, progress = _run(_adapter(h, spec=spec))
    assert out.status == "done" and out.cards_emitted == 0 and len(cards) == 0
    assert "0 条命中" in out.error_message


def test_normalize_returns_lazy_generator_that_raises_is_failed_not_raised():
    """normalize 返回一个生成器(惰性求值)，真正的异常在第一次 next() 时才抛出 ——
    这类异常必须发生在 _fetch_page 的 try 块内部才能被捕获成 _PageError；如果
    normalize 的返回值没有在 try 内被具体化(list()化)，异常会在 try 块外的
    for 循环里穿透 search()。"""
    def boom_gen(raw, f):
        def gen():
            raise RuntimeError("bad shape")
            yield  # pragma: no cover — 使其成为生成器函数
        return gen()

    spec = dataclasses.replace(S.DOUYIN_SEARCH_SPEC, normalize=boom_gen)
    h = lambda req: httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))
    out, cards, progress = _run(_adapter(h, spec=spec))
    assert out.status == "failed" and out.cards_emitted == 0 and "解析" in out.error_message
    assert progress[-1].phase == "failed"


# ── A4：已达 target 后循环退出，收尾时取消事件已置位不应把 done 降级 ────────

def test_cancel_set_after_reaching_target_stays_done():
    """target=2，一页刚好 2 张卡；on_card 在收到第 2 张卡时才置位取消事件 ——
    此时采集已经达标，循环因 emitted>=target 自然退出，不应因为退出后取消事件
    恰好已置位就把结果降级成 cancelled(那会丢弃已经入库的候选)。"""
    ev = threading.Event()

    def h(req):
        return httpx.Response(200, json=_dy_page(["1", "2"], has_more=0, next_cursor=0))

    cards = []

    def on_card_and_maybe_cancel(card):
        cards.append(card)
        if len(cards) == 2:
            ev.set()

    out = _adapter(h).search(
        keyword="k", target_count=2,
        on_card=on_card_and_maybe_cancel, on_progress=lambda pu: None,
        cancel_event=ev, filters=None,
    )
    assert out.status == "done" and out.cards_emitted == 2


# ── A5：failed 的 reason 必须截断，避免 note 无界增长 ───────────────────────

def test_failed_reason_is_bounded_even_for_huge_exception_message():
    def cf():
        raise RuntimeError("x" * 500)

    adapter = S.TikHubSearchAdapter(S.DOUYIN_SEARCH_SPEC, cf)
    out = adapter.search(
        keyword="k", target_count=10,
        on_card=lambda c: None, on_progress=lambda pu: None,
        cancel_event=threading.Event(), filters=None,
    )
    assert out.status == "failed"
    assert len(out.error_message) < 260


def test_max_attempts_caps_pages():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page([str(calls["n"])], has_more=1, next_cursor=calls["n"]))

    out, cards, _ = _run(_adapter(h), target=80, max_attempts=2)
    assert out.status == "done" and calls["n"] == 2 and len(cards) == 2


def test_cancel_before_first_page():
    ev = threading.Event(); ev.set()
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))

    out, _, _ = _run(_adapter(h), cancel=ev)
    assert out.status == "cancelled" and calls["n"] == 0


def test_missing_key_returns_failed_not_raise():
    out, _, progress = _run(_adapter(lambda req: httpx.Response(200, json={}), key=""))
    assert out.status == "failed" and "未配置" in out.error_message
    assert progress[-1].phase == "failed"


def test_bilibili_spec_uses_get_with_query_params():
    seen = {}

    def h(req):
        seen["method"] = req.method
        seen["q"] = dict(req.url.params)
        return httpx.Response(200, json={"code": 200, "data": {"data": {
            "page": 1, "numPages": 1, "result": [{
                "type": "video", "bvid": "BV1", "title": "t", "author": "a", "mid": 1,
                "pic": "//x/p.jpg", "play": 1, "like": 2, "pubdate": 1785893300, "duration": "1:00",
            }],
        }}})

    out, cards, _ = _run(_adapter(h, spec=S.BILIBILI_SEARCH_SPEC),
                         filters={"bilibili": {"order": "click"}})
    assert seen["method"] == "GET" and seen["q"]["order"] == "click" and seen["q"]["keyword"] == "k"
    assert out.status == "done" and cards[0].platform_video_id == "BV1"


def test_build_factory_returns_three_platform_adapters():
    from unittest.mock import MagicMock
    ad = S.build_tikhub_search_adapters(lambda: MagicMock(), lambda p, c=None: "k")
    assert set(ad) == {"douyin", "bilibili", "kuaishou"}
    assert all(isinstance(a, S.TikHubSearchAdapter) for a in ad.values())
    assert ad["kuaishou"].platform == "kuaishou"


def test_page_log_records_cursor_but_not_keyword(caplog):
    h = lambda req: httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))
    with caplog.at_level(logging.INFO, logger="csm_core.mining.platforms.tikhub_search"):
        _run(_adapter(h))
    page_lines = [r.getMessage() for r in caplog.records if "page 1 [" in r.getMessage()]
    assert page_lines and "cursor=0" in page_lines[0]
    assert all("keyword" not in line for line in page_lines)


def test_malformed_leaf_field_card_is_skipped_not_fatal():
    """aweme_info.author 是字符串 → 归一化层单卡容错跳过这一张卡，页面本身仍算成功
    （0 条命中，走 B5 的诊断 note）——不再因为一张脏卡把整页/整个平台打成 failed。
    normalize 整体异常仍然按页级错误处理，见
    test_normalize_exception_on_first_page_is_failed_not_raised。"""
    page = _dy_page(["1"], has_more=0, next_cursor=0)
    page["data"]["business_data"][0]["data"]["aweme_info"]["author"] = "x"
    out, cards, progress = _run(_adapter(lambda req: httpx.Response(200, json=page)))
    assert out.status == "done" and out.cards_emitted == 0
    assert "0 条命中" in out.error_message


# ── B1 (I1)：search() 永不异常穿透 ─────────────────────────────────────────

def test_first_request_construction_error_is_failed_not_raised():
    """first_request 内部抛出常规 try/except 接不住的异常（比如 AttributeError）——
    首页请求构造阶段就出错，必须兜成 failed，绝不能让异常穿透 search()，且 reason
    只报类型名（S1：不 repr(e)）。

    注：B 站 time_begin 传成 int 曾经是触发这条路径的真实场景（date_to_epoch 内部
    .strip() 抛 AttributeError，原 except (ValueError, TypeError) 接不住）——该
    根因已在 _common.date_to_epoch 里修复（AttributeError 现在被兜成 None，见
    test_search_normalize.py::test_date_to_epoch_non_str_input_returns_none），
    这里改用显式的 first_request 故障注入，继续覆盖 search() 自身的安全网（I1）。"""
    def boom_first_request(keyword, f):
        raise AttributeError("boom")

    spec = dataclasses.replace(S.BILIBILI_SEARCH_SPEC, first_request=boom_first_request)
    out, cards, progress = _run(
        _adapter(lambda req: httpx.Response(200, json={}), spec=spec),
    )
    assert out.status == "failed"
    assert "请求构造失败" in out.error_message and "AttributeError" in out.error_message
    assert progress[-1].phase == "failed"


def test_first_page_non_tikhub_exception_is_failed_not_raised():
    """handler 抛非 TikHubError 的普通异常（模拟 httpx.InvalidURL / UnicodeEncodeError /
    transport 插件 bug 等）—— 首页必须兜成 failed，绝不能穿透 search()。

    注：C4 把 client.get()/post() 的异常捕获从「只接 httpx.HTTPError」扩到「接住
    请求发送阶段的一切异常」，所以这类裸异常现在在 client 层就已经被转换成
    TikHubError(reason="请求构造失败：RuntimeError", retryable=False)，不会再以
    未包装的原始异常形态触达 tikhub_search 自己的兜底（那个兜底仍然存在，见
    test_normalize_returns_lazy_generator_that_raises_is_failed_not_raised 覆盖
    的是 normalize 阶段的等价场景）——但外部可观察行为不变：依旧是 failed、
    不穿透、reason 只报类型名（S1：不 repr(e)）。"""
    def h(req):
        raise RuntimeError("boom")

    out, cards, progress = _run(_adapter(h))
    assert out.status == "failed" and out.cards_emitted == 0
    assert "RuntimeError" in out.error_message
    assert "boom" not in out.error_message
    assert progress[-1].phase == "failed"


def test_later_page_non_tikhub_exception_after_cards_is_done():
    def h(req):
        if _cursor(req) == 0:
            return httpx.Response(200, json=_dy_page(["1", "2"], has_more=1, next_cursor=8))
        raise RuntimeError("boom")

    out, cards, _ = _run(_adapter(h))
    assert out.status == "done" and out.cards_emitted == 2 and len(cards) == 2
    assert "第 2 页" in out.error_message


def test_filters_non_dict_falls_back_to_empty_plat_filters():
    """filters 顶层不是 dict（例如误传成 list）—— 不能让 .get() 抛异常穿透，应兜成
    空 plat_filters 正常跑完。"""
    h = lambda req: httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))
    out, cards, _ = _run(_adapter(h), filters=["x"])
    assert out.status == "done" and out.cards_emitted == 1


# ── A1：HTTP 200 + body code=429 是"已出货"的限流提示，不重试（区别于真 HTTP 429）──

def test_body_429_is_not_retried_served_response():
    """HTTP 200 + body code=429 是服务端已经处理并回了限流提示（已出货，可能已
    计费）—— from_body 判据现在排在 429 特判之前，不能重试，否则重复计费。真正
    没出货的 HTTP 429（见 test_page_failure_retries_then_succeeds）才应该退避重试。"""
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json={"code": 429})

    out, cards, _ = _run(_adapter(h))
    assert calls["n"] == 1
    assert out.status == "failed"


# ── B2 (I4)：重试只重试「服务端没出货」的失败；429 指数退避 ──────────────────

def test_401_auth_failure_not_retried():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(401, json={"code": 401})

    out, _, _ = _run(_adapter(h))
    assert calls["n"] == 1
    assert out.status == "failed"


def test_http_200_body_error_not_retried():
    """HTTP 200 + body code != 200：服务端已经出货（可能已计费），重试只会重复计费，
    绝不能重试。"""
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json={"code": 400, "message": "bad request"})

    out, _, _ = _run(_adapter(h))
    assert calls["n"] == 1
    assert out.status == "failed"


def test_network_error_retried_to_exhaustion():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        raise httpx.ConnectError("x")

    out, _, _ = _run(_adapter(h))
    assert calls["n"] == S.PAGE_RETRIES
    assert out.status == "failed"


def test_retry_delay_backs_off_only_for_429(monkeypatch):
    monkeypatch.setattr(S, "_RETRY_SLEEP_S", 1.0)
    assert S._retry_delay(429, 1) == 1.0
    assert S._retry_delay(429, 2) == 2.0
    assert S._retry_delay(429, 3) == 4.0
    assert S._retry_delay(500, 2) == 1.0
    assert S._retry_delay(None, 2) == 1.0


# ── B3 (M1)：取消在重试等待中即时生效 ──────────────────────────────────────

def test_cancel_set_during_retry_wait_returns_cancelled_not_failed():
    """handler 在第一次调用时就置位取消事件并返回 500（可重试）—— 重试前的
    cancel_event.wait(...) 因为事件已置位立即返回 True，不应再发第二次请求，
    结果必须是 cancelled 而不是 failed。"""
    ev = threading.Event()
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        ev.set()
        return httpx.Response(500, json={"code": 500})

    out, _, _ = _run(_adapter(h), cancel=ev)
    assert out.status == "cancelled"
    assert calls["n"] == 1


# ── B4 (I5)：一页内不超发 ───────────────────────────────────────────────────

def test_does_not_overshoot_target_mid_page():
    h = lambda req: httpx.Response(200, json=_dy_page([str(i) for i in range(20)], has_more=1, next_cursor=8))
    out, cards, _ = _run(_adapter(h), target=3)
    assert out.cards_emitted == 3 and len(cards) == 3


# ── B5：0 命中诊断 note ─────────────────────────────────────────────────────

def test_zero_hits_after_scanning_pages_gets_diagnostic_note():
    def h(req):
        if _cursor(req) == 0:
            return httpx.Response(200, json=_dy_page([], has_more=1, next_cursor=8))
        return httpx.Response(200, json=_dy_page([], has_more=0, next_cursor=0))

    out, cards, progress = _run(_adapter(h))
    assert out.status == "done" and out.cards_emitted == 0
    assert "0 条命中" in out.error_message and "已翻 2 页" in out.error_message
    assert "0 条命中" in progress[-1].note


# ── S1：key 含非 ASCII 字符触发编码异常时绝不泄漏 ──────────────────────────

def test_non_ascii_key_never_leaks_via_repr(caplog):
    """key 含零宽空格(U+200B)→ httpx 编码 "Bearer <key>" 头时抛 UnicodeEncodeError；
    repr(UnicodeEncodeError) 会带出整个待编码字符串（完整的 "Bearer <key>"）——绝不能
    出现在 error_message 或任何日志（含 traceback）里。这类失败发生在请求发出之前，
    且被 client 标记为不可重试（见 client._parse 上方的三类映射），只应尝试 1 次，
    不该傻等 3 次重试间隔。"""
    secret_key = "sk-live-ABC\u200bTAIL"
    attempts = {"n": 0}
    real_post = TikHubClient.post

    def counting_post(self, path, body):
        attempts["n"] += 1
        return real_post(self, path, body)

    import unittest.mock as mock
    with mock.patch.object(TikHubClient, "post", counting_post):
        with caplog.at_level(logging.DEBUG):
            out, cards, _ = _run(_adapter(
                lambda req: httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0)),
                key=secret_key,
            ))

    assert out.status == "failed"
    for blob in (out.error_message, caplog.text):
        assert "ABC" not in blob
        assert "TAIL" not in blob
        assert "Bearer" not in blob
    assert attempts["n"] == 1          # 预发送失败不可重试：只应尝试 1 次


def test_read_timeout_after_send_is_not_retried():
    """C4：ReadTimeout 说明请求已经真的发出去了(不同于连不上)，响应没收全不代表
    服务端没处理——可能已计费，绝不能当成"没出货"去重试，只应尝试 1 次。"""
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        raise httpx.ReadTimeout("x")

    out, _, _ = _run(_adapter(h))
    assert calls["n"] == 1
    assert out.status == "failed"
    assert "已发出" in out.error_message


# ── C3：连续多页无有效结果止损 ──────────────────────────────────────────────

def test_consecutive_empty_pages_stop_after_three():
    """服务端一直回声空页但 has_more=1 —— 没有止损会一直翻到 MAX_PAGES(12) 才停，
    每页仍是一次计费请求；连续 _MAX_EMPTY_PAGES 页 0 张有效卡就该提前止损。"""
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page([], has_more=1, next_cursor=calls["n"]))

    out, cards, _ = _run(_adapter(h), target=80)
    assert out.status == "done" and out.cards_emitted == 0
    assert calls["n"] == S._MAX_EMPTY_PAGES == 3
    assert "连续 3 页" in out.error_message


# ── D3：提前停止时 note 写明具体原因 ─────────────────────────────────────────

def test_all_duplicates_note_mentions_duplicate_stop_reason():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page(["1", "2"], has_more=1, next_cursor=calls["n"] * 8))

    out, cards, _ = _run(_adapter(h), target=80)
    assert out.status == "done" and out.cards_emitted == 2
    assert "重复" in out.error_message


def test_no_next_page_before_target_note_mentions_no_next_page():
    h = lambda req: httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))
    out, cards, _ = _run(_adapter(h), target=50)
    assert out.status == "done" and out.cards_emitted == 1
    assert "无下一页" in out.error_message


def test_max_pages_note_mentions_page_cap():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page([str(calls["n"])], has_more=1, next_cursor=calls["n"]))

    out, cards, _ = _run(_adapter(h), target=80)
    assert out.status == "done" and calls["n"] == S.MAX_PAGES
    assert "翻页上限" in out.error_message


def test_target_reached_produces_empty_note():
    h = lambda req: httpx.Response(200, json=_dy_page(["1", "2", "3"], has_more=1, next_cursor=8))
    out, cards, _ = _run(_adapter(h), target=3)
    assert out.status == "done" and out.cards_emitted == 3
    assert out.error_message == ""
