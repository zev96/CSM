from csm_core.monitor.geo.providers.rpa import _flow


ANSWER_HTML = """
<html><body>
  <nav><a href="https://chat.deepseek.com/help">帮助</a></nav>
  <div class="answer">
    <p>推荐 小鹏G6，参考下列来源。</p>
    <a href="https://zhuanlan.zhihu.com/p/123">小鹏G6 实测 - 知乎</a>
    <a href="https://www.autohome.com.cn/x">汽车之家评测</a>
    <a href="https://zhuanlan.zhihu.com/p/123">重复链接</a>
    <a href="/relative/path">站内相对链接</a>
    <a href="https://chat.deepseek.com/self">自家域名</a>
  </div>
</body></html>
"""


def test_extract_citations_dedups_filters_and_excludes_hosts():
    cits = _flow.extract_citations(
        ANSWER_HTML, container_sel="div.answer",
        exclude_hosts=("chat.deepseek.com",))
    urls = [c.url for c in cits]
    assert urls == ["https://zhuanlan.zhihu.com/p/123",
                    "https://www.autohome.com.cn/x"]
    assert cits[0].title == "小鹏G6 实测 - 知乎"


def test_extract_citations_container_none_scans_whole_doc():
    cits = _flow.extract_citations(ANSWER_HTML)  # 无 container → 含 nav 的 help 链接
    assert any(c.url.endswith("/help") for c in cits)


def test_extract_answer_text_collapses_whitespace():
    txt = _flow.extract_answer_text(ANSWER_HTML, container_sel="div.answer")
    assert "小鹏G6" in txt
    assert "  " not in txt  # 空白已折叠


def test_extract_answer_text_missing_container_returns_empty():
    assert _flow.extract_answer_text("<html></html>", container_sel="div.nope") == ""


def test_parse_source_items_dedups_and_url_empty():
    # 元宝「源」抽屉条目：抓文本作 title、url 留空、按 title 去重。
    html = """
    <div class="agent-dialogue-references__list">
      <div class="agent-dialogue-references__item">北京商报: 20款扫地机测评</div>
      <div class="agent-dialogue-references__item">北京市市场监督管理局</div>
      <div class="agent-dialogue-references__item">北京商报: 20款扫地机测评</div>
    </div>
    """
    cits = _flow.parse_source_items(
        html, item_sel="div[class*='agent-dialogue-references__item']")
    assert [c.title for c in cits] == ["北京商报: 20款扫地机测评", "北京市市场监督管理局"]
    assert all(c.url == "" for c in cits)


def test_parse_source_items_empty_when_no_match():
    assert _flow.parse_source_items("<div></div>", item_sel="div.nope") == []


def test_is_logged_in_html_true_when_composer_present():
    html = '<html><body><textarea id="chat-input"></textarea></body></html>'
    assert _flow.is_logged_in_html(html, logged_in_sel="textarea#chat-input") is True


def test_is_logged_in_html_false_when_logged_out_marker_present():
    html = '<html><body><textarea></textarea><button class="login-btn">登录</button></body></html>'
    assert _flow.is_logged_in_html(
        html, logged_in_sel="textarea", logged_out_sel="button.login-btn") is False


def test_is_logged_in_html_false_when_composer_absent():
    assert _flow.is_logged_in_html("<html></html>", logged_in_sel="textarea") is False


import threading
import pytest


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page
    def type(self, text, **kwargs):
        self._page.typed.append(text)
    def press(self, key):
        self._page.pressed.append(("<kbd>", key))


class _FakePage:
    """脚本化 page：content() 依次返回 _contents 序列（末值定格），
    query_selector 按 selector→对象表返回。"""
    def __init__(self, contents, selectors=None):
        self._contents = list(contents)
        self._selectors = selectors or {}
        self.filled = None
        self.clicked = []
        self.pressed = []
        self.typed = []
        self.evaluated = []
        self._eval_return = None       # start_new_chat 的 JS 点击返回（True=点到/False=icon 不在）
        self._eval_seq = None          # 设为列表 → evaluate 依次返回（末值定格），用于 answer_text_len
        self.keyboard = _FakeKeyboard(self)

    def content(self):
        return self._contents.pop(0) if len(self._contents) > 1 else self._contents[0]

    def evaluate(self, expression, arg=None):
        self.evaluated.append((expression, arg))
        if self._eval_seq is not None:
            return self._eval_seq.pop(0) if len(self._eval_seq) > 1 else self._eval_seq[0]
        return self._eval_return

    def wait_for_timeout(self, ms):
        self.waited = getattr(self, "waited", [])
        self.waited.append(ms)

    def query_selector(self, sel):
        v = self._selectors.get(sel)
        return v() if callable(v) else v

    def fill(self, sel, text):
        self.filled = (sel, text)

    def click(self, sel, **kwargs):
        self.clicked.append(sel)

    def press(self, sel, key):
        self.pressed.append((sel, key))


class _FakeEl:
    def __init__(self, *, enabled=True, attrs=None):
        self._enabled = enabled
        self._attrs = attrs or {}
    def is_enabled(self):
        return self._enabled
    def get_attribute(self, name):
        return self._attrs.get(name)
    def click(self):
        self._attrs["__clicked"] = True


def test_submit_query_types_and_clicks_send():
    page = _FakePage(["<html></html>"])
    _flow.submit_query(page, composer_sel="textarea", send_sel="button.send", text="k")
    assert page.clicked == ["textarea", "button.send"]   # 聚焦 composer + 点发送
    assert page.typed == ["k"]


def test_submit_query_types_and_enters_when_no_send_sel():
    page = _FakePage(["<html></html>"])
    _flow.submit_query(page, composer_sel="textarea", send_sel=None, text="k")
    assert page.typed == ["k"]
    assert page.pressed == [("<kbd>", "Enter")]


class _FlakyClickPage(_FakePage):
    """指定 selector 的 click 抛异常(模拟发送键选择器漂移),验证 Enter 兜底/下一候选。"""
    def __init__(self, contents, fail_sels=()):
        super().__init__(contents)
        self._fail = set(fail_sels)

    def click(self, sel, **kwargs):
        if sel in self._fail:
            raise RuntimeError(f"click timeout: {sel}")
        self.clicked.append(sel)


def test_submit_query_falls_back_to_enter_when_send_click_fails():
    page = _FlakyClickPage(["<html></html>"], fail_sels={"button.send"})
    _flow.submit_query(page, composer_sel="textarea", send_sel="button.send", text="k")
    assert page.clicked == ["textarea"]              # composer 聚焦成功、发送键失败
    assert page.pressed == [("<kbd>", "Enter")]      # 回落 Enter


def test_submit_query_tries_second_candidate_before_enter():
    page = _FlakyClickPage(["<html></html>"], fail_sels={"button.a"})
    _flow.submit_query(page, composer_sel="textarea",
                       send_sel=("button.a", "button.b"), text="k")
    assert page.clicked == ["textarea", "button.b"]  # 首候选失败→次候选成功
    assert page.pressed == []                         # 无需 Enter


def test_ensure_web_toggle_clicks_when_off():
    el = _FakeEl(attrs={"aria-pressed": "false"})
    page = _FakePage(["<html></html>"], {"#web": el})
    _flow.ensure_web_toggle(page, toggle_sel="#web", want_on=True)
    assert el._attrs.get("__clicked") is True


def test_ensure_web_toggle_noop_when_already_on():
    el = _FakeEl(attrs={"aria-pressed": "true"})
    page = _FakePage(["<html></html>"], {"#web": el})
    _flow.ensure_web_toggle(page, toggle_sel="#web", want_on=True)
    assert el._attrs.get("__clicked") is None


def test_ensure_web_toggle_missing_toggle_is_ignored():
    page = _FakePage(["<html></html>"], {})
    _flow.ensure_web_toggle(page, toggle_sel="#nope", want_on=True)  # 不抛


def test_detect_login_uses_page_content():
    page = _FakePage(['<textarea id="c"></textarea>'])
    assert _flow.detect_login(page, logged_in_sel="textarea#c") is True


def test_wait_login_ready_true_when_composer_appears_late():
    # 加载中（composer 没出现）→ 第三帧 composer 渲染出来 → True（防 2s 误判）
    seq = ["<html></html>", "<html></html>", '<textarea id="c"></textarea>']
    page = _FakePage(seq)
    assert _flow.wait_login_ready(page, logged_in_sel="textarea#c",
                                  timeout_s=5, poll_ms=1) is True


def test_wait_login_ready_false_when_logged_out_marker():
    page = _FakePage(['<textarea></textarea><button class="lo">登录</button>'])
    assert _flow.wait_login_ready(page, logged_in_sel="textarea",
                                  logged_out_sel="button.lo", timeout_s=5, poll_ms=1) is False


def test_wait_login_ready_false_on_timeout_no_composer():
    page = _FakePage(["<html></html>"])
    assert _flow.wait_login_ready(page, logged_in_sel="textarea",
                                  timeout_s=0.05, poll_ms=10) is False


def test_start_new_chat_returns_false_when_icon_absent():
    # icon 不在场（JS 返回 False）→ 跳过，不轮询 content
    page = _FakePage(["<html></html>"])
    page._eval_return = False
    assert _flow.start_new_chat(page, new_chat_sel="span.nc", answer_sel="div.a") is False
    assert page.evaluated and page.evaluated[0][1] == "span.nc"  # 把 selector 传进 JS


def test_start_new_chat_clicked_and_already_clear():
    # 点到（JS 返回 True）+ 视图已清空（回答容器空）→ 立即返回 True
    page = _FakePage(['<div class="a"></div>'])
    page._eval_return = True
    assert _flow.start_new_chat(page, new_chat_sel="span.nc", answer_sel="div.a",
                                timeout_s=5, poll_ms=1) is True


def test_start_new_chat_waits_until_view_cleared():
    # 点完旧答案还在 → 轮询到清空再返回（防新会话未渲染完就 submit 读到旧答案）
    old = '<div class="a">' + "旧" * 100 + "</div>"
    fresh = '<div class="a"></div>'
    page = _FakePage([old, old, fresh, fresh])
    page._eval_return = True
    assert _flow.start_new_chat(page, new_chat_sel="span.nc", answer_sel="div.a",
                                timeout_s=5, poll_ms=1) is True


def test_wait_stream_done_returns_when_done_and_quiet():
    # 前两次 generating 在场→未完成；之后 generating 消失 + content 稳定→完成
    contents = ["<a>", "<ab>", "<abc>", "<abc>", "<abc>"]
    gen = iter([_FakeEl(), _FakeEl(), None, None, None, None, None, None])
    page = _FakePage(contents, {"#gen": lambda: next(gen, None)})
    _flow.wait_stream_done(
        page, done_predicate=lambda: page.query_selector("#gen") is None,
        idle_ms=1, timeout_s=5, poll_ms=1)


def test_wait_stream_done_timeout_raises():
    page = _FakePage(["<a>"], {})
    with pytest.raises(TimeoutError):
        _flow.wait_stream_done(page, done_predicate=lambda: False,
                               idle_ms=1, timeout_s=0.2, poll_ms=10)


def test_wait_stream_done_honors_cancel_token():
    try:
        from csm_sidecar.services.monitor_loop import _CancelledFetch
    except ImportError:
        _CancelledFetch = RuntimeError
    tok = threading.Event(); tok.set()
    page = _FakePage(["<a>"], {})
    with pytest.raises(_CancelledFetch):
        _flow.wait_stream_done(page, done_predicate=lambda: False,
                               idle_ms=1, timeout_s=5, poll_ms=10, cancel_token=tok)


def test_sites_deepseek_present_and_css_selectors_valid():
    from bs4 import BeautifulSoup
    from csm_core.monitor.geo.providers.rpa.sites import SITES, SiteSpec
    spec = SITES["deepseek"]
    assert isinstance(spec, SiteSpec)
    assert spec.url.startswith("https://")
    # 传给 bs4 的选择器必须是合法 CSS（否则 .select 抛 SelectorSyntaxError）
    soup = BeautifulSoup("<html></html>", "html.parser")
    for css in [spec.logged_in_sel, spec.answer_sel, spec.citation_sel]:
        soup.select(css)  # 不抛即合法
    if spec.logged_out_sel:
        soup.select(spec.logged_out_sel)


def test_make_done_predicate_generating_requires_started():
    seq = iter([None, _FakeEl(), _FakeEl(), None])  # 没开始 / 生成中 / 生成中 / 完成
    page = _FakePage(["x"], {"#gen": lambda: next(seq, None)})
    done = _flow.make_done_predicate(page, generating_sel="#gen", answer_sel="div.a")
    assert done() is False  # generating 还没出现 → 不算完成（防提交后误判）
    assert done() is False  # 出现 → started
    assert done() is False  # 还在生成
    assert done() is True   # 曾出现且现已消失 → 完成


def test_answer_text_len_uses_evaluate_and_guards_errors():
    page = _FakePage(["x"]); page._eval_seq = [123]
    assert _flow.answer_text_len(page, "div.a") == 123
    assert page.evaluated and page.evaluated[0][1] == "div.a"   # 把 selector 传进 JS
    boom = _FakePage(["x"])
    def _raise(*a, **k): raise RuntimeError("eval boom")
    boom.evaluate = _raise
    assert _flow.answer_text_len(boom, "div.a") == 0            # 出错→0,不外抛


def test_make_done_predicate_answer_growth_uses_evaluate():
    # 无 generating：内容分支改走 answer_text_len(evaluate) —— 空 → 仍空 → 出文>基线+30 判「已开始」
    page = _FakePage(["x"]); page._eval_seq = [0, 0, 200]
    done = _flow.make_done_predicate(page, generating_sel=None, answer_sel="div.a")
    assert done() is False   # 回答容器空 → 记基线
    assert done() is False   # 仍空 → 还没开始
    assert done() is True    # 回答容器出文 >30 → 已开始
