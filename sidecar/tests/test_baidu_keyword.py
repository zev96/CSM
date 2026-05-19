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


def test_fetch_article_browser_risk_control_raises(monkeypatch):
    """文章页 page.goto 落到 wappass / verify.baidu / safetycheck 等风控页时，
    fetch_article_browser 必须抛 RiskControlException 而不是静默返回 empty content。

    历史 bug：HTTP fetch 失败 → 浏览器 fallback → goto 跳到验证页 → readability 提不到
    正文 → 返回 content="" + fetch_error="browser content empty after readability"。
    上游误判为单条文章抓取失败，继续跑剩余 keyword，整个任务 status=ok 完成但大量
    品牌词漏匹配。修复：detect_risk(page, response) 任一层命中即 raise，让 runner
    跟 SERP 命中走同一条 retry/breakpoint 路径。progress=None 表示非 per-keyword 风控。
    """
    from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException

    class FakePage:
        def goto(self, url, **kw):
            return None  # response None 也没关系，detect_risk 被 mock 了

        def content(self):
            return ""

    def fake_detect_risk(page, response=None):
        return RiskSignal(layer="url", detail="URL matches 'wappass.baidu.com'")

    # 通过模块命名空间注入，跟现有 TestRiskDetectionIntegration 一样
    monkeypatch.setattr(baidu_keyword, "detect_risk", fake_detect_risk)

    with pytest.raises(RiskControlException) as exc_info:
        baidu_keyword.fetch_article_browser(FakePage(), "https://example.com/article")

    assert exc_info.value.progress is None, (
        f"文章页风控不绑定具体 keyword 进度；期望 progress=None，实际 {exc_info.value.progress!r}"
    )
    assert exc_info.value.signal.layer == "url"


# ── 完整 fetch 编排 ──────────────────────────────────────────────────────
from csm_core.monitor.base import MonitorTask


class FakeSession:
    """假装 IncognitoSession，只暴露 page。支持多关键词顺序 goto。"""

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
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
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


def test_fetch_breaker_open_returns_risk_control(monkeypatch):
    """熔断打开时跳过所有 IO 直接 risk_control。"""
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
        assert result.status == "risk_control"
        assert "circuit breaker" in result.error_message.lower()
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

        # 用最简 SERP HTML（空解析结果即可，不关心品牌匹配）
        serp = _load("serp_default_only.html")
        # 5 个关键词；第 3 个（index=2）触发风控
        patch_session["session"] = FakeSession(
            serp_html=serp,
            page_contents={},
        )
        # resolve_baidu_link / _cc_get 不会被调到（风控在 SERP 阶段抛出）
        monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)

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
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
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
