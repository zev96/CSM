"""百度 keyword adapter 单元测试。

不真开 Chromium、不真发 HTTP。所有外部交互都 mock。
SERP 解析逻辑用真实保存的 fixture 验证。
"""
from __future__ import annotations

from pathlib import Path

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
    assert len(parsed["default_links"]) == 8
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
    assert len(parsed["default_links"]) == 7
    # 两个 list 严格分开，不重复
    default_hrefs = {l["href"] for l in parsed["default_links"]}
    news_hrefs = {l["href"] for l in parsed["news_links"]}
    assert default_hrefs.isdisjoint(news_hrefs)


def test_parse_serp_empty_html_returns_empty():
    parsed = baidu_keyword.parse_serp("")
    assert parsed["default_links"] == []
    assert parsed["news_links"] == []
    assert parsed["news_present"] is False


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
    """readability 提出来正文 < 200 字 → 视为 SPA 壳，要求浏览器 fallback。"""
    short = "<html><body><div>请打开 APP 查看</div></body></html>"
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text=short),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/spa")
    assert result["needs_browser_fallback"] is True


def test_fetch_article_http_network_exception_triggers_fallback(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("dns nxdomain")

    monkeypatch.setattr(baidu_keyword, "_cc_get", boom)
    result = baidu_keyword.fetch_article_http("https://offline.example/")
    assert result["needs_browser_fallback"] is True
    assert "nxdomain" in (result["fetch_error"] or "").lower()


# ── 浏览器 fallback ─────────────────────────────────────────────────────
def test_fetch_article_browser_success():
    """给一个 fake page，验证 fallback 抽到 content 并标 source=browser。"""
    long_text = "  这里是浏览器 fallback 抓到的正文：" + ("Claude " * 30)

    class FakePage:
        def goto(self, url, **kw):
            pass

        def content(self):
            return f"<html><body><article>{long_text}</article></body></html>"

    result = baidu_keyword.fetch_article_browser(
        FakePage(), "https://spa.example/post"
    )
    assert result["source"] == "browser"
    assert result["fetch_error"] is None
    assert "Claude" in result["content"]


def test_fetch_article_browser_navigation_exception():
    class FakePage:
        def goto(self, url, **kw):
            raise RuntimeError("navigation timeout")

        def content(self):
            return ""

    result = baidu_keyword.fetch_article_browser(
        FakePage(), "https://timeout.example/"
    )
    assert result["source"] == "browser"
    assert "navigation timeout" in (result["fetch_error"] or "")


# ── 完整 fetch 编排 ──────────────────────────────────────────────────────
from csm_core.monitor.base import MonitorTask


class FakeSession:
    """假装 IncognitoSession，只暴露 page。"""

    def __init__(self, *, serp_html: str, page_contents: dict[str, str],
                 captcha_url: str | None = None):
        self._serp_html = serp_html
        self._page_contents = page_contents
        self._captcha_url = captcha_url
        self._current_url = ""
        # adapter 通过 .page.goto / .page.content 读取
        self.page = self  # type: ignore[assignment]
        self.context = None
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
def patch_session(monkeypatch):
    """工厂 fixture：调用方传入 fake session，adapter 走 mock 路径。"""
    holder: dict = {"session": None}

    from contextlib import contextmanager

    @contextmanager
    def fake_ctx(*, headless: bool):
        holder["last_headless"] = headless
        yield holder["session"]

    monkeypatch.setattr(
        baidu_keyword, "incognito_session", fake_ctx
    )
    return holder


def test_fetch_happy_path_default_only(monkeypatch, patch_session):
    """没有最新资讯，10 条结果里第 1 条是自家、其余竞品。"""
    serp = _load("serp_default_only.html")
    # 用真实 SERP 抓出来的 hrefs 给每条配一段正文
    parsed = baidu_keyword.parse_serp(serp)
    default_links = parsed["default_links"]
    page_contents = {}
    for i, link in enumerate(default_links):
        # 解掉百度跳转后 fake_get 默认走 mock_resolve（见下）
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
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
    # 走 HTTP-first 直接命中（不绕浏览器）
    def fake_cc_get(url, **kw):
        return _FakeResp(text=page_contents.get(url, ""))
    monkeypatch.setattr(baidu_keyword, "_cc_get", fake_cc_get)

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keyword": "test", "target_brands": ["Claude"]},
    )

    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "ok"
    assert result.metric["news_present"] is False
    assert len(result.metric["default_results"]) >= 8
    assert result.metric["default_results"][0]["matches_brand"] is True
    assert result.metric["default_results"][0]["matched_brand"] == "Claude"
    assert result.rank == 1  # 首条命中
    assert result.metric["default_first_rank"] == 1
    assert result.metric["default_matched_count"] >= 1
    assert result.metric["captcha_hit"] is False


def test_fetch_captcha_returns_risk_control(monkeypatch, patch_session):
    """SERP 落地到验证码 URL，单 task 不升级（max_promotions=0 用 monkey）→
    立即返回 risk_control。"""
    serp = _load("serp_default_only.html")
    patch_session["session"] = FakeSession(
        serp_html=serp,
        page_contents={},
        captcha_url="https://wappass.baidu.com/static/captcha/tuxing.html?x=y",
    )

    # 把 max_promotions 暂时设成 0，避免单测里真跑升级流程
    baidu_keyword.ADAPTER._captcha_max_promotions = 0

    task = MonitorTask(
        id=2,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keyword": "test", "target_brands": ["Claude"]},
    )
    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "risk_control"
    assert result.metric["captcha_hit"] is True

    # 还原
    baidu_keyword.ADAPTER._captcha_max_promotions = 1


def test_fetch_breaker_open_returns_risk_control(monkeypatch):
    """熔断打开时跳过所有 IO 直接 risk_control。"""
    from csm_core.monitor.rate_limit import get_breaker
    breaker = get_breaker("baidu_keyword")
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
        config={"search_keyword": "test", "target_brands": ["x"]},
    )
    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "risk_control"
    assert "circuit breaker" in result.error_message.lower()

    # 还原
    breaker.record_success()
