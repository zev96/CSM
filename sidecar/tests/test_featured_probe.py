"""精选评论轻量探测（csm_core.mining.featured_probe）—— 全程假会话，不触网。

响应样本取自 2026-09 对 x/v2/reply/main 的实测：
  - 开启精选：control.web_selection=true、root_input_text="评论被up主精选后，对所有人可见"、
    cursor.name="精选评论"、replies 为空；
  - 普通视频：web_selection=false、cursor.name="热门评论"。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from csm_core.mining import featured_probe as fp
from csm_core.mining.featured_probe import FeaturedProber, bilibili_bv_to_aid

FEATURED_DATA = {
    "cursor": {"is_begin": True, "is_end": True, "mode": 3, "support_mode": [3], "name": "精选评论"},
    "replies": [],
    "control": {
        "input_disable": False,
        "root_input_text": "评论被up主精选后，对所有人可见",
        "child_input_text": "评论被up主精选后，对所有人可见",
        "show_type": 2,
        "web_selection": True,
    },
}
NORMAL_DATA = {
    "cursor": {"is_begin": True, "is_end": False, "mode": 3, "support_mode": [2, 3], "name": "热门评论"},
    "replies": [{"content": {"message": "hi"}, "member": {"uname": "u"}, "like": 1}],
    "control": {
        "input_disable": False,
        "root_input_text": "与其赞同别人的话语，不如自己畅所欲言。",
        "show_type": 1,
        "web_selection": False,
    },
}

URL = "https://www.bilibili.com/video/BV1rAeH6JE5k"


def _resp(body=None, *, status=200, text="{}"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    if body is None:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = body
    return r


def _ok(data):
    return _resp({"code": 0, "message": "OK", "data": data})


class _NoWait:
    def wait(self):
        return 0.0


def _prober(*responses):
    session = MagicMock()
    session.get.side_effect = list(responses)
    return FeaturedProber(session_factory=lambda: session, pacer=_NoWait()), session


# ── BV → aid ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bvid, aid", [
    ("BV1GJ411x7h7", 80433022),             # 老一代 aid
    ("BV1rAeH6JE5k", 117276078507046),      # 2024 起的大号 aid（> 2^32）
])
def test_bv_to_aid_known_pairs(bvid, aid):
    assert bilibili_bv_to_aid(bvid) == aid


@pytest.mark.parametrize("bad", ["", "BV1", "AV1GJ411x7h7", "BV2GJ411x7h7", "BV1GJ411x7h", "BV1GJ411x7h0", None])
def test_bv_to_aid_rejects_malformed(bad):
    # "BV1GJ411x7h0"：'0' 不在 base58 表里
    assert bilibili_bv_to_aid(bad) is None


# ── check() ─────────────────────────────────────────────────────────────────

def test_check_featured_video_true_and_request_shape():
    prober, session = _prober(_ok(FEATURED_DATA))
    assert prober.check("bilibili", URL) is True
    (args, kwargs), = session.get.call_args_list
    assert args[0] == "https://api.bilibili.com/x/v2/reply/main"
    # oid 是离线换算出的数字 aid；ps=1 —— 只为读 control 块，不翻评论
    assert kwargs["params"] == {"oid": 117276078507046, "type": 1, "mode": 3, "next": 0, "ps": 1}


def test_check_normal_video_false():
    prober, _ = _prober(_ok(NORMAL_DATA))
    assert prober.check("bilibili", URL) is False


def test_check_av_url():
    prober, session = _prober(_ok(NORMAL_DATA))
    assert prober.check("bilibili", "https://www.bilibili.com/video/av80433022") is False
    assert session.get.call_args.kwargs["params"]["oid"] == 80433022


def test_check_unsupported_platform_or_bad_url_sends_nothing():
    prober, session = _prober()
    assert prober.check("douyin", "https://www.douyin.com/video/7438932126029843752") is None
    assert prober.check("bilibili", "https://www.bilibili.com/") is None
    assert prober.check("bilibili", "") is None
    session.get.assert_not_called()


def test_session_is_created_lazily_and_reused_then_closed():
    session = MagicMock()
    session.get.side_effect = [_ok(NORMAL_DATA), _ok(FEATURED_DATA)]
    made = []

    def factory():
        made.append(1)
        return session

    with FeaturedProber(session_factory=factory, pacer=_NoWait()) as prober:
        assert made == []
        prober.check("bilibili", URL)
        prober.check("bilibili", URL)
        assert made == [1]
    session.close.assert_called_once()


def test_transient_risk_control_is_retried_once():
    """B 站匿名请求偶发 code=-352（实测：紧接着重试就过）—— 单次失败不该让精选视频漏网。"""
    prober, session = _prober(
        _resp({"code": -352, "message": "风控校验失败"}),
        _ok(FEATURED_DATA),
    )
    assert prober.check("bilibili", URL) is True
    assert session.get.call_count == 2
    assert prober._failures == 0, "a check rescued by the retry is not a failure"


def test_channel_failures_trip_breaker_and_stop_requests():
    # 每次 check = 首发 + 一次重试；两次都失败才计 1 次失败，连续 3 次熔断。
    prober, session = _prober(
        _resp(status=412, text="<html>risk</html>"), _resp(status=412, text="<html>risk</html>"),
        _resp({"code": -352, "message": "风控校验失败"}), _resp({"code": -412, "message": "请求被拦截"}),
        RuntimeError("timeout"), RuntimeError("timeout"),
    )
    for _ in range(3):
        assert prober.check("bilibili", URL) is None
    assert prober.tripped
    # 熔断后不再发请求
    assert prober.check("bilibili", URL) is None
    assert session.get.call_count == 6


def test_success_resets_failure_streak():
    boom2 = [RuntimeError("boom"), RuntimeError("boom")]   # 一次 check 的首发 + 重试
    prober, _ = _prober(*boom2, *boom2, _ok(NORMAL_DATA), *boom2, *boom2)
    verdicts = [prober.check("bilibili", URL) for _ in range(5)]
    assert verdicts == [None, None, False, None, None]
    assert not prober.tripped


def test_per_video_business_codes_do_not_trip_breaker():
    """12002 评论区已关闭 / -404 视频不存在：单条视频自身的状态，不是探测通道坏了。"""
    prober, session = _prober(*[
        _resp({"code": code, "message": "x"}) for code in (12002, -404, 12002, 12061)
    ])
    assert [prober.check("bilibili", URL) for _ in range(4)] == [None] * 4
    assert not prober.tripped
    assert session.get.call_count == 4, "per-video states are final — no retry either"


def test_non_dict_body_counts_as_failure():
    prober, _ = _prober(_resp([1, 2, 3]), _resp([1, 2, 3]))
    assert prober.check("bilibili", URL) is None
    assert prober._failures == 1


def test_session_factory_failure_is_fail_open():
    def boom():
        raise ImportError("curl_cffi not installed")

    prober = FeaturedProber(session_factory=boom, pacer=_NoWait())
    assert prober.check("bilibili", URL) is None
    assert prober._failures == 1


def test_default_pacer_is_short_and_default_session_is_anonymous(monkeypatch):
    prober = FeaturedProber()
    assert (prober._pacer.delay_min, prober._pacer.delay_max) == (fp._DELAY_MIN_S, fp._DELAY_MAX_S)
    assert prober._pacer.delay_max <= 3.0, "探测间隔应远短于评论监控的 5–15s"

    created = {}

    class FakeSession:
        def __init__(self, **kw):
            created["kw"] = kw
            self.headers = {}

    import curl_cffi.requests as cc

    monkeypatch.setattr(cc, "Session", FakeSession)
    session = fp._default_session()
    assert created["kw"] == {"impersonate": "chrome120"}
    assert "Cookie" not in session.headers
    assert session.headers["Referer"] == "https://www.bilibili.com/"
