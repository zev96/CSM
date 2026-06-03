import contextlib
import threading
import pytest
import csm_core.monitor.geo.providers.rpa.deepseek as ds


class _FakeKeyboard:
    def type(self, *a, **k):
        pass
    def press(self, *a, **k):
        pass


class _FakePage:
    def __init__(self, html, *, raise_on_wait=None):
        self._html = html
        self._raise_on_wait = raise_on_wait
        self.keyboard = _FakeKeyboard()
    def goto(self, *a, **k):
        pass
    def wait_for_timeout(self, *a, **k):
        pass
    def content(self):
        return self._html
    def query_selector(self, sel):
        return None
    def query_selector_all(self, sel):
        return []                       # 无 toggle/源 元素 → enable_*/scrape_* 优雅跳过
    def evaluate(self, *a, **k):
        return False                    # start_new_chat 的 JS 点击：icon 不在 → 跳过
    def fill(self, *a, **k):
        pass
    def click(self, *a, **k):
        pass
    def press(self, *a, **k):
        pass


def _patch_session(monkeypatch, page, *, wait=None):
    @contextlib.contextmanager
    def fake_rpa_page(platform, *, headless=False):
        yield page
    monkeypatch.setattr(ds, "rpa_page", fake_rpa_page)
    if wait is not None:
        monkeypatch.setattr(ds._flow, "wait_stream_done", wait)


def test_deepseek_blocked_when_not_logged_in(monkeypatch):
    _patch_session(monkeypatch, _FakePage("<html><body>请登录</body></html>"))
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "blocked"
    assert "登录" in ans.error


def test_deepseek_ok_when_logged_in_and_answer_present(monkeypatch):
    # 答案在 ds-assistant-message-main-content（深度思考推理在 ds-think-content 里，已排除）
    html = ('<textarea id="chat-input"></textarea>'
            '<div class="ds-markdown ds-assistant-message-main-content">推荐小鹏G6 '
            '<a href="https://zhuanlan.zhihu.com/p/9">知乎</a></div>')
    _patch_session(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "ok"
    assert "小鹏G6" in ans.answer_text
    assert ans.citations[0].url == "https://zhuanlan.zhihu.com/p/9"


def test_deepseek_empty_when_logged_in_but_no_answer(monkeypatch):
    html = ('<textarea id="chat-input"></textarea>'
            '<div class="ds-markdown ds-assistant-message-main-content"></div>')
    _patch_session(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "empty"


def test_deepseek_timeout_becomes_error(monkeypatch):
    html = '<textarea id="chat-input"></textarea>'
    def _boom(*a, **k):
        raise TimeoutError("stream too slow")
    _patch_session(monkeypatch, _FakePage(html), wait=_boom)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "error"
    assert "slow" in ans.error or "timeout" in ans.error.lower()


def test_deepseek_query_never_raises(monkeypatch):
    # rpa_page 本身抛 → provider 兜成 error，不冒泡
    @contextlib.contextmanager
    def boom_page(platform, *, headless=False):
        raise RuntimeError("browser launch failed")
        yield  # pragma: no cover
    monkeypatch.setattr(ds, "rpa_page", boom_page)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "error"


def test_deepseek_reraises_cancellation(monkeypatch):
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        pytest.skip("sidecar 不可用")
    html = '<textarea id="chat-input"></textarea>'
    def _cancel(*a, **k):
        raise _CancelledFetch("cancelled by user")
    _patch_session(monkeypatch, _FakePage(html), wait=_cancel)
    with pytest.raises(_CancelledFetch):
        ds.DeepSeekProvider().query("k", web_search=True)


import csm_core.monitor.geo.providers.rpa.kimi as km


def _patch_km(monkeypatch, page, *, wait=None):
    @contextlib.contextmanager
    def fake(platform, *, headless=False):
        yield page
    monkeypatch.setattr(km, "rpa_page", fake)
    if wait is not None:
        monkeypatch.setattr(km._flow, "wait_stream_done", wait)


def test_kimi_blocked_when_not_logged_in(monkeypatch):
    # 命中 logged_out_sel（user-name=登录）→ wait_login_ready 快速判未登录
    _patch_km(monkeypatch, _FakePage('<span class="user-name">登录</span>'))
    ans = km.KimiProvider().query("k", web_search=True)
    assert ans.status == "blocked"


def test_kimi_ok_when_answer_present(monkeypatch):
    html = ('<div contenteditable="true"></div>'
            '<div class="markdown">小鹏G6 不错 '
            '<a href="https://www.autohome.com.cn/a">汽车之家</a></div>')
    _patch_km(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = km.KimiProvider().query("k", web_search=True)
    assert ans.status == "ok" and ans.citations[0].url.startswith("https://www.autohome")


import csm_core.monitor.geo.providers.rpa.yuanbao as yb


def _patch_yb(monkeypatch, page, *, wait=None):
    @contextlib.contextmanager
    def fake(platform, *, headless=False):
        yield page
    monkeypatch.setattr(yb, "rpa_page", fake)
    if wait is not None:
        monkeypatch.setattr(yb._flow, "wait_stream_done", wait)


def test_yuanbao_blocked_when_not_logged_in(monkeypatch):
    # 命中 logged_out_sel（composer 占位「请登录」）→ wait_login_ready 快速判未登录
    _patch_yb(monkeypatch, _FakePage('<div data-placeholder="请登录后输入内容"></div>'))
    ans = yb.YuanbaoProvider().query("k", web_search=True)
    assert ans.status == "blocked"


def test_yuanbao_ok_when_answer_present(monkeypatch):
    # 答案在 hyc-common-markdown（深度思考推理带 -cot 后缀，已排除）。元宝信源走
    # 「源」抽屉（scrape_source_panel，fake 里返回 []），故此处只验 ok+答案，不验 citations。
    html = ('<div contenteditable="true"></div>'
            '<div class="hyc-common-markdown hyc-common-markdown-style">小鹏G6 不错</div>')
    _patch_yb(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = yb.YuanbaoProvider().query("k", web_search=True)
    assert ans.status == "ok"
    assert "小鹏G6" in ans.answer_text
