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
