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


def test_is_logged_in_html_true_when_composer_present():
    html = '<html><body><textarea id="chat-input"></textarea></body></html>'
    assert _flow.is_logged_in_html(html, logged_in_sel="textarea#chat-input") is True


def test_is_logged_in_html_false_when_logged_out_marker_present():
    html = '<html><body><textarea></textarea><button class="login-btn">登录</button></body></html>'
    assert _flow.is_logged_in_html(
        html, logged_in_sel="textarea", logged_out_sel="button.login-btn") is False


def test_is_logged_in_html_false_when_composer_absent():
    assert _flow.is_logged_in_html("<html></html>", logged_in_sel="textarea") is False
