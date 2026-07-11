from __future__ import annotations
from csm_core.monitor.geo.providers.rpa import _driver, _flow
from csm_core.monitor.geo.providers.rpa.sites import SITES


class _FakeKeyboard:
    def type(self, *a, **k): pass
    def press(self, *a, **k): pass


class _FakePage:
    def __init__(self, html):
        self._html = html
        self.keyboard = _FakeKeyboard()
        self.gotos = []
    def goto(self, url, *a, **k): self.gotos.append(url)
    def wait_for_timeout(self, *a, **k): pass
    def content(self): return self._html
    def query_selector(self, sel): return None
    def query_selector_all(self, sel): return []
    def evaluate(self, *a, **k): return False
    def click(self, *a, **k): pass


def test_run_one_keyword_blocked_when_not_logged_in():
    page = _FakePage("<html></html>")
    ans = _driver.run_one_keyword(page, SITES["deepseek"], "k",
                                  web_search=True, cancel_token=None, logged_in=False)
    assert ans.status == "blocked"
    assert "登录" in ans.error
    assert page.gotos == []                      # 未登录不 goto,直接 blocked


def test_run_one_keyword_resets_conversation_via_goto(monkeypatch):
    # 每关键词必须 goto 回首页重置会话(致命修复①)。wait_stream_done patch 成 no-op。
    monkeypatch.setattr(_flow, "wait_stream_done", lambda *a, **k: None)
    html = ('<textarea></textarea>'
            '<div class="ds-markdown ds-assistant-message-main-content">推荐小鹏G6 '
            '<a href="https://zhuanlan.zhihu.com/p/9">知乎</a></div>')
    page = _FakePage(html)
    ans = _driver.run_one_keyword(page, SITES["deepseek"], "家用吸尘器",
                                  web_search=True, cancel_token=None, logged_in=True)
    assert ans.status == "ok"
    assert "小鹏G6" in ans.answer_text
    assert ans.citations[0].url == "https://zhuanlan.zhihu.com/p/9"
    assert page.gotos == ["https://chat.deepseek.com/"]   # 确实 goto 重置了一次


def test_run_one_keyword_empty_when_no_answer(monkeypatch):
    monkeypatch.setattr(_flow, "wait_stream_done", lambda *a, **k: None)
    page = _FakePage('<textarea></textarea>'
                     '<div class="ds-markdown ds-assistant-message-main-content"></div>')
    ans = _driver.run_one_keyword(page, SITES["deepseek"], "k",
                                  web_search=True, cancel_token=None, logged_in=True)
    assert ans.status == "empty"
