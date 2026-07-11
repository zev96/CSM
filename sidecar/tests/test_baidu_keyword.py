"""百度 keyword adapter 单元测试。

不真开 Chromium、不真发 HTTP。所有外部交互都 mock。
SERP 解析逻辑用真实保存的 fixture 验证。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from csm_core.monitor.platforms import baidu_keyword


FIXTURES = Path(__file__).parent / "fixtures" / "baidu"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── SERP 解析 ─────────────────────────────────────────────────────────────
def test_parse_serp_default_only_no_news():
    html = _load("serp_default_only.html")
    parsed = baidu_keyword.parse_serp(html)
    assert parsed["news_present"] is False
    assert parsed["news_links"] == []
    # 9 = 8 条常规 + 1 条 cosc-title-slot 卡（2026-07 起 cosc 结构排除移除）
    assert len(parsed["default_links"]) == 9
    # 每个 link 是 dict，包含 title + href
    for link in parsed["default_links"]:
        assert "title" in link
        assert "href" in link
        assert link["href"].startswith("http")


def test_parse_serp_with_news_extracts_both_blocks():
    html = _load("serp_with_news.html")
    parsed = baidu_keyword.parse_serp(html)
    assert parsed["news_present"] is True
    assert len(parsed["news_links"]) == 4
    # 8 = 7 条常规 + 1 条 cosc-title-slot 卡（2026-07 起 cosc 结构排除移除）
    assert len(parsed["default_links"]) == 8
    # 两个 list 严格分开，不重复
    default_hrefs = {l["href"] for l in parsed["default_links"]}
    news_hrefs = {l["href"] for l in parsed["news_links"]}
    assert default_hrefs.isdisjoint(news_hrefs)


def test_parse_serp_empty_html_returns_empty():
    parsed = baidu_keyword.parse_serp("")
    assert parsed["default_links"] == []
    assert parsed["news_links"] == []
    assert parsed["news_present"] is False


def test_parse_serp_2026_dom_result_token_removed():
    """2026-07 百度改版：organic 卡 class 不再含 'result' token（用户实测）。

    锁五个行为：① token 级匹配（顺序无关）仍抓到全部 organic；
    ② rel_base_realtime / b2b_factory_wise_san（登录桶）与 b2b_prod /
    recommend_list（匿名桶）等新杂卡被 tpl 黑名单排除；③ 带
    cosc-title-slot 通用标题槽的 organic 卡必须计入（该结构排除已移除）；
    ④ 主选择器命中时不走兜底；⑤ "部分 token" 子串诱饵卡
    （c-container-promo 等，fixture id=11）必须被拒 —— 谁把选择器回退成
    子串 contains 匹配，这里立刻红。
    """
    html = _load("serp_2026_no_result_token.html")
    parsed = baidu_keyword.parse_serp(html)
    hrefs = [l["href"] for l in parsed["default_links"]]
    assert hrefs == [
        "https://www.zhihu.com/question/2026001",
        "https://baijiahao.baidu.com/s?id=2026002",
        "https://www.sohu.com/a/2026004",
        "https://www.163.com/dy/article/2026003.html",
    ]
    # 主选择器直接命中，不应走兜底
    assert parsed["selector_fallback"] is False
    assert parsed["news_present"] is False


def test_parse_serp_relaxed_fallback_when_era_tokens_gone():
    """xpath-log / new-pmd 这类时代标记 token 全消失时，走 content_left
    兜底选择器：仍按 tpl 黑名单排除杂卡，并置 selector_fallback=True 供观测。"""
    html = """
    <html><body><div id="content_left">
      <div class="c-container" tpl="se_com_default">
        <h3><a href="https://example.com/a1">A1</a></h3>
      </div>
      <div class="c-container" tpl="sp_purc_pc">
        <h3><a href="https://ad.example.com/x">[Ad] X</a></h3>
      </div>
      <div class="c-container" tpl="se_com_default">
        <h3><a href="https://example.com/a2">A2</a></h3>
      </div>
    </div></body></html>
    """
    parsed = baidu_keyword.parse_serp(html)
    assert [l["href"] for l in parsed["default_links"]] == [
        "https://example.com/a1",
        "https://example.com/a2",
    ]
    assert parsed["selector_fallback"] is True


def test_parse_serp_zero_match_logs_diagnostics(caplog):
    """主 + 兜底全 0 命中 ≈ 百度又改版或风控漏检 —— 必须留 WARNING 证据，
    不允许静默返回空 list（否则 status=ok + 假"无排名"没法诊断）。"""
    html = "<html><body><div id='content_left'><p>某种全新结构，没有任何 c-cont 卡片</p></div></body></html>"
    with caplog.at_level("WARNING"):
        parsed = baidu_keyword.parse_serp(html)
    assert parsed["default_links"] == []
    assert parsed["selector_fallback"] is False
    assert any("0 命中" in r.getMessage() for r in caplog.records)


def test_parse_serp_partial_token_drift_warns(caplog):
    """部分 organic 卡丢时代 token（如 xpath-log）时主选择器返回非空子集，
    兜底开关（主 0 才切）看不见这种静默漏抓 —— 常开对照哨兵必须告警。
    选择行为保持不变：仍只返回主选择器命中的条目、不切兜底。"""
    html = """
    <html><body><div id="content_left">
      <div class="c-container xpath-log new-pmd" tpl="se_com_default">
        <h3><a href="https://example.com/full-tokens">A</a></h3>
      </div>
      <div class="c-container new-pmd" tpl="se_com_default">
        <h3><a href="https://example.com/lost-xpath-log">B</a></h3>
      </div>
    </div></body></html>
    """
    with caplog.at_level("WARNING"):
        parsed = baidu_keyword.parse_serp(html)
    assert [l["href"] for l in parsed["default_links"]] == [
        "https://example.com/full-tokens",
    ]
    assert parsed["selector_fallback"] is False
    assert any("兜底选择器比主选择器多" in r.getMessage() for r in caplog.records)


def test_parse_serp_news_container_present_but_zero_rows_warns(caplog):
    """cos-space 资讯容器存在但一行都没解出 = 内层结构漂移信号，必须告警
    （页面根本没有资讯区是常态，不告警 —— news_present=False 本身无法
    区分这两种情况）。"""
    html = """
    <html><body><div id="content_left">
      <div class="c-container xpath-log new-pmd" tpl="se_com_default">
        <h3><a href="https://example.com/a">A</a></h3>
      </div>
      <div class="cos-space">
        <div class="cos-header">最新资讯</div>
        <div class="cos-line-v2">全新内层结构，没有 cos-row</div>
      </div>
    </div></body></html>
    """
    with caplog.at_level("WARNING"):
        parsed = baidu_keyword.parse_serp(html)
    assert parsed["news_links"] == []
    assert parsed["news_present"] is False
    assert any("cos-space" in r.getMessage() for r in caplog.records)


# ── 品牌词匹配 ───────────────────────────────────────────────────────────
def test_match_brand_case_insensitive_hit():
    matched = baidu_keyword.match_brand(
        "I love claude code today",
        ["Claude", "Anthropic"],
    )
    assert matched == "Claude"


def test_match_brand_returns_first_in_brand_order():
    """命中多个时，按 brands 列表里的顺序取第一个。"""
    matched = baidu_keyword.match_brand(
        "anthropic 出了一个叫 claude 的产品",
        ["Claude", "Anthropic"],  # Claude 在前
    )
    assert matched == "Claude"


def test_match_brand_no_match_returns_none():
    assert baidu_keyword.match_brand("text without brand", ["Claude"]) is None


def test_match_brand_empty_inputs():
    assert baidu_keyword.match_brand("", ["Claude"]) is None
    assert baidu_keyword.match_brand("text", []) is None
    assert baidu_keyword.match_brand("", []) is None


def test_match_brand_word_boundary_avoids_substring_false_positive():
    """纯 ASCII 字母数字品牌要求词边界：Nova 不该命中 innovation、MOVA 不该
    命中 removal（尤其 raw-body fallback 会喂全站 nav/JS 文本，一个这种
    子串误命中就把整站文章都判成命中）。"""
    assert baidu_keyword.match_brand("this is pure innovation", ["Nova"]) is None
    assert baidu_keyword.match_brand("hair removal tips", ["MOVA"]) is None


def test_match_brand_word_boundary_still_hits_real_mention():
    assert baidu_keyword.match_brand("I bought a Nova phone", ["Nova"]) == "Nova"
    assert baidu_keyword.match_brand("访问 nova.com 了解", ["Nova"]) == "Nova"


def test_match_brand_fullwidth_normalized():
    """全角品牌名 vs 半角配置 —— NFKC 归一后应命中。"""
    assert baidu_keyword.match_brand("这款 ＮＯＶＡ 很好", ["NOVA"]) == "NOVA"


def test_match_brand_cjk_substring_still_works():
    """中文品牌无词边界概念，仍走子串匹配。"""
    assert baidu_keyword.match_brand("我用的是小米手机", ["小米"]) == "小米"


def test_all_keywords_failed_true_when_every_kw_errored():
    assert baidu_keyword._all_keywords_failed([
        {"keyword": "a", "fetch_error": "serp navigate raised"},
        {"keyword": "b", "fetch_error": "page.content raised"},
    ]) is True


def test_all_keywords_failed_false_when_some_ok():
    assert baidu_keyword._all_keywords_failed([
        {"keyword": "a", "fetch_error": "serp navigate raised"},
        {"keyword": "b", "fetch_error": None},
    ]) is False


def test_all_keywords_failed_false_on_empty():
    assert baidu_keyword._all_keywords_failed([]) is False


def test_extract_raw_body_text_strips_script_style():
    """text_content() 默认会把 <script>/<style> 里的 JS/CSS 文本一起拼进来，
    污染 match_brand（品牌名出现在全站 JS 常量里 → 假命中）。必须先剔除。"""
    html = (
        "<html><body>"
        "<p>正文里根本没提那个词</p>"
        '<script>var cfg = {"brand": "Nova"};</script>'
        '<style>.x{content:"Nova"}</style>'
        "</body></html>"
    )
    text = baidu_keyword._extract_raw_body_text(html)
    assert "正文里根本没提那个词" in text
    assert "Nova" not in text, "script/style 里的品牌名不该混进正文"
    assert "var cfg" not in text


def test_fetch_article_http_sends_baidu_referer(monkeypatch):
    """文章抓取要带 Referer=baidu + Sec-Fetch-Site=cross-site，模拟从 SERP
    点进文章的真实流量形状（百家号等风控最严的站看这个；裸访问 =
    Sec-Fetch-Site:none 无 Referer 是明显机器人特征）。"""
    captured: dict = {}
    long_html = "<html><body><article>" + ("正文内容 " * 60) + "</article></body></html>"

    def fake_get(url, **kw):
        captured.update(kw)
        return _FakeResp(text=long_html)

    monkeypatch.setattr(baidu_keyword, "_cc_get", fake_get)
    baidu_keyword.fetch_article_http("https://post.smzdm.com/p/1")
    hdrs = captured.get("headers") or {}
    assert hdrs.get("Referer") == "https://www.baidu.com/"
    assert hdrs.get("Sec-Fetch-Site") == "cross-site"


def test_fetch_article_http_long_article_mentioning_risk_word_not_flagged(monkeypatch):
    """长文章正文里出现「网络异常/系统繁忙」等词是正常内容，不该被 text 层
    误判成百度风控（那会丢正文、退化到 title 兜底）。"""
    long_body = "本文详细讲解如何排查和处理网络异常问题。" * 40
    html = f"<html><body><article>{long_body}</article></body></html>"
    monkeypatch.setattr(baidu_keyword, "_cc_get", lambda url, **kw: _FakeResp(text=html))
    res = baidu_keyword.fetch_article_http("https://example.com/a")
    assert not (res.get("fetch_error") or "").startswith("百度风控"), "长文章不该判风控"
    assert "网络异常" in (res.get("content") or "")


def test_fetch_article_http_short_captcha_page_flagged(monkeypatch):
    """短的验证码/安全验证插页仍要被 text 层判成风控。"""
    html = "<html><body>安全验证 请完成验证</body></html>"
    monkeypatch.setattr(baidu_keyword, "_cc_get", lambda url, **kw: _FakeResp(text=html))
    res = baidu_keyword.fetch_article_http("https://example.com/a")
    assert (res.get("fetch_error") or "").startswith("百度风控")


# ── 百度跳转解析 ─────────────────────────────────────────────────────────
def test_resolve_baidu_link_already_real_url():
    """非百度跳转 URL 原样返回。"""
    real = "https://zhuanlan.zhihu.com/p/123456"
    assert baidu_keyword.resolve_baidu_link(real) == real


def test_resolve_baidu_link_follows_302(monkeypatch):
    """baidu.com/link?url=... 跟随 302 到真实站点。"""
    fake_real = "https://www.example.com/article"

    class FakeResp:
        url = fake_real
        status_code = 200

    def fake_get(url, **kwargs):
        # 验证调用方传了 allow_redirects=True
        assert kwargs.get("allow_redirects") is True
        return FakeResp()

    import csm_core.monitor.platforms.baidu_keyword as bk
    monkeypatch.setattr(bk, "_cc_get", fake_get)

    resolved = baidu_keyword.resolve_baidu_link(
        "https://www.baidu.com/link?url=encoded_blob_xxx"
    )
    assert resolved == fake_real


def test_resolve_baidu_link_returns_original_on_error(monkeypatch):
    """解失败 → 退回原始 URL，让上游决定怎么处理。"""
    def fake_get(url, **kwargs):
        raise RuntimeError("network down")

    import csm_core.monitor.platforms.baidu_keyword as bk
    monkeypatch.setattr(bk, "_cc_get", fake_get)

    original = "https://www.baidu.com/link?url=blob"
    assert baidu_keyword.resolve_baidu_link(original) == original


# ── HTTP-first 抓正文 ────────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, *, text: str, status_code: int = 200,
                 headers: dict | None = None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}


def test_fetch_article_http_success(monkeypatch):
    """正常 HTML，readability 提到正文 ≥ 200 字 → source=http, 拿到 preview。"""
    long_content = (
        "<html><body><article>"
        + ("我用 Claude Code 写了一个 Tauri 应用。" * 20)
        + "</article></body></html>"
    )

    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text=long_content),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/post")
    assert result["source"] == "http"
    assert result["fetch_error"] is None
    assert "Claude Code" in result["content"]
    assert len(result["content"]) >= 200


def test_fetch_article_http_status_too_high_triggers_fallback(monkeypatch):
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text="", status_code=403),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/forbidden")
    assert result["source"] == "http"
    assert result["needs_browser_fallback"] is True
    assert "403" in (result["fetch_error"] or "")


def test_fetch_article_http_non_html_triggers_fallback(monkeypatch):
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(
            text="{}",
            headers={"content-type": "application/json"},
        ),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/api")
    assert result["needs_browser_fallback"] is True
    assert "content-type" in (result["fetch_error"] or "").lower()


def test_fetch_article_http_too_short_triggers_fallback(monkeypatch):
    """极短壳页（<500 字符 HTML、正文提不出）→ 判定为 JS challenge 壳，
    交给 caller 用 SERP title 兜底，而不是浏览器 fallback。

    v0.5.6+ 演进（覆盖旧断言）：原策略「readability 正文<200 字 →
    needs_browser_fallback=True」对这种连 raw body 都为空的极短壳页，改成标
    ``is_js_challenge=True`` + ``needs_browser_fallback=False``（浏览器兜底会
    触发风控、代价远大于 article-level fail，且标题党概率低于反爬概率）。
    只有 raw HTML ≥500 但正文仍<200 的「大而空」页才继续要 browser fallback。
    """
    short = "<html><body><div>请打开 APP 查看</div></body></html>"
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text=short),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/spa")
    assert result["is_js_challenge"] is True
    assert result["needs_browser_fallback"] is False
    assert result["source"] == "http_js_challenge_no_body"


def test_fetch_article_http_network_exception_triggers_fallback(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("dns nxdomain")

    monkeypatch.setattr(baidu_keyword, "_cc_get", boom)
    result = baidu_keyword.fetch_article_http("https://offline.example/")
    assert result["needs_browser_fallback"] is True
    assert "nxdomain" in (result["fetch_error"] or "").lower()


# ── 完整 fetch 编排 ──────────────────────────────────────────────────────
from csm_core.monitor.base import MonitorTask


class FakeSession:
    """假装 IncognitoSession，只暴露 page。支持多关键词顺序 goto。"""

    class FakeContext:
        """Mock context with cookies() method that returns BDUSS for logged-in state."""
        def cookies(self, url=None):
            # Return a list with BDUSS to simulate logged-in state
            return [{"name": "BDUSS", "value": "mock_bduss_token"}]

    def __init__(self, *, serp_html: str, page_contents: dict[str, str],
                 captcha_url: str | None = None):
        self._serp_html = serp_html
        self._page_contents = page_contents
        self._captcha_url = captcha_url
        self._current_url = ""
        # adapter 通过 .page.goto / .page.content 读取
        self.page = self  # type: ignore[assignment]
        self.context = self.FakeContext()
        self.browser = None
        self.pw = None

    # adapter 当 page 调用的方法
    def goto(self, url, **kw):
        if self._captcha_url and "baidu.com/s?" in url:
            self._current_url = self._captcha_url
        else:
            self._current_url = url

    @property
    def url(self):
        return self._current_url

    def content(self):
        if "baidu.com/s?" in self._current_url:
            return self._serp_html
        return self._page_contents.get(self._current_url, "")


@pytest.fixture
def patch_session(monkeypatch, settings_path):
    """工厂 fixture：调用方传入 fake session，adapter 走 mock 路径。

    依赖 ``settings_path`` 把 config 钉到一份干净的临时 settings.json
    （use_native_chrome=False），否则 fetch() 里的 ``config_service.load()``
    会读到开发机真实的 settings.json —— 真机若开了 native Chrome 模式，
    fetch 会带 ``use_native_chrome=...`` 等 kwargs 调用本 fixture 的 fake
    session（只收 headless），直接 TypeError，跟被测逻辑无关。钉死 config
    让本地与 CI（无 settings.json，取模型默认）行为一致。
    """
    holder: dict = {"session": None}

    from contextlib import contextmanager

    @contextmanager
    def fake_ctx(*, headless: bool):
        holder["last_headless"] = headless
        yield holder["session"]

    monkeypatch.setattr(
        baidu_keyword, "baidu_browser_session", fake_ctx
    )
    # Also mock the pacer so wait() is instant for subsequent keywords
    from csm_core.monitor import rate_limit as _rl

    class _NoWaitPacer:
        def wait(self):
            pass
        def configure(self, **kw):
            pass

    monkeypatch.setattr(_rl, "get_pacer", lambda name: _NoWaitPacer())
    return holder


def test_fetch_happy_path_default_only(monkeypatch, patch_session):
    """两个关键词，没有最新资讯，第 1 条结果是自家、其余竞品。"""
    serp = _load("serp_default_only.html")
    # 用真实 SERP 抓出来的 hrefs 给每条配一段正文
    parsed = baidu_keyword.parse_serp(serp)
    default_links = parsed["default_links"]
    page_contents = {}
    for i, link in enumerate(default_links):
        url = link["href"]
        page_contents[url] = (
            "<html><body><article>"
            + (f"这是关于 Claude 的文章 {i}。" if i == 0
               else f"这是别的竞品的文章 {i}。 ")
            * 30
            + "</article></body></html>"
        )

    patch_session["session"] = FakeSession(
        serp_html=serp, page_contents=page_contents,
    )
    # resolve_baidu_link → 原样返回（mock）
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    # 走 HTTP-first 直接命中（不绕浏览器）
    def fake_cc_get(url, **kw):
        return _FakeResp(text=page_contents.get(url, ""))
    monkeypatch.setattr(baidu_keyword, "_cc_get", fake_cc_get)

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test1",
        config={"search_keywords": ["test1", "test2"], "target_brand": "Claude"},
    )

    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "ok"
    # metric.keywords has 2 entries (one per keyword)
    assert len(result.metric["keywords"]) == 2
    # Each keyword entry has correct shape
    for kw_entry in result.metric["keywords"]:
        assert "keyword" in kw_entry
        assert "default_results" in kw_entry
        assert "news_results" in kw_entry
        assert "default_matched_count" in kw_entry
        assert "default_first_rank" in kw_entry
        assert "news_first_rank" in kw_entry
        assert "news_present" in kw_entry
    # First keyword: first result matches Claude
    kw0 = result.metric["keywords"][0]
    assert kw0["default_results"][0]["matches_brand"] is True
    assert kw0["default_results"][0]["matched_brand"] == "Claude"
    assert kw0["default_first_rank"] == 1
    # Aggregations
    assert result.metric["total_keywords"] == 2
    assert result.metric["matched_keywords"] >= 1


def test_fetch_matches_brand_alias(monkeypatch, patch_session):
    """品牌别名命中：正文只含别名「希喂」而无主品牌「CEWEY」→ 仍判自家。

    回归 commit 86e9018 引入的 NameError：``aliases`` 在 ``fetch()`` 里定义
    却在 ``_fetch_once`` 里使用（跨方法没传参），任何真正走到 SERP 解析的
    抓取都会抛 ``NameError("name 'aliases' is not defined")``，被 runner
    包成 ``adapter exception``。``patch_session`` 已注入干净 config
    （use_native_chrome=False），让 fetch 走 fake browser session 真正进到
    ``_check_block`` 的 ``[brand, *aliases]``，从而覆盖这条路径。
    """
    serp = _load("serp_default_only.html")
    parsed = baidu_keyword.parse_serp(serp)
    default_links = parsed["default_links"]
    assert default_links, "fixture 至少应有一条默认结果"
    # 第 1 条正文只提别名「希喂」，不含主品牌「CEWEY」；其余是竞品。
    page_contents = {}
    for i, link in enumerate(default_links):
        url = link["href"]
        page_contents[url] = (
            "<html><body><article>"
            + (f"这篇评测只提到了希喂这个牌子的猫粮 {i}。" if i == 0
               else f"这是别的竞品的文章 {i}。 ")
            * 30
            + "</article></body></html>"
        )

    patch_session["session"] = FakeSession(serp_html=serp, page_contents=page_contents)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)

    def fake_cc_get(url, **kw):
        return _FakeResp(text=page_contents.get(url, ""))
    monkeypatch.setattr(baidu_keyword, "_cc_get", fake_cc_get)

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=猫粮",
        config={
            "search_keywords": ["猫粮"],
            "target_brand": "CEWEY",
            "brand_aliases": ["希喂"],
        },
    )

    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "ok"
    kw0 = result.metric["keywords"][0]
    first = kw0["default_results"][0]
    # 第 1 条只含别名「希喂」→ 命中自家，matched_brand 回别名原文。
    assert first["matches_brand"] is True
    assert first["matched_brand"] == "希喂"
    assert kw0["default_first_rank"] == 1
    # metric 把 brand_aliases 透出去给前端 L2 展示。
    assert result.metric["brand_aliases"] == ["希喂"]
    assert result.metric["best_default_first_rank"] == 1
    assert result.rank == 1
    # captcha_hit field removed in Task 3 refactor — auto-promotion dead code deleted
    assert "captcha_hit" not in result.metric
    # news_present is now per-keyword in metric["keywords"][i]["news_present"]
    assert "news_present" in result.metric["keywords"][0]


def test_fetch_captcha_raises_RiskControlException(monkeypatch, patch_session):
    """SERP 落地到验证码 URL → detect_risk(page) URL 层命中 →
    RiskControlException 抛出（progress=0，即第一个 keyword）。"""
    from csm_core.monitor.drivers.risk_detector import RiskControlException

    serp = _load("serp_default_only.html")
    patch_session["session"] = FakeSession(
        serp_html=serp,
        page_contents={},
        captcha_url="https://wappass.baidu.com/static/captcha/tuxing.html?x=y",
    )
    # _try_human_solve 立即返回 False，走原 raise 路径（避免 300s 超时）
    monkeypatch.setattr(baidu_keyword, "_try_human_solve", lambda **kw: False)

    task = MonitorTask(
        id=2,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keywords": ["test"], "target_brand": "Claude"},
    )
    with pytest.raises(RiskControlException) as exc_info:
        baidu_keyword.ADAPTER.fetch(task)
    assert exc_info.value.progress == 0
    assert exc_info.value.signal.layer == "url"


def test_fetch_breaker_open_returns_failed_with_reason(monkeypatch):
    """熔断打开时跳过所有 IO 直接返回 *failed*（不是 risk_control）。

    回归 bug：熔断早退原来回 status='risk_control' + 英文 'circuit breaker open'，
    被 monitor_loop 当成正常完成发「监测任务完成」假通知，前端又因无 metric 显示
    「未跑 + keyword #0 断点」，把真实失败藏起来。现在回 'failed' + 中文可读原因，
    让前端显示「失败」并 toast 出原因。
    """
    from csm_core.monitor.rate_limit import get_breaker
    breaker = get_breaker("baidu_keyword")
    # 保存原始值
    orig_threshold = breaker.failure_threshold
    orig_cooldown = breaker.cool_off_seconds
    try:
        # 强制打开
        breaker.failure_threshold = 1
        breaker.cool_off_seconds = 999.0
        breaker.record_failure()
        assert breaker.allow() is False

        task = MonitorTask(
            id=3,
            type="baidu_keyword",
            name="t",
            target_url="https://www.baidu.com/s?wd=test",
            config={"search_keywords": ["test"], "target_brand": "x"},
        )
        result = baidu_keyword.ADAPTER.fetch(task)
        # 关键回归断言：不再是 risk_control（那会伪装成断点 + 触发假「完成」）
        assert result.status == "failed"
        assert "circuit breaker" not in (result.error_message or "").lower()
        # 中文可读原因 + 可操作指引
        assert "熔断" in result.error_message
        assert "重新导入" in result.error_message
    finally:
        breaker.failure_threshold = orig_threshold
        breaker.cool_off_seconds = orig_cooldown
        breaker.record_success()


def test_fetch_validation_empty_keywords_fails(monkeypatch):
    """空 search_keywords list → status=failed，error_message 含 'keywords'。"""
    task = MonitorTask(
        id=4,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keywords": [], "target_brand": "Claude"},
    )
    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "failed"
    assert "keywords" in (result.error_message or "").lower()


# ── exclude_domains 过滤 ───────────────────────────────────────────────────
def test_is_host_excluded_exact_and_subdomain():
    """host 后缀匹配：jd.com 同时命中 jd.com / www.jd.com / mall.jd.com。"""
    ex = {"jd.com", "1688.com"}
    assert baidu_keyword.BaiduKeywordAdapter._is_host_excluded("jd.com", ex)
    assert baidu_keyword.BaiduKeywordAdapter._is_host_excluded("www.jd.com", ex)
    assert baidu_keyword.BaiduKeywordAdapter._is_host_excluded("mall.jd.com", ex)
    assert baidu_keyword.BaiduKeywordAdapter._is_host_excluded("DETAIL.1688.COM", ex)  # case-insensitive
    # 类似前缀但非子域名 → 不命中（jd.com.cn 不是 jd.com 的后缀）
    assert not baidu_keyword.BaiduKeywordAdapter._is_host_excluded("notjd.com", ex)
    assert not baidu_keyword.BaiduKeywordAdapter._is_host_excluded("zhihu.com", ex)
    # 空 set / 空 host → False
    assert not baidu_keyword.BaiduKeywordAdapter._is_host_excluded("jd.com", set())
    assert not baidu_keyword.BaiduKeywordAdapter._is_host_excluded("", ex)


def test_build_exclude_set_merges_global_and_task():
    """task.config.exclude_domains 跟 apply_settings 设的全局合并；
    use_default_excludes=False 时只用 task list。"""
    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(
        default_excluded_domains=["jd.com", "Taobao.com"],
    )
    task_merge = MonitorTask(
        id=1, type="baidu_keyword", name="t", target_url="x",
        config={"exclude_domains": ["cewey.com", " "], "use_default_excludes": True},
    )
    s = adapter._build_exclude_set(task_merge)
    assert s == {"jd.com", "taobao.com", "cewey.com"}

    task_opt_out = MonitorTask(
        id=2, type="baidu_keyword", name="t", target_url="x",
        config={"exclude_domains": ["cewey.com"], "use_default_excludes": False},
    )
    s2 = adapter._build_exclude_set(task_opt_out)
    assert s2 == {"cewey.com"}

    task_empty = MonitorTask(
        id=3, type="baidu_keyword", name="t", target_url="x",
        config={},  # opts-in by default
    )
    s3 = adapter._build_exclude_set(task_empty)
    assert s3 == {"jd.com", "taobao.com"}


# ── Task 3: 风控检测集成 ──────────────────────────────────────────────────────
class TestRiskDetectionIntegration:
    """Task 3: baidu adapter 命中风控时应抛 RiskControlException(progress=i)。

    设计：detect_risk(page, response) 在 SERP 抓取循环里每 keyword 调用一次。
    任一层命中 → raise RiskControlException(signal, progress=current_idx)。
    runner（Task 4）负责捕获 + 写断点 + 暂停任务。
    """

    def test_risk_signal_triggers_RiskControlException_with_progress(
        self, monkeypatch, patch_session
    ):
        """模拟在第 3 个 keyword（0-index=2）命中风控，期望 RiskControlException(progress=2)。

        mock 路径：baidu_keyword.detect_risk —— 因为 baidu_keyword.py 用
        `from ..drivers.risk_detector import detect_risk` 直接绑定到模块命名空间。
        """
        from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException

        call_count = {"n": 0}

        def fake_detect_risk(page, response=None):
            # 只在 SERP 阶段计数（page.url 落在 baidu.com/s 上）。
            # fetch_article_browser 也会调 detect_risk，这里跳过文章页调用
            # 避免污染 SERP 计数 —— 文章页风控由
            # test_fetch_article_browser_risk_control_raises 单独验证。
            url = getattr(page, "url", "") or ""
            if "baidu.com/s?" not in url:
                return None
            call_count["n"] += 1
            if call_count["n"] >= 3:
                # 第 3 次及以后：DOM 层命中
                return RiskSignal(layer="dom", detail="DOM matched '#captcha-mask'")
            return None

        # 注入 fake detect_risk 到 baidu_keyword 模块命名空间
        monkeypatch.setattr(baidu_keyword, "detect_risk", fake_detect_risk)
        # _try_human_solve 立即返回 False，走原 raise 路径（避免 300s 超时）
        monkeypatch.setattr(baidu_keyword, "_try_human_solve", lambda **kw: False)

        # 用最简 SERP HTML（空解析结果即可，不关心品牌匹配）
        serp = _load("serp_default_only.html")
        # 5 个关键词；第 3 个（index=2）触发风控
        patch_session["session"] = FakeSession(
            serp_html=serp,
            page_contents={},
        )
        # resolve_baidu_link / _cc_get 不会被调到（风控在 SERP 阶段抛出）
        monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)

        task = MonitorTask(
            id=99,
            type="baidu_keyword",
            name="risk-test",
            target_url="https://www.baidu.com/s?wd=kw1",
            config={
                "search_keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
                "target_brand": "Claude",
            },
        )

        with pytest.raises(RiskControlException) as exc_info:
            baidu_keyword.ADAPTER.fetch(task)

        assert exc_info.value.progress == 2, (
            f"expected progress=2 (0-indexed 3rd keyword), got {exc_info.value.progress}"
        )
        assert exc_info.value.signal.layer == "dom"
        assert call_count["n"] == 3, (
            f"detect_risk should have been called 3 times (one per keyword until hit), got {call_count['n']}"
        )

    def test_risk_exception_carries_scraped_partial_keywords(
        self, monkeypatch, patch_session
    ):
        """断点续跑重建：风控在第 3 个 keyword（idx=2）命中时，前两个已抓完的
        keyword（kw1/kw2）必须随 RiskControlException.partial_keywords 带出去，
        否则 runner 存断点时头段数据灭失、resume 拼不回完整快照。"""
        from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException

        call_count = {"n": 0}

        def fake_detect_risk(page, response=None):
            url = getattr(page, "url", "") or ""
            if "baidu.com/s?" not in url:
                return None
            call_count["n"] += 1
            if call_count["n"] >= 3:
                return RiskSignal(layer="dom", detail="DOM matched '#captcha-mask'")
            return None

        monkeypatch.setattr(baidu_keyword, "detect_risk", fake_detect_risk)
        monkeypatch.setattr(baidu_keyword, "_try_human_solve", lambda **kw: False)

        serp = _load("serp_default_only.html")
        patch_session["session"] = FakeSession(serp_html=serp, page_contents={})
        monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)

        task = MonitorTask(
            id=99,
            type="baidu_keyword",
            name="risk-partial-test",
            target_url="https://www.baidu.com/s?wd=kw1",
            config={
                "search_keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
                "target_brand": "Claude",
            },
        )

        with pytest.raises(RiskControlException) as exc_info:
            baidu_keyword.ADAPTER.fetch(task)

        partial = exc_info.value.partial_keywords
        assert [kw.get("keyword") for kw in partial] == ["kw1", "kw2"], (
            f"expected the 2 completed keywords carried as partial, got {partial!r}"
        )


def test_human_solve_uses_configured_captcha_timeout(monkeypatch, patch_session):
    """T7：apply_settings 的 captcha_visible_timeout_s 必须传给 _try_human_solve
    的 timeout_s —— 否则该设置项恒等于死默认（存了不用），用户调不动解验证码窗口。"""
    from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException

    captured: dict = {}

    def fake_solve(**kw):
        captured.update(kw)
        return False  # 不解 → 走 raise 退出

    monkeypatch.setattr(baidu_keyword, "_try_human_solve", fake_solve)

    def fake_detect_risk(page, response=None):
        url = getattr(page, "url", "") or ""
        if "baidu.com/s?" not in url:
            return None
        return RiskSignal(layer="dom", detail="captcha")

    monkeypatch.setattr(baidu_keyword, "detect_risk", fake_detect_risk)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)

    serp = _load("serp_default_only.html")
    patch_session["session"] = FakeSession(serp_html=serp, page_contents={})

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter._captcha_timeout_s = 137
    task = MonitorTask(
        id=7, type="baidu_keyword", name="captcha-timeout-test",
        target_url="https://www.baidu.com/s?wd=kw1",
        config={"search_keywords": ["kw1"], "target_brand": "Claude"},
    )
    with pytest.raises(RiskControlException):
        adapter.fetch(task)
    assert captured.get("timeout_s") == 137, (
        f"配置的 captcha 超时未传给 _try_human_solve，captured={captured.get('timeout_s')!r}"
    )


def test_apply_settings_default_captcha_timeout_preserves_300(monkeypatch):
    """默认值必须是 300s（保持接线前的 effective 窗口），否则接线反而缩短窗口。"""
    adapter = baidu_keyword.BaiduKeywordAdapter()
    assert adapter._captcha_timeout_s == 300  # __init__ 默认
    adapter.apply_settings()  # 全默认调用
    assert adapter._captcha_timeout_s == 300  # apply_settings 默认


# ── Article-level pacing（防百家号验证码） ──────────────────────────────────
#
# 这一层节流是为了防 baidu 风控：原来 _check_block 对 SERP 解析出的
# N 条链接做裸 for 循环，秒级连发 N 条 baidu.com/link?url= 跳转 + N 次
# article HTTP 请求，百家号（baidu 自家子域反爬最严）很容易因此触发验
# 证码 → fetch_article_http 拿回验证码 HTML → content_preview 污染 +
# matches_brand 判错。修法：
#   - "baidu_keyword:article"   pacer 控普通 host
#   - "baidu_keyword:baijiahao" pacer 控 baidu 自家子域（更宽窗口）
#   - 被 exclude_set 命中的 host 跳过、不调 pacer（不计 rank 也不空耗）

def _make_pacer_tracker():
    """生成一个 get_pacer 替代实现 + calls 列表。
    返回 (fake_get_pacer, calls)。每次 wait 把对应 pacer name 追加到 calls。"""
    calls: list[str] = []

    class _Tracker:
        def __init__(self, name: str) -> None:
            self.name = name

        def wait(self) -> None:
            calls.append(self.name)

        def configure(self, **kw) -> None:  # configure 会在 apply_settings 里被调
            pass

    def _fake_get_pacer(name: str):
        return _Tracker(name)

    return _fake_get_pacer, calls


def _setup_check_block_mocks(monkeypatch):
    """让 _check_block 内部走纯 HTTP 路径、resolve_baidu_link 不发请求。"""
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    # 长 HTML → readability 提到 ≥200 字 → fetch_article_http 成功（不走 fallback）
    long_html = (
        "<html><body><article>"
        + ("这是一篇关于产品评测的文章。" * 30)
        + "</article></body></html>"
    )
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text=long_html),
    )


def test_check_block_calls_article_pacer_per_link(monkeypatch):
    """正常 host 走 article pacer；每条 link 调一次 wait。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    _setup_check_block_mocks(monkeypatch)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "a", "href": "https://example.com/a"},
        {"title": "b", "href": "https://zhihu.com/p/1"},
        {"title": "c", "href": "https://sohu.com/n/2"},
    ]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
    )
    assert len(out) == 3
    assert calls == [
        "baidu_keyword:article",
        "baidu_keyword:article",
        "baidu_keyword:article",
    ]


def test_check_block_ranks_unresolved_redirect_instead_of_dropping(monkeypatch):
    """resolve 失败（跟不动 302，返回原 baidu.com/link?… URL）时，这条结果
    绝不能被当成"百度垂类"静默丢弃 —— 必须占一个 rank 位、带 fetch_error，
    并用 SERP title 尽力判命中。否则 resolve session 被软封时，用户自己的
    软文会从整张表里凭空消失、后面所有位次前移。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, _pacer_calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    # resolve = identity → baidu.com/link 保持未解析（模拟解析失败）
    _setup_check_block_mocks(monkeypatch)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "深度测评 Claude 真香", "href": "https://www.baidu.com/link?url=ABCDEF"},
        {"title": "百科词条", "href": "https://baike.baidu.com/item/x"},  # 真垂类 → 跳过
    ]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
    )
    # 未解析行作为 rank 1 保留；真垂类仍被跳过。
    assert len(out) == 1
    row = out[0]
    assert row["rank"] == 1
    assert "baidu.com/link?" in row["url"]
    assert row["source"] == "unresolved"
    assert row["fetch_error"], "未解析行必须带 fetch_error"
    assert row["matched_brand"] == "Claude", "应用 SERP title 兜底命中"
    assert row["matches_brand"] is True


def test_check_block_skips_browser_fallback_for_baidu_risk(monkeypatch):
    """fetch_article_http 明确标 needs_browser_fallback=False 的百度风控页
    （verify.baidu.com / safetycheck），绝不能因为 content 为空就被长度条款
    强行升级到隔离 tab —— 那会在真登录 context 里反复打开 verify.baidu.com
    并 180s 空等。应尊重 False，直接走 title 兜底。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, _pacer_calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    monkeypatch.setattr(
        baidu_keyword, "fetch_article_http",
        lambda url, **kw: {
            "content": "",
            "source": "http",
            "fetch_error": "百度风控：layer=url verify.baidu.com",
            "needs_browser_fallback": False,
        },
    )
    called: list[int] = []
    monkeypatch.setattr(
        baidu_keyword, "fetch_article_browser_isolated",
        lambda *a, **kw: (called.append(1), {"content": "x" * 900})[1],
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    fake_page = type("P", (), {"context": object()})()
    links = [{"title": "评测 Claude 真香", "href": "https://baijiahao.baidu.com/s?id=1"}]
    out = adapter._check_block(page=fake_page, links=links, brands=["Claude"], block="default")

    assert called == [], "百度风控页不该进浏览器兜底"
    assert len(out) == 1
    assert out[0]["rank"] == 1
    assert out[0]["matched_brand"] == "Claude", "应用 SERP title 兜底命中"


def test_check_block_short_circuits_repeated_captcha_host(monkeypatch):
    """同一 host 多条结果：第一条软着陆验证码超时（is_blocked）后，后续同
    host 的结果不再进浏览器兜底空等 180s，直接跳过。否则一页 3 条 smzdm =
    3×180s。所有结果仍占 rank 位。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, _pacer_calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    monkeypatch.setattr(
        baidu_keyword, "fetch_article_http",
        lambda url, **kw: {
            "content": "",
            "source": "http",
            "fetch_error": "short",
            "needs_browser_fallback": True,
        },
    )
    calls: list[str] = []

    def fake_isolated(ctx, href, **kw):
        calls.append(href)
        return {
            "content": "",
            "is_blocked": True,
            "fetch_error": "验证码解题超时（180s）",
            "source": "browser_isolated",
        }

    monkeypatch.setattr(baidu_keyword, "fetch_article_browser_isolated", fake_isolated)
    adapter = baidu_keyword.BaiduKeywordAdapter()
    fake_page = type("P", (), {"context": object()})()
    links = [
        {"title": "1", "href": "https://post.smzdm.com/p/1"},
        {"title": "2", "href": "https://post.smzdm.com/p/2"},
        {"title": "3", "href": "https://post.smzdm.com/p/3"},
    ]
    out = adapter._check_block(page=fake_page, links=links, brands=["X"], block="default")

    assert len(calls) == 1, "同 host 只应软着陆一次，后续短路"
    assert len(out) == 3, "所有结果仍占 rank 位"


def test_check_block_memoizes_duplicate_urls(monkeypatch):
    """同一 resolved URL 在多条结果 / 多关键词里重复出现时，只抓一次正文，
    其余复用（93 个品牌关键词头部结果高度重叠 → 省 30-50% 文章抓取）。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, _calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    fetch_calls: list[str] = []

    def fake_fetch(url, **kw):
        fetch_calls.append(url)
        return {
            "content": "长正文内容 " * 30,
            "source": "http",
            "fetch_error": None,
            "needs_browser_fallback": False,
        }

    monkeypatch.setattr(baidu_keyword, "fetch_article_http", fake_fetch)
    adapter = baidu_keyword.BaiduKeywordAdapter()
    memo: dict = {}
    links = [
        {"title": "a", "href": "https://ex.com/same"},
        {"title": "b", "href": "https://ex.com/same"},   # 同 URL → 复用
        {"title": "c", "href": "https://ex.com/other"},
    ]
    out = adapter._check_block(
        page=None, links=links, brands=["X"], block="default", article_memo=memo,
    )
    assert len(out) == 3, "所有结果仍占 rank 位"
    assert fetch_calls == ["https://ex.com/same", "https://ex.com/other"], "重复 URL 只抓一次"


def test_check_block_uses_baijiahao_pacer_for_baidu_subdomains(monkeypatch):
    """baijiahao.baidu.com / mbd.baidu.com / mp.baidu.com 都走 baijiahao pacer。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    _setup_check_block_mocks(monkeypatch)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "bjh", "href": "https://baijiahao.baidu.com/s?id=123"},
        {"title": "mbd", "href": "https://mbd.baidu.com/newspage/x"},
        {"title": "mp",  "href": "https://mp.baidu.com/foo"},
    ]
    adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
    )
    assert calls == [
        "baidu_keyword:baijiahao",
        "baidu_keyword:baijiahao",
        "baidu_keyword:baijiahao",
    ]


def test_check_block_picks_pacer_per_link_host(monkeypatch):
    """混合 host 时按 host 逐条切 pacer：百家号用 baijiahao，其它用 article。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    _setup_check_block_mocks(monkeypatch)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "1", "href": "https://example.com/a"},
        {"title": "2", "href": "https://baijiahao.baidu.com/s?id=1"},
        {"title": "3", "href": "https://zhihu.com/p/1"},
        {"title": "4", "href": "https://mbd.baidu.com/newspage/2"},
    ]
    adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
    )
    assert calls == [
        "baidu_keyword:article",
        "baidu_keyword:baijiahao",
        "baidu_keyword:article",
        "baidu_keyword:baijiahao",
    ]


def test_parse_serp_extracts_show_host_from_showurl():
    """T4 来源预过滤：parse_serp 从 c-showurl 抽出可见来源 host，供 _check_block
    在 resolve 之前预过滤排除域名。显示名（无域名）→ show_host=None（fail-open）。"""
    html = """
    <div id="content_left">
      <div class="result c-container xpath-log new-pmd">
        <h3><a href="http://www.baidu.com/link?url=JD">京东自营</a></h3>
        <div class="c-showurl c-color-gray">mall.jd.com</div>
      </div>
      <div class="result c-container xpath-log new-pmd">
        <h3><a href="http://www.baidu.com/link?url=ZH">知乎测评</a></h3>
        <span class="c-showurl">www.zhihu.com&nbsp;2天前</span>
      </div>
      <div class="result c-container xpath-log new-pmd">
        <h3><a href="http://www.baidu.com/link?url=NAME">某来源</a></h3>
        <span class="c-showurl">什么值得买</span>
      </div>
    </div>
    """
    links = baidu_keyword.parse_serp(html)["default_links"]
    hosts = {l["href"]: l.get("show_host") for l in links}
    assert hosts["http://www.baidu.com/link?url=JD"] == "mall.jd.com"
    assert hosts["http://www.baidu.com/link?url=ZH"] == "www.zhihu.com"
    # 纯显示名（无域名）→ 解析不到，fail-open 为 None
    assert hosts["http://www.baidu.com/link?url=NAME"] is None


def test_parse_serp_show_host_fail_open_on_multi_item_container():
    """防误杀（结构排除=灾难）：一个 c-container 里有多条结果标题（资讯簇 /
    聚合卡）时，showurl 无法可靠归属到具体某一条 → show_host 必须 fail-open 为
    None，绝不能让簇内某一条的来源域名污染整簇、把整簇一起 resolve 前预过滤掉。"""
    # 模拟资讯簇：一个 c-container 内 4 条 cos-item，其中一条来源是排除域名。
    html = """
    <div id="content_left">
      <div class="result c-container xpath-log new-pmd" tpl="news-realtime">
        <div class="cos-space">
          <div class="cos-row">
            <div><h3 class="cos-item-title"><a href="http://www.baidu.com/link?url=A">竞品资讯</a></h3>
                 <span class="cos-source">mall.jd.com</span></div>
            <div><h3 class="cos-item-title"><a href="http://www.baidu.com/link?url=B">我的软文</a></h3>
                 <span class="cos-source">知乎</span></div>
          </div>
        </div>
      </div>
    </div>
    """
    news = baidu_keyword.parse_serp(html)["news_links"]
    assert len(news) == 2
    # 多条结果同容器 → 全部 fail-open，B（我的软文）绝不能被 A 的 jd 来源连累
    assert all(l.get("show_host") is None for l in news), (
        f"多结果容器必须 fail-open，实际 {[l.get('show_host') for l in news]}"
    )


def test_check_block_prefilters_excluded_show_host_without_resolving(monkeypatch):
    """show_host 命中 exclude_set 时，在 resolve_baidu_link 之前就跳过 —— 省一次
    /link 跳转解析。与 resolve 后过滤同结果（不计 rank、不抓正文）。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    _setup_check_block_mocks(monkeypatch)

    resolved: list[str] = []
    real_resolve = baidu_keyword.resolve_baidu_link

    def _tracking_resolve(u, **kw):
        resolved.append(u)
        return real_resolve(u, **kw)

    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", _tracking_resolve)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "jd ad", "href": "http://www.baidu.com/link?url=JD", "show_host": "mall.jd.com"},
        {"title": "article", "href": "https://example.com/a", "show_host": "example.com"},
    ]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        exclude_set={"jd.com"},
    )
    # jd 被 show_host 预过滤：从未 resolve、不占 rank
    assert "http://www.baidu.com/link?url=JD" not in resolved
    assert [r["host"] for r in out] == ["example.com"]
    # 只有 example 走了 article pacer（jd 连 pacer 都没碰）
    assert calls == ["baidu_keyword:article"]


def test_check_block_show_host_display_name_falls_through_to_resolve(monkeypatch):
    """show_host 是显示名（None）或非排除域名时，走原 resolve 后过滤路径，零回归。"""
    _setup_check_block_mocks(monkeypatch)
    from csm_core.monitor import rate_limit as _rl
    fake_get_pacer, _calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)

    resolved: list[str] = []
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link",
                        lambda u, **kw: resolved.append(u) or u)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "jd via display name", "href": "https://item.jd.com/1.html", "show_host": None},
    ]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        exclude_set={"jd.com"},
    )
    # show_host=None → 不预过滤 → 仍 resolve，随后按真实 host 过滤掉（原行为）
    assert resolved == ["https://item.jd.com/1.html"]
    assert out == []


def test_check_block_cross_run_cache_hit_skips_article_fetch(monkeypatch):
    """T5 跨轮正向缓存：上轮确认命中的 URL（未过期、brand 在本任务品牌列表里），
    本轮直接判命中、跳过正文抓取 + article pacer；rank 仍按本轮 SERP 位置算。"""
    import time as _t
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    fetched: list[str] = []
    monkeypatch.setattr(baidu_keyword, "fetch_article_http",
                        lambda u, **kw: fetched.append(u) or {"content": "x" * 500})

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter._cross_run_hits["https://example.com/a"] = ("Claude", _t.monotonic() + 3600)
    links = [{"title": "t", "href": "https://example.com/a", "show_host": None}]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        cross_run_cache=adapter._cross_run_hits,
    )
    assert fetched == [], "cached hit 不应再抓正文"
    assert calls == [], "cached hit 不应调 article pacer"
    assert out[0]["matches_brand"] is True
    assert out[0]["matched_brand"] == "Claude"
    assert out[0]["source"] == "cache"
    assert out[0]["rank"] == 1


def test_check_block_cross_run_cache_writes_on_positive_match(monkeypatch):
    """正向命中的 URL 写入跨轮缓存，供后续 run 复用（未命中不写）。"""
    from csm_core.monitor import rate_limit as _rl
    fake_get_pacer, _calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(
            text="<html><body><article>" + ("Claude 产品测评。" * 40) + "</article></body></html>"
        ),
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    cache = adapter._cross_run_hits
    links = [
        {"title": "hit", "href": "https://example.com/hit", "show_host": None},
        {"title": "miss", "href": "https://example.com/miss", "show_host": None},
    ]
    # 第二条命中不同内容（无品牌）→ 用另一个 _cc_get 分支？简单起见只验第一条写入。
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        cross_run_cache=cache,
    )
    assert out[0]["matched_brand"] == "Claude"
    assert cache.get("https://example.com/hit", (None,))[0] == "Claude"


def test_check_block_does_not_cache_title_fallback_match(monkeypatch):
    """T5 准确性：title fallback 命中（正文抓取失败、靠 SERP 标题兜底）绝不写跨轮
    缓存 —— 否则一次瞬时抓取失败的 title-only 判定被钉死 6h，掩盖文章其实可抓 /
    可能已不含品牌。只有真·正文命中才进缓存。"""
    from csm_core.monitor import rate_limit as _rl
    fake_get_pacer, _c = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    # 正文抓取失败：内容过短 + is_blocked → fetch_failed，正文匹配 None
    monkeypatch.setattr(baidu_keyword, "fetch_article_http",
                        lambda u, **kw: {"content": "x", "is_blocked": True})

    adapter = baidu_keyword.BaiduKeywordAdapter()
    cache = adapter._cross_run_hits
    # SERP 标题含品牌 → 触发 title fallback 命中
    links = [{"title": "Claude 深度测评", "href": "https://example.com/a", "show_host": None}]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        cross_run_cache=cache,
    )
    assert out[0]["matched_brand"] == "Claude"  # title fallback 判命中
    assert "https://example.com/a" not in cache, "title fallback 命中不应写跨轮缓存"


def test_check_block_cross_run_cache_expired_entry_refetches(monkeypatch):
    """过期条目（超 TTL）→ 当作未命中，重新抓正文。"""
    import time as _t
    from csm_core.monitor import rate_limit as _rl
    fake_get_pacer, _calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    fetched: list[str] = []
    monkeypatch.setattr(baidu_keyword, "fetch_article_http",
                        lambda u, **kw: fetched.append(u) or {"content": "Claude " * 200})

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter._cross_run_hits["https://example.com/a"] = ("Claude", _t.monotonic() - 1)  # 已过期
    links = [{"title": "t", "href": "https://example.com/a", "show_host": None}]
    adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        cross_run_cache=adapter._cross_run_hits,
    )
    assert fetched == ["https://example.com/a"], "过期条目必须重新抓取"


def test_check_block_cross_run_cache_wrong_brand_ignored(monkeypatch):
    """缓存里记的 brand 不在本任务品牌列表里 → 不复用，正常抓取（多任务隔离）。"""
    import time as _t
    from csm_core.monitor import rate_limit as _rl
    fake_get_pacer, _calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u, **kw: u)
    fetched: list[str] = []
    monkeypatch.setattr(baidu_keyword, "fetch_article_http",
                        lambda u, **kw: fetched.append(u) or {"content": "z" * 500})

    adapter = baidu_keyword.BaiduKeywordAdapter()
    # 缓存记的是别的任务的品牌 Nova
    adapter._cross_run_hits["https://example.com/a"] = ("Nova", _t.monotonic() + 3600)
    links = [{"title": "t", "href": "https://example.com/a", "show_host": None}]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        cross_run_cache=adapter._cross_run_hits,
    )
    assert fetched == ["https://example.com/a"], "别的品牌的缓存不能复用"
    assert out[0]["matched_brand"] is None


def test_check_block_excluded_host_skips_pacer(monkeypatch):
    """exclude_set 命中的 host 不调 pacer（不计 rank 也不空耗节流时间）。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    _setup_check_block_mocks(monkeypatch)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "jd ad",   "href": "https://item.jd.com/123.html"},  # excluded
        {"title": "article", "href": "https://example.com/a"},
        {"title": "tmall",   "href": "https://detail.tmall.com/x"},    # excluded
    ]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
        exclude_set={"jd.com", "tmall.com"},
    )
    # 只有 example.com 被实际抓 + 计 rank + 调 pacer
    assert len(out) == 1
    assert out[0]["host"] == "example.com"
    assert calls == ["baidu_keyword:article"]


def test_check_block_baidu_vertical_hosts_never_ranked(monkeypatch):
    """百度自有垂类（百科 / 自搜索 / 图片等）永不计 rank、不抓正文、不调
    pacer —— cosc 知识卡结构排除移除后的补偿守卫（词条正文天然含品牌词，
    计入会假报「自家软文排第 N」）。百家号是真实文章宿主，不受影响。"""
    from csm_core.monitor import rate_limit as _rl

    fake_get_pacer, calls = _make_pacer_tracker()
    monkeypatch.setattr(_rl, "get_pacer", fake_get_pacer)
    _setup_check_block_mocks(monkeypatch)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    links = [
        {"title": "baike", "href": "https://baike.baidu.com/item/%E5%93%81%E7%89%8C/1"},
        {"title": "self-search", "href": "https://www.baidu.com/s?wd=%E5%93%81%E7%89%8C"},
        {"title": "article", "href": "https://example.com/a"},
        {"title": "bjh", "href": "https://baijiahao.baidu.com/s?id=1"},
    ]
    out = adapter._check_block(
        page=None, links=links, brands=["Claude"], block="default",
    )
    assert [(r["rank"], r["host"]) for r in out] == [
        (1, "example.com"),
        (2, "baijiahao.baidu.com"),
    ]
    assert calls == ["baidu_keyword:article", "baidu_keyword:baijiahao"]


def test_apply_settings_configures_article_and_baijiahao_pacers(monkeypatch):
    """apply_settings 把 SERP / article / baijiahao 三个 pacer 都配上对应的
    [N, 2N] jitter 窗口。"""
    from csm_core.monitor import rate_limit as _rl

    configs: dict[str, tuple[float, float]] = {}

    class _ConfigSpy:
        def __init__(self, name: str) -> None:
            self.name = name

        def wait(self) -> None:
            pass

        def configure(self, *, delay_min: float, delay_max: float) -> None:
            configs[self.name] = (delay_min, delay_max)

    monkeypatch.setattr(_rl, "get_pacer", lambda name: _ConfigSpy(name))

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(
        serp_pacing_seconds=5,
        article_pacing_seconds=4,
        baijiahao_pacing_seconds=10,
    )
    assert configs["baidu_keyword"] == (5.0, 10.0)
    assert configs["baidu_keyword:article"] == (4.0, 8.0)
    assert configs["baidu_keyword:baijiahao"] == (10.0, 20.0)


# ── _get_session / _drop_session ───────────────────────────────────────
# 注：UA 轮换池已删除 —— impersonate="chrome131" 会发出自洽的 UA + client
# hints，旧的 _UA_POOL 用 Windows UA 覆盖却让 client hints 说 macOS chrome120，
# 3/4 会话指纹自相矛盾，是明显机器人特征（见 P1 #4）。


def test_get_session_caches_per_task(monkeypatch):
    """同一 task_id 调两次 _get_session 返回同一对象；不同 task_id 返回不同对象."""
    from csm_core.monitor.platforms import baidu_keyword
    from typing import Any

    # Avoid real curl_cffi calls. Build a fake Session class that records
    # warmup GETs and exposes a .close().
    created: list[Any] = []

    class FakeSession:
        def __init__(self, *a, **kw):
            self.headers = {}
            self.closed = False
            created.append(self)

        def get(self, url, **kwargs):
            return type("R", (), {"status_code": 200})()

        def close(self):
            self.closed = True

    import sys
    fake_cc = type("M", (), {"Session": FakeSession})()
    # Replace the module-attribute import path used by _get_session
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_cc)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    s1 = adapter._get_session(42)
    s2 = adapter._get_session(42)
    s3 = adapter._get_session(43)
    assert s1 is s2, "same task_id should get cached session"
    assert s1 is not s3, "different task_id should get different session"
    assert len(created) == 2


def test_get_session_warmup_failure_not_fatal(monkeypatch, caplog):
    """warm-up GET baidu.com 抛异常时 _get_session 仍正常返回 session."""
    from csm_core.monitor.platforms import baidu_keyword

    class FakeSession:
        def __init__(self, *a, **kw):
            self.headers = {}

        def get(self, url, **kwargs):
            raise RuntimeError("simulated network failure")

        def close(self):
            pass

    import sys
    fake_cc = type("M", (), {"Session": FakeSession})()
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_cc)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    with caplog.at_level("INFO", logger="csm_core.monitor.platforms.baidu_keyword"):
        sess = adapter._get_session(99)
    assert sess is not None
    assert "warmup failed" in caplog.text.lower()


def test_drop_session_removes_and_closes(monkeypatch):
    """_drop_session 应该从 dict 里移除并调 close。重复调用 idempotent."""
    from csm_core.monitor.platforms import baidu_keyword

    class FakeSession:
        def __init__(self, *a, **kw):
            self.headers = {}
            self.closed = False

        def get(self, url, **kwargs):
            return type("R", (), {"status_code": 200})()

        def close(self):
            self.closed = True

    import sys
    fake_cc = type("M", (), {"Session": FakeSession})()
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_cc)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    sess = adapter._get_session(7)
    assert 7 in adapter._http_sessions
    adapter._drop_session(7)
    assert 7 not in adapter._http_sessions
    assert sess.closed is True
    # Idempotent: second call is no-op, doesn't raise
    adapter._drop_session(7)


# ── fetch() session lifecycle ──────────────────────────────────────────


def test_fetch_drops_session_on_normal_return(monkeypatch):
    """正常完成时 fetch() 在 finally 里释放 session（_http_sessions 不留残)."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask, MonitorResult
    from datetime import datetime
    from typing import Any

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(default_excluded_domains=())

    # Short-circuit fetch's heavy path: return a MonitorResult immediately
    # from _fetch_with_promotion. We're only verifying the session-cleanup
    # contract here, not the full SERP pipeline.
    captured: dict[str, Any] = {}

    def fake_promotion(self, task, keywords, brand, headless, progress_cb, cancel_token,
                       *, aliases=(), resume_from, session, session_kwargs=None):
        captured["session"] = session
        captured["task_id"] = task.id
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="ok", rank=1, metric={},
        )

    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_fetch_with_promotion",
        fake_promotion,
    )
    # Bypass curl_cffi by stubbing _get_session to a sentinel
    sentinel = object()
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_get_session",
        lambda self, tid: sentinel,
    )
    drops: list[int] = []
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_drop_session",
        lambda self, tid: drops.append(tid),
    )

    task = MonitorTask(
        id=101, type="baidu_keyword", name="t",
        target_url="https://www.baidu.com/s?wd=x",
        config={"search_keywords": ["x"], "target_brand": "y"},
    )
    result = adapter.fetch(task)
    assert result.status == "ok"
    assert captured["session"] is sentinel
    assert drops == [101]


def test_fetch_drops_session_on_risk_control(monkeypatch):
    """RiskControlException 时 session 也被 drop (脏 cookie 不能复用)."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask
    from csm_core.monitor.drivers.risk_detector import (
        RiskControlException, RiskSignal,
    )

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(default_excluded_domains=())

    def fake_promotion(self, task, keywords, brand, headless, progress_cb, cancel_token,
                       *, aliases=(), resume_from, session, session_kwargs=None):
        raise RiskControlException(
            RiskSignal(layer="url", detail="wappass triggered"), progress=2,
        )

    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_fetch_with_promotion",
        fake_promotion,
    )
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_get_session",
        lambda self, tid: object(),
    )
    drops: list[int] = []
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_drop_session",
        lambda self, tid: drops.append(tid),
    )

    task = MonitorTask(
        id=202, type="baidu_keyword", name="t",
        target_url="https://www.baidu.com/s?wd=x",
        config={"search_keywords": ["x"], "target_brand": "y"},
    )
    import pytest
    with pytest.raises(RiskControlException):
        adapter.fetch(task)
    assert drops == [202], "session should be dropped even when RiskControlException propagates"


# ── _navigate_to_serp (simplified: direct goto(serp_url)) ──────────────


def test_navigate_to_serp_direct_goto():
    """_navigate_to_serp performs exactly one page.goto on the SERP url.

    The 3-stage home→fill→Enter flow was retired — its stable timing
    pattern was itself a bot signal. With persistent BDUSS the direct
    goto looks like a real user opening SERP from a bookmark / external
    link.
    """
    from csm_core.monitor.platforms import baidu_keyword

    calls: list[tuple] = []

    class FakePage:
        def goto(self, url, **kwargs):
            calls.append(("goto", url, kwargs))
            return "fake-response"

    response = baidu_keyword._navigate_to_serp(FakePage(), keyword="吸尘器")

    assert response == "fake-response"
    assert len(calls) == 1
    op, url, kwargs = calls[0]
    assert op == "goto"
    assert url.startswith("https://www.baidu.com/s?wd=")
    # quote() encodes 吸尘器 as %E5%90%B8%E5%B0%98%E5%99%A8
    assert "%E5%90%B8%E5%B0%98%E5%99%A8" in url
    assert kwargs.get("wait_until") == "domcontentloaded"
    # 60s（非 30s）：native 副本 Chrome 首次启动 + 首个 SERP 加载慢，
    # 实测 30s 不够，见 _navigate_to_serp 的 timeout=60000 注释。
    assert kwargs.get("timeout") == 60000


def test_navigate_to_serp_does_not_touch_input_or_keyboard():
    """Guard against future regression: the function must NOT call
    fill / click / keyboard / mouse / wait_for_timeout — those were
    the bot-signal-leaking ops.
    """
    from csm_core.monitor.platforms import baidu_keyword

    forbidden_calls: list[str] = []

    class FakePage:
        def goto(self, url, **kwargs):
            return "fake-response"
        def fill(self, *a, **kw):
            forbidden_calls.append("fill")
        def click(self, *a, **kw):
            forbidden_calls.append("click")
        def wait_for_timeout(self, *a, **kw):
            forbidden_calls.append("wait_for_timeout")
        def expect_navigation(self, **kw):
            forbidden_calls.append("expect_navigation")
            raise AssertionError("should not be called")

    baidu_keyword._navigate_to_serp(FakePage(), keyword="test")

    assert forbidden_calls == [], (
        f"_navigate_to_serp should only call page.goto, got: {forbidden_calls}"
    )


def test_apply_settings_forces_baidu_concurrency_to_one():
    """persistent_context profile lock requires serial baidu execution.
    apply_settings should reconfigure rate_limit accordingly."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.browser_infra import rate_limit

    # Clean slate — clear any prior configuration for this platform
    with rate_limit._sem_lock:
        rate_limit._sems.pop(baidu_keyword.BaiduKeywordAdapter.platform, None)
        rate_limit._max_concurrent.pop(baidu_keyword.BaiduKeywordAdapter.platform, None)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(default_excluded_domains=())

    assert rate_limit._max_concurrent[baidu_keyword.BaiduKeywordAdapter.platform] == 1


# ── fetch BDUSS pre-flight check (Layer 3) ─────────────────────────────


def test_assert_baidu_logged_in_passes_when_bduss_present():
    """The pure helper used by _fetch_once must NOT raise when BDUSS
    is in the cookie list."""
    from csm_core.monitor.platforms import baidu_keyword

    adapter = baidu_keyword.BaiduKeywordAdapter()
    cookies = [
        {"name": "BAIDUID", "value": "irrelevant"},
        {"name": "BDUSS", "value": "abc"},
    ]
    # Should not raise
    adapter._assert_baidu_logged_in(cookies, resume_from=0)


def test_assert_baidu_logged_in_raises_auth_when_bduss_missing():
    """Same helper raises RiskControlException(layer='auth') when BDUSS
    is missing, with progress = resume_from passed through."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.drivers.risk_detector import RiskControlException

    adapter = baidu_keyword.BaiduKeywordAdapter()
    cookies = [{"name": "BAIDUID", "value": "no_bduss_here"}]
    try:
        adapter._assert_baidu_logged_in(cookies, resume_from=3)
    except RiskControlException as e:
        assert e.signal.layer == "auth"
        assert e.progress == 3
    else:
        raise AssertionError("expected RiskControlException")


def test_fetch_raises_auth_risk_control_when_not_logged_in(monkeypatch, settings_path):
    """If session.context.cookies returns no BDUSS, fetch must raise
    RiskControlException(layer='auth') with progress=resume_from before
    making a single SERP request.

    ``settings_path`` pins a clean (non-native) config so the inline fake
    session — which only accepts ``headless`` — isn't handed native-mode
    kwargs from a developer's real settings.json.
    """
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask
    from csm_core.monitor.drivers.risk_detector import RiskControlException

    class FakeContext:
        def cookies(self, url=None):
            return []  # no BDUSS — logged out

    class FakePage:
        def goto(self, url, **kwargs):
            raise AssertionError("should not reach goto when not logged in")

    class FakeSession:
        def __init__(self):
            self.page = FakePage()
            self.context = FakeContext()

    from contextlib import contextmanager
    @contextmanager
    def fake_session(*, headless, user_data_dir=None):
        yield FakeSession()

    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", fake_session)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    task = MonitorTask(
        id=42, type="baidu_keyword", name="test",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keywords": ["吸尘器", "洗碗机"], "target_brand": "CEWEY"},
    )

    try:
        adapter.fetch(task, resume_from=1)
    except RiskControlException as e:
        assert e.signal.layer == "auth"
        assert "登录" in e.signal.detail or "BDUSS" in e.signal.detail
        assert e.progress == 1
    else:
        raise AssertionError("expected RiskControlException")


def test_fetch_raises_auth_when_serp_redirects_to_login(monkeypatch, settings_path):
    """BDUSS in cookies but SERP comes back as a wappass redirect →
    raise RiskControlException(layer='auth') with progress=kw_idx
    (so resume continues from this keyword, not from the start).

    ``settings_path`` pins a clean (non-native) config — see the sibling
    auth test for why the inline fake session needs it.
    """
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask
    from csm_core.monitor.drivers.risk_detector import RiskControlException

    class FakeResp:
        def __init__(self, url: str):
            self.url = url

    class FakeContext:
        def cookies(self, url=None):
            return [{"name": "BDUSS", "value": "x"}]

    class FakePage:
        def goto(self, url, **kwargs):
            # baidu redirected SERP to the login wall
            return FakeResp("https://wappass.baidu.com/static/captcha/tuxing.html?...")
        def content(self):
            return ""

    class FakeSession:
        def __init__(self):
            self.page = FakePage()
            self.context = FakeContext()

    from contextlib import contextmanager
    @contextmanager
    def fake_session(*, headless, user_data_dir=None):
        yield FakeSession()

    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", fake_session)
    # Prevent _check_block + article fetches from running
    monkeypatch.setattr(baidu_keyword, "parse_serp", lambda html: {"default_links": [], "news_links": [], "news_present": False})
    # Disable the article-level fetches and pacer so the test runs in <1s
    from csm_core.monitor import rate_limit
    monkeypatch.setattr(rate_limit, "get_pacer", lambda key: type(
        "P", (), {"wait": lambda self: None})())
    monkeypatch.setattr(rate_limit, "get_breaker", lambda key: type(
        "B", (), {"allow": lambda self: True,
                  "record_success": lambda self: None,
                  "record_failure": lambda self: None})())

    adapter = baidu_keyword.BaiduKeywordAdapter()
    task = MonitorTask(
        id=99, type="baidu_keyword", name="test",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keywords": ["aaa", "bbb"], "target_brand": "X"},
    )

    try:
        adapter.fetch(task, resume_from=0)
    except RiskControlException as e:
        assert e.signal.layer == "auth"
        assert e.progress == 0  # failed on first keyword
    else:
        raise AssertionError("expected RiskControlException(layer='auth')")


def test_fetch_returns_error_when_native_mode_copy_path_missing(monkeypatch):
    """use_native_chrome=True 但 chrome_profile_copy_path 未导入
    → 返回 status=error 提示用户先复制 profile。"""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask

    fake_cfg = MagicMock()
    fake_cfg.monitor.baidu_keyword.use_native_chrome = True
    fake_cfg.monitor.baidu_keyword.chrome_executable_path = "C:/x/chrome.exe"
    fake_cfg.monitor.baidu_keyword.chrome_profile_copy_path = None  # 未导入
    monkeypatch.setattr("csm_sidecar.services.config_service.load", lambda: fake_cfg)

    task = MonitorTask(
        id=1, type="baidu_keyword", name="t", target_url="https://baidu.com",
        config={"search_keywords": ["x"], "target_brand": "y"},
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    result = adapter.fetch(task)
    assert result.status == "error"
    assert "未导入 Chrome profile 副本" in (result.error_message or "")


def test_fetch_returns_error_when_native_mode_executable_missing(monkeypatch):
    """use_native_chrome=True + copy_path 存在 但 chrome_executable_path 缺失
    → 返回 status=error 提示用户配置可执行文件路径。"""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask

    fake_cfg = MagicMock()
    fake_cfg.monitor.baidu_keyword.use_native_chrome = True
    fake_cfg.monitor.baidu_keyword.chrome_executable_path = None  # 缺失
    fake_cfg.monitor.baidu_keyword.chrome_profile_copy_path = "C:/CSM-Data/baidu_chrome_profile_copy"
    monkeypatch.setattr("csm_sidecar.services.config_service.load", lambda: fake_cfg)

    task = MonitorTask(
        id=1, type="baidu_keyword", name="t", target_url="https://baidu.com",
        config={"search_keywords": ["x"], "target_brand": "y"},
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    result = adapter.fetch(task)
    assert result.status == "error"
    assert "缺 Chrome 可执行文件路径" in (result.error_message or "")


# ── _try_human_solve 软着陆验证码 ──────────────────────────────────────────

def test_try_human_solve_returns_true_when_url_leaves_risk_domain(monkeypatch):
    """page.url 从 wappass.baidu.com 切回 www.baidu.com/s → 返回 True。"""
    from csm_core.monitor.platforms import baidu_keyword

    state = {"polls": 0}
    fake_page = MagicMock()
    def url_property(self):
        state["polls"] += 1
        # 前 3 次还在 wappass，第 4 次跳回 baidu/s
        if state["polls"] <= 3:
            return "https://wappass.baidu.com/static/captcha/tuxing.html"
        return "https://www.baidu.com/s?wd=test"
    type(fake_page).url = property(url_property)
    fake_page.query_selector.return_value = None  # 没有 captcha DOM

    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: None)

    result = baidu_keyword._try_human_solve(
        page=fake_page, keyword="test", kw_idx=5, timeout_s=5, poll_interval_s=0.01,
    )
    assert result is True
    assert state["polls"] >= 4


def test_try_human_solve_returns_false_on_timeout(monkeypatch):
    """超时仍在 wappass → 返回 False（caller 走原 raise 路径）。"""
    from csm_core.monitor.platforms import baidu_keyword

    fake_page = MagicMock()
    type(fake_page).url = property(lambda self: "https://wappass.baidu.com/captcha")
    fake_page.query_selector.return_value = MagicMock()  # passmod DOM 还在

    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: None)

    result = baidu_keyword._try_human_solve(
        page=fake_page, keyword="test", kw_idx=5, timeout_s=0.05, poll_interval_s=0.01,
    )
    assert result is False


def test_try_human_solve_emits_notification_with_keyword(monkeypatch):
    """触发时发系统通知带关键词。"""
    from csm_core.monitor.platforms import baidu_keyword

    fake_page = MagicMock()
    type(fake_page).url = property(lambda self: "https://www.baidu.com/s?wd=already_solved")
    fake_page.query_selector.return_value = None

    captured: list = []
    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: captured.append(kw))

    baidu_keyword._try_human_solve(
        page=fake_page, keyword="testkw", kw_idx=3, timeout_s=1, poll_interval_s=0.01,
    )
    assert len(captured) == 1
    assert "testkw" in captured[0].get("body", "")


def test_try_human_solve_surfaces_then_hides(monkeypatch):
    """验证码等待期间窗口上浮；退出（解完或超时）后窗口移回屏外。

    检查：
    - surface_window 与 hide_window 各调一次
    - surface 发生在 hide 之前（无论是解完还是超时路径）
    - 解完路径：返回 True
    """
    from csm_core.monitor.platforms import baidu_keyword

    calls: list[str] = []
    monkeypatch.setattr(baidu_keyword, "surface_window", lambda p: calls.append("surface"))
    monkeypatch.setattr(baidu_keyword, "hide_window", lambda p: calls.append("hide"))
    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: None)

    # page.url returns a safe (non-risk) URL → loop exits immediately with True
    fake_page = MagicMock()
    type(fake_page).url = property(lambda self: "https://www.baidu.com/s?wd=ok")
    fake_page.query_selector.return_value = None  # no captcha DOM

    solved = baidu_keyword._try_human_solve(
        page=fake_page, keyword="x", kw_idx=0, timeout_s=2, poll_interval_s=0,
    )
    assert solved is True
    assert "surface" in calls, "surface_window should have been called"
    assert "hide" in calls, "hide_window should have been called"
    assert calls.index("surface") < calls.index("hide"), (
        f"surface must happen before hide; got call order: {calls}"
    )


def test_try_human_solve_hides_on_timeout(monkeypatch):
    """超时路径：hide_window 也必须被调到（finally 覆盖两条出口）。"""
    from csm_core.monitor.platforms import baidu_keyword

    calls: list[str] = []
    monkeypatch.setattr(baidu_keyword, "surface_window", lambda p: calls.append("surface"))
    monkeypatch.setattr(baidu_keyword, "hide_window", lambda p: calls.append("hide"))
    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: None)

    # page stays in risk URL → loop times out → returns False
    fake_page = MagicMock()
    type(fake_page).url = property(lambda self: "https://wappass.baidu.com/captcha")
    fake_page.query_selector.return_value = MagicMock()  # captcha DOM still present

    solved = baidu_keyword._try_human_solve(
        page=fake_page, keyword="x", kw_idx=0, timeout_s=0.05, poll_interval_s=0.01,
    )
    assert solved is False
    assert "surface" in calls, "surface_window should have been called even on timeout path"
    assert "hide" in calls, "hide_window must be called in finally (timeout path)"
    assert calls.index("surface") < calls.index("hide")


# ── B' pivot: fetch() native mode 用 copy_path ──────────────────────────────

def test_fetch_uses_copy_path_in_native_mode(monkeypatch):
    """B' pivot: use_native_chrome=True → baidu_browser_session 拿到
    user_data_dir=copy_path 且 chrome_profile_name='Default'（副本内固定）。"""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask
    from pathlib import Path

    copy_path = "C:/CSM-Data/baidu_chrome_profile_copy"

    fake_cfg = MagicMock()
    fake_cfg.monitor.baidu_keyword.use_native_chrome = True
    fake_cfg.monitor.baidu_keyword.chrome_executable_path = "C:/x/chrome.exe"
    fake_cfg.monitor.baidu_keyword.chrome_profile_copy_path = copy_path
    monkeypatch.setattr("csm_sidecar.services.config_service.load", lambda: fake_cfg)

    session_kwargs_received: dict = {}
    from contextlib import contextmanager

    @contextmanager
    def fake_session(**kw):
        session_kwargs_received.update(kw)
        sess = MagicMock()
        sess.page = MagicMock()
        sess.context = MagicMock()
        sess.context.cookies.return_value = [{"name": "BDUSS", "value": "x"}]
        yield sess

    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", fake_session)

    task = MonitorTask(
        id=99, type="baidu_keyword", name="t", target_url="https://baidu.com",
        config={"search_keywords": ["test"], "target_brand": "y"},
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.fetch(task)

    assert session_kwargs_received.get("use_native_chrome") is True
    assert session_kwargs_received.get("user_data_dir") == Path(copy_path)
    assert session_kwargs_received.get("chrome_profile_name") == "Default"
    assert session_kwargs_received.get("chrome_executable_path") == "C:/x/chrome.exe"
