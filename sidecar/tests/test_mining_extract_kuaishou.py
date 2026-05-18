import threading
from pathlib import Path
from unittest.mock import MagicMock

from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter, _PHOTO_ID_RE
from csm_core.mining.models import VideoCard


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "kuaishou" / "search_dom.html"


def test_extract_two_cards_from_fixture():
    adapter = KuaishouSearchAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    cards = adapter._extract_from_dom(html, exclude_ids=set())
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "kuaishou"
    assert c1.platform_video_id == "3xabc123"
    assert c1.url == "https://www.kuaishou.com/short-video/3xabc123"
    assert c1.title == "扫地机器人 推荐"
    assert c1.author_name == "家电达人"
    assert c1.play_count == 123_000   # 12.3万
    assert c1.like_count == 3_456
    assert c1.duration_sec == 83      # 1:23


def test_extract_respects_exclude_ids():
    adapter = KuaishouSearchAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    cards = adapter._extract_from_dom(html, exclude_ids={"3xabc123"})
    assert len(cards) == 1
    assert cards[0].platform_video_id == "3xdef456"


def test_short_video_id_with_hyphen_extracted_consistently():
    """Real Kuaishou photo IDs include hyphens. Verify adapter regex and storage regex
    parse identically so the same URL produces the same platform_video_id regardless
    of which code path handles it (broken dedup results otherwise).

    The regexes live in:
    - kuaishou_search.py  _PHOTO_ID_RE
    - kuaishou_search.py  _EXTRACT_JS  (JS regex inside page.evaluate)
    - mining/storage.py   _VIDEO_ID_PATTERNS["kuaishou"][0]
    """
    from csm_core.mining import storage

    test_url = "https://www.kuaishou.com/short-video/3xa1b2c-def-456"

    # Adapter regex
    m = _PHOTO_ID_RE.search(test_url)
    assert m is not None, "adapter _PHOTO_ID_RE must match hyphenated photo ID"
    adapter_id = m.group(1)
    assert "-" in adapter_id, f"adapter regex must include hyphens, got: {adapter_id!r}"

    # Storage helper
    storage_id = storage.extract_platform_video_id("kuaishou", test_url)
    assert storage_id is not None, "storage.extract_platform_video_id must match hyphenated URL"
    assert "-" in storage_id, f"storage regex must include hyphens, got: {storage_id!r}"

    assert adapter_id == storage_id, (
        f"adapter regex and storage regex disagree on {test_url!r}: "
        f"adapter={adapter_id!r}, storage={storage_id!r}"
    )


class TestKuaishouDomFallback:
    """When page.evaluate(_EXTRACT_JS) returns 0 items (SPA fingerprint block),
    _scrape_dom should be called and its cards emitted."""

    def test_scrape_dom_method_exists(self):
        """KuaishouSearchAdapter must expose _scrape_dom."""
        adapter = KuaishouSearchAdapter()
        assert callable(getattr(adapter, "_scrape_dom", None)), \
            "_scrape_dom method must exist on KuaishouSearchAdapter"

    def test_xhr_empty_triggers_dom_fallback(self, monkeypatch):
        """search() getting 0 cards from page.evaluate must call _scrape_dom."""
        adapter = KuaishouSearchAdapter()

        dom_calls = {"n": 0}

        def fake_scrape_dom(page, target_count, on_card, *, seen=None):
            dom_calls["n"] += 1
            cards = [
                VideoCard(
                    platform="kuaishou",
                    platform_video_id="3xfallback001",
                    url="https://www.kuaishou.com/short-video/3xfallback001",
                    title="dom-fallback-ks-1",
                ),
                VideoCard(
                    platform="kuaishou",
                    platform_video_id="3xfallback002",
                    url="https://www.kuaishou.com/short-video/3xfallback002",
                    title="dom-fallback-ks-2",
                ),
            ]
            for c in cards:
                on_card(c)
            return cards

        monkeypatch.setattr(adapter, "_scrape_dom", fake_scrape_dom, raising=False)

        monkeypatch.setattr(
            "csm_core.mining.platforms.kuaishou_search.mining_browser.has_login_cookie",
            lambda platform: True,
        )

        mock_page = MagicMock()
        mock_page.url = "https://www.kuaishou.com/search/video?searchKey=test"
        mock_page.title.return_value = "快手"
        mock_page.__enter__ = lambda s: mock_page
        mock_page.__exit__ = MagicMock(return_value=False)
        mock_page.goto = MagicMock()
        # evaluate always returns empty list — simulates the fingerprint block
        mock_page.evaluate = MagicMock(return_value=[])

        monkeypatch.setattr(
            "csm_core.mining.platforms.kuaishou_search.mining_browser.launched_page",
            lambda platform: mock_page,
        )
        monkeypatch.setattr(
            "csm_core.mining.platforms.kuaishou_search._looks_like_captcha",
            lambda page: False,
        )
        monkeypatch.setattr("csm_core.mining.platforms.kuaishou_search.time.sleep", lambda _: None)

        cards_received: list = []
        cancel = threading.Event()

        outcome = adapter.search(
            keyword="test",
            target_count=10,
            on_card=lambda c: cards_received.append(c),
            on_progress=lambda *a: None,
            cancel_event=cancel,
        )

        assert dom_calls["n"] == 1, (
            f"DOM fallback should fire exactly once when evaluate returns nothing, got {dom_calls['n']}"
        )
        assert len(cards_received) == 2, (
            f"Fallback DOM cards should be emitted via on_card, got {len(cards_received)}"
        )
        assert cards_received[0].platform_video_id == "3xfallback001"
        assert outcome.status == "done"

    def test_dom_fallback_not_triggered_when_evaluate_has_items(self, monkeypatch):
        """When page.evaluate returns cards, _scrape_dom must NOT be called."""
        adapter = KuaishouSearchAdapter()

        dom_calls = {"n": 0}

        def fake_scrape_dom(page, target_count, on_card, *, seen=None):
            dom_calls["n"] += 1
            return []

        monkeypatch.setattr(adapter, "_scrape_dom", fake_scrape_dom, raising=False)

        monkeypatch.setattr(
            "csm_core.mining.platforms.kuaishou_search.mining_browser.has_login_cookie",
            lambda platform: True,
        )

        mock_page = MagicMock()
        mock_page.url = "https://www.kuaishou.com/search/video?searchKey=test"
        mock_page.title.return_value = "快手"
        mock_page.__enter__ = lambda s: mock_page
        mock_page.__exit__ = MagicMock(return_value=False)
        mock_page.goto = MagicMock()
        # evaluate returns 1 card — normal path
        mock_page.evaluate = MagicMock(return_value=[{
            "photo_id": "3xnormalcard",
            "url": "https://www.kuaishou.com/short-video/3xnormalcard",
            "title": "normal card",
            "author": "author1",
            "duration_text": "1:30",
            "play_text": "1万",
            "like_text": "500",
            "cover": "",
        }])

        monkeypatch.setattr(
            "csm_core.mining.platforms.kuaishou_search.mining_browser.launched_page",
            lambda platform: mock_page,
        )
        monkeypatch.setattr(
            "csm_core.mining.platforms.kuaishou_search._looks_like_captcha",
            lambda page: False,
        )
        monkeypatch.setattr("csm_core.mining.platforms.kuaishou_search.time.sleep", lambda _: None)

        cards_received: list = []
        cancel = threading.Event()

        outcome = adapter.search(
            keyword="test",
            target_count=10,
            on_card=lambda c: cards_received.append(c),
            on_progress=lambda *a: None,
            cancel_event=cancel,
        )

        assert dom_calls["n"] == 0, (
            "DOM fallback must NOT fire when page.evaluate already produced items"
        )
        assert len(cards_received) == 1
        assert cards_received[0].platform_video_id == "3xnormalcard"

    def test_dom_fallback_does_not_re_emit_seen_ids(self, monkeypatch):
        """If photo_id was already emitted via evaluate (in `seen`), DOM fallback
        must skip it — shared dedup set prevents double-emission."""
        adapter = KuaishouSearchAdapter()

        # Mock page with 2 anchors: photo IDs "3xaaa" and "3xbbb"
        anchor1 = MagicMock()
        anchor1.get_attribute.return_value = "/short-video/3xaaa"
        anchor1.text_content.return_value = "card aaa"
        anchor2 = MagicMock()
        anchor2.get_attribute.return_value = "/short-video/3xbbb"
        anchor2.text_content.return_value = "card bbb"

        mock_locator = MagicMock()
        mock_locator.all.return_value = [anchor1, anchor2]

        page = MagicMock()
        page.locator.return_value = mock_locator

        # Pre-seed `seen` with "3xaaa" — simulating evaluate already emitted it
        shared_seen: set[str] = {"3xaaa"}
        cards_emitted: list = []

        result = adapter._scrape_dom(
            page,
            target_count=10,
            on_card=lambda c: cards_emitted.append(c),
            seen=shared_seen,
        )

        assert len(result) == 1, f"Must skip 3xaaa (already in seen), got {len(result)}"
        assert result[0].platform_video_id == "3xbbb"
        assert shared_seen == {"3xaaa", "3xbbb"}, (
            f"seen must be updated with new id, got {shared_seen}"
        )
