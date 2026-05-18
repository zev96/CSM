import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.models import VideoCard


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "douyin" / "search_response.json"


def test_extract_two_cards_from_fixture():
    adapter = DouyinSearchAdapter()
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cards = adapter._extract_cards(body)
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "douyin"
    assert c1.platform_video_id == "7300000000000000001"
    assert c1.url == "https://www.douyin.com/video/7300000000000000001"
    assert c1.title == "扫地机器人推荐"
    assert c1.author_name == "测评博主"
    assert c1.author_id == "123"
    assert c1.like_count == 1234     # digg_count
    assert c1.play_count == 5678
    assert c1.duration_sec == 60     # 60000ms → 60s
    assert c1.cover_url.startswith("https://")


def test_extract_handles_missing_fields():
    adapter = DouyinSearchAdapter()
    cards = adapter._extract_cards({
        "status_code": 0,
        "data": [{"type": 1, "aweme_info": {"aweme_id": "x"}}],
    })
    assert len(cards) == 1
    assert cards[0].platform_video_id == "x"
    assert cards[0].title == ""
    assert cards[0].duration_sec is None


def test_extract_returns_empty_on_failure_status():
    adapter = DouyinSearchAdapter()
    cards = adapter._extract_cards({"status_code": 8, "data": []})
    # Adapter is forgiving on status when data is empty anyway.
    assert cards == []


class TestDouyinDomFallback:
    """When XHR path returns 0 items, _scrape_dom should be called as fallback."""

    def test_scrape_dom_method_exists(self):
        """DouyinSearchAdapter must expose _scrape_dom."""
        adapter = DouyinSearchAdapter()
        assert callable(getattr(adapter, "_scrape_dom", None)), \
            "_scrape_dom method must exist on DouyinSearchAdapter"

    def test_xhr_empty_triggers_dom_fallback(self, monkeypatch):
        """search() returning 0 from XHR must call _scrape_dom and emit its cards."""
        adapter = DouyinSearchAdapter()

        dom_calls = {"n": 0}

        def fake_scrape_dom(page, target_count, on_card):
            dom_calls["n"] += 1
            cards = [
                VideoCard(
                    platform="douyin",
                    platform_video_id="7111111111111111111",
                    url="https://www.douyin.com/video/7111111111111111111",
                    title="dom-fallback-card-1",
                ),
                VideoCard(
                    platform="douyin",
                    platform_video_id="7222222222222222222",
                    url="https://www.douyin.com/video/7222222222222222222",
                    title="dom-fallback-card-2",
                ),
            ]
            for c in cards:
                on_card(c)
            return cards

        monkeypatch.setattr(adapter, "_scrape_dom", fake_scrape_dom, raising=False)

        # Mock out login check so we reach the scroll loop
        monkeypatch.setattr(
            "csm_core.mining.platforms.douyin_search.mining_browser.has_login_cookie",
            lambda platform: True,
        )

        # Build a mock page context manager: XHR listeners register but never fire
        mock_page = MagicMock()
        mock_page.url = "https://www.douyin.com/search/test?type=video"
        mock_page.__enter__ = lambda s: mock_page
        mock_page.__exit__ = MagicMock(return_value=False)

        # launched_page returns the mock page context
        monkeypatch.setattr(
            "csm_core.mining.platforms.douyin_search.mining_browser.launched_page",
            lambda platform: mock_page,
        )

        # Make _is_captcha_or_login always return False
        monkeypatch.setattr(
            "csm_core.mining.platforms.douyin_search._is_captcha_or_login",
            lambda page: False,
        )

        # Make scrolling instant (no sleep)
        monkeypatch.setattr("csm_core.mining.platforms.douyin_search.time.sleep", lambda _: None)

        # Make scroll loop exit immediately (emitted stays 0 but we cap scrolls at 30)
        # We patch page.evaluate to be a no-op and page.on to be a no-op so XHR never fires
        mock_page.on = MagicMock()
        mock_page.goto = MagicMock()
        mock_page.evaluate = MagicMock()

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
            f"DOM fallback should fire exactly once when XHR returns nothing, got {dom_calls['n']}"
        )
        assert len(cards_received) == 2, (
            f"Fallback DOM cards should be emitted via on_card, got {len(cards_received)}"
        )
        assert cards_received[0].platform_video_id == "7111111111111111111"
        assert outcome.status == "done"

    def test_dom_fallback_not_triggered_when_xhr_has_items(self, monkeypatch):
        """When XHR already collected items, _scrape_dom must NOT be called."""
        adapter = DouyinSearchAdapter()

        dom_calls = {"n": 0}

        def fake_scrape_dom(page, target_count, on_card):
            dom_calls["n"] += 1
            return []

        monkeypatch.setattr(adapter, "_scrape_dom", fake_scrape_dom, raising=False)

        monkeypatch.setattr(
            "csm_core.mining.platforms.douyin_search.mining_browser.has_login_cookie",
            lambda platform: True,
        )

        mock_page = MagicMock()
        mock_page.url = "https://www.douyin.com/search/test?type=video"
        mock_page.__enter__ = lambda s: mock_page
        mock_page.__exit__ = MagicMock(return_value=False)

        # Capture the response handler so we can fire it ourselves
        registered_handlers = {}

        def capture_on(event, handler):
            registered_handlers[event] = handler

        mock_page.on = capture_on
        mock_page.goto = MagicMock()
        mock_page.evaluate = MagicMock()

        monkeypatch.setattr(
            "csm_core.mining.platforms.douyin_search.mining_browser.launched_page",
            lambda platform: mock_page,
        )
        monkeypatch.setattr(
            "csm_core.mining.platforms.douyin_search._is_captcha_or_login",
            lambda page: False,
        )
        monkeypatch.setattr("csm_core.mining.platforms.douyin_search.time.sleep", lambda _: None)

        # After the goto, simulate an XHR response with 1 card
        real_goto = mock_page.goto

        def goto_with_xhr_response(url, **kwargs):
            # Fire the XHR response handler if registered
            handler = registered_handlers.get("response")
            if handler:
                mock_resp = MagicMock()
                mock_resp.url = "https://www.douyin.com/aweme/v1/web/general/search/single/?keyword=test"
                mock_resp.json.return_value = {
                    "status_code": 0,
                    "data": [{
                        "aweme_info": {
                            "aweme_id": "7999999999999999999",
                            "desc": "xhr-card",
                            "share_url": "https://www.douyin.com/video/7999999999999999999",
                            "author": {"nickname": "author1", "uid": "u1"},
                            "statistics": {"play_count": 100, "digg_count": 50},
                            "video": {"cover": {"url_list": []}, "duration": 30000},
                        }
                    }],
                }
                handler(mock_resp)

        mock_page.goto = goto_with_xhr_response

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
            "DOM fallback must NOT fire when XHR already produced items"
        )
        assert len(cards_received) == 1
        assert cards_received[0].platform_video_id == "7999999999999999999"
