import contextlib
import threading
import pytest
import csm_core.monitor.geo.providers.rpa.deepseek as ds


class _FakePage:
    def __init__(self, html, *, raise_on_wait=None):
        self._html = html
        self._raise_on_wait = raise_on_wait
    def goto(self, *a, **k):
        pass
    def wait_for_timeout(self, *a, **k):
        pass
    def content(self):
        return self._html
    def query_selector(self, sel):
        return None
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
    html = ('<textarea id="chat-input"></textarea>'
            '<div class="ds-markdown">推荐小鹏G6 '
            '<a href="https://zhuanlan.zhihu.com/p/9">知乎</a></div>')
    _patch_session(monkeypatch, _FakePage(html), wait=lambda *a, **k: None)
    ans = ds.DeepSeekProvider().query("k", web_search=True)
    assert ans.status == "ok"
    assert "小鹏G6" in ans.answer_text
    assert ans.citations[0].url == "https://zhuanlan.zhihu.com/p/9"


def test_deepseek_empty_when_logged_in_but_no_answer(monkeypatch):
    html = '<textarea id="chat-input"></textarea><div class="ds-markdown"></div>'
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
