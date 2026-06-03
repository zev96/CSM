import contextlib
import csm_core.monitor.geo.providers.rpa._session as sess


def test_rpa_page_wraps_launched_page_with_geo_prefix(monkeypatch):
    seen = {}

    @contextlib.contextmanager
    def fake_launched(platform, *, headless=False):
        seen["platform"] = platform
        seen["headless"] = headless
        yield "PAGE"

    monkeypatch.setattr(sess, "launched_page", fake_launched)
    with sess.rpa_page("deepseek", headless=True) as p:
        assert p == "PAGE"
    assert seen == {"platform": "geo_deepseek", "headless": True}


def test_login_status_unknown_platform_returns_false():
    out = sess.login_status("nope")
    assert out["logged_in"] is False


def test_open_login_unknown_platform_returns_error():
    out = sess.open_login("nope")
    assert out["status"] == "error"


class _Ctx:
    def __init__(self, html):
        self._html = html
        self.closed = False
        self._page = _Pg(html)
    @property
    def pages(self):
        return [self._page]
    def new_page(self):
        return self._page
    def on(self, *a, **k):
        pass
    def close(self):
        self.closed = True


class _Pg:
    def __init__(self, html):
        self._html = html
    def goto(self, *a, **k):
        pass
    def wait_for_timeout(self, *a, **k):
        pass
    def bring_to_front(self):
        pass
    def content(self):
        return self._html


class _PW:
    def __init__(self, html):
        self._html = html
        self.chromium = self
        self.executable_path = "/x/chromium"
        self.stopped = False
    def start(self):
        return self
    def launch_persistent_context(self, **k):
        return _Ctx(self._html)
    def stop(self):
        self.stopped = True


def _patch_pw(monkeypatch, html):
    monkeypatch.setattr(sess, "ensure_browsers_path", lambda: None)
    monkeypatch.setattr(sess, "_profile_dir_for", lambda p: __import__("pathlib").Path("/tmp") / p)
    import types
    fake_mod = types.SimpleNamespace(sync_playwright=lambda: _PW(html))
    monkeypatch.setitem(__import__("sys").modules, "patchright.sync_api", fake_mod)


def test_login_status_logged_in_true(monkeypatch):
    _patch_pw(monkeypatch, '<textarea id="chat-input"></textarea>')
    out = sess.login_status("deepseek")
    assert out["logged_in"] is True


def test_login_status_logged_out_false(monkeypatch):
    _patch_pw(monkeypatch, "<html><body>请登录</body></html>")
    out = sess.login_status("deepseek")
    assert out["logged_in"] is False


def test_open_login_success_when_marker_present(monkeypatch):
    _patch_pw(monkeypatch, '<textarea id="chat-input"></textarea>')
    out = sess.open_login("deepseek", timeout_s=2)
    assert out["status"] == "success"


def test_open_login_cancelled_when_page_detaches(monkeypatch):
    # 用户关窗 → page.content() 抛 → open_login 返回 cancelled
    import sys
    import types

    class _DeadPage:
        def goto(self, *a, **k):
            pass
        def wait_for_timeout(self, *a, **k):
            pass
        def bring_to_front(self):
            pass
        def content(self):
            raise RuntimeError("page closed")

    class _DeadCtx:
        @property
        def pages(self):
            return [_DeadPage()]
        def new_page(self):
            return _DeadPage()
        def on(self, *a, **k):
            pass
        def close(self):
            pass

    class _DeadPW:
        def __init__(self):
            self.chromium = self
            self.executable_path = "/x/chromium"
        def start(self):
            return self
        def launch_persistent_context(self, **k):
            return _DeadCtx()
        def stop(self):
            pass

    monkeypatch.setattr(sess, "ensure_browsers_path", lambda: None)
    monkeypatch.setattr(sess, "_profile_dir_for", lambda p: __import__("pathlib").Path("/tmp") / p)
    monkeypatch.setitem(sys.modules, "patchright.sync_api",
                        types.SimpleNamespace(sync_playwright=lambda: _DeadPW()))
    out = sess.open_login("deepseek", timeout_s=2)
    assert out["status"] == "cancelled"
