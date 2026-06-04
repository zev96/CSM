"""Runner integration test with a fake adapter — no real browser."""
import threading
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.mining.models import (
    ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.runner import MiningRunner
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    if hasattr(monitor_storage._local, "conn"):
        delattr(monitor_storage._local, "conn")
    monitor_storage.init_db(tmp_path / "monitor.db")
    yield


class FakeAdapter:
    def __init__(self, platform, cards, status="done"):
        self.platform = platform
        self.cards = cards
        self.status = status

    def search(self, keyword, target_count, on_card, on_progress, cancel_event):
        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        for c in self.cards:
            if cancel_event.is_set():
                return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=0)
            on_card(c)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=len(self.cards), target=target_count))
        return SearchOutcome(platform=self.platform, status=self.status, cards_emitted=len(self.cards))


def test_runner_two_platforms_done(db, monkeypatch):
    events: list[tuple] = []

    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    fake_b = FakeAdapter("bilibili", [
        VideoCard(platform="bilibili", platform_video_id="B1", url="u1", title="t1"),
        VideoCard(platform="bilibili", platform_video_id="B2", url="u2", title="t2"),
    ])
    fake_k = FakeAdapter("kuaishou", [
        VideoCard(platform="kuaishou", platform_video_id="K1", url="u3", title="t3"),
    ])

    def fake_get_adapter(platform):
        return {"bilibili": fake_b, "kuaishou": fake_k}[platform]

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", fake_get_adapter)

    jid = ms.create_job("k", ["bilibili", "kuaishou"], 50)
    runner.run(jid)

    job = ms.get_job(jid)
    assert job["status"] == "done"
    rows, total = ms.list_videos(commented="all")
    assert total == 3
    kinds = [e[0] for e in events]
    assert "job.started" in kinds
    assert "job.finished" in kinds
    # platform_done events for both platforms
    plat_done = [e for e in events if e[0] == "job.platform_done"]
    assert len(plat_done) == 2


def test_runner_partial_when_one_needs_login(db, monkeypatch):
    events = []
    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    good = FakeAdapter("bilibili", [
        VideoCard(platform="bilibili", platform_video_id="B1", url="u1"),
    ])
    bad = FakeAdapter("douyin", [], status="needs_login")

    def fake_get_adapter(platform):
        return {"bilibili": good, "douyin": bad}[platform]

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", fake_get_adapter)

    jid = ms.create_job("k", ["bilibili", "douyin"], 50)
    runner.run(jid)
    job = ms.get_job(jid)
    assert job["status"] == "partial_done"
    rows, total = ms.list_videos(commented="all")
    assert total == 1  # bilibili's one card persisted


def test_runner_prefilter_excludes_brand_seeded(db, monkeypatch):
    """Brand-keyword job: videos with >=3 brand-hit comments get excluded=1."""
    events = []

    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    cards = [
        VideoCard(platform="bilibili", platform_video_id="B1", url="http://b.com/v/B1", title="t1"),
        VideoCard(platform="bilibili", platform_video_id="B2", url="http://b.com/v/B2", title="t2"),
        VideoCard(platform="bilibili", platform_video_id="B3", url="http://b.com/v/B3", title="t3"),
    ]
    fake_b = FakeAdapter("bilibili", cards)

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p: fake_b)

    # B1: 3 comments with 石头 → should be excluded
    # B2: 1 comment with 石头 → kept, brand_comment_hits=1
    # B3: 0 comments → kept, brand_comment_hits=0
    def fake_fetch(platform, video_url, limit=30):
        if "B1" in video_url:
            return ["石头很好", "石头真棒", "石头不错"]
        if "B2" in video_url:
            return ["石头还行", "其他内容"]
        return ["无关评论", "another"]

    monkeypatch.setattr("csm_core.mining.runner.fetch_video_comment_texts", fake_fetch)

    jid = ms.create_job("keyword", ["bilibili"], 50, brand_keywords=["石头"])
    runner.run(jid)

    # Job must still end as "done" (prefilter must restore done phase)
    job = ms.get_job(jid)
    assert job["status"] == "done", f"expected done, got {job['status']}"

    # Query videos table directly — list_videos hides excluded=1
    conn = ms.get_conn()
    rows = conn.execute(
        "SELECT platform_video_id, excluded, exclude_reason, brand_comment_hits "
        "FROM videos ORDER BY platform_video_id"
    ).fetchall()
    row_by_id = {r["platform_video_id"]: dict(r) for r in rows}

    # B1: excluded by brand detection
    assert row_by_id["B1"]["excluded"] == 1, "B1 should be excluded"
    assert row_by_id["B1"]["exclude_reason"] == "brand_seeded"
    assert row_by_id["B1"]["brand_comment_hits"] >= 3

    # B2: kept, but hits recorded
    assert row_by_id["B2"]["excluded"] == 0, "B2 should NOT be excluded"
    assert row_by_id["B2"]["brand_comment_hits"] == 1

    # B3: kept, hits=0
    assert row_by_id["B3"]["excluded"] == 0, "B3 should NOT be excluded"
    assert row_by_id["B3"]["brand_comment_hits"] == 0

    # Platform must end on "done" so finalize counts success
    plat_done = [e for e in events if e[0] == "job.platform_done"]
    assert len(plat_done) == 1
    assert plat_done[0][1]["status"] == "done"


def test_runner_no_brand_keywords_skips_prefilter(db, monkeypatch):
    """Without brand_keywords the prefilter pass is skipped entirely."""
    events = []

    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    cards = [
        VideoCard(platform="bilibili", platform_video_id="B1", url="http://b.com/v/B1", title="t1"),
    ]
    fake_b = FakeAdapter("bilibili", cards)
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p: fake_b)

    fetch_calls = []

    def fake_fetch(platform, video_url, limit=30):
        fetch_calls.append((platform, video_url))
        return []

    monkeypatch.setattr("csm_core.mining.runner.fetch_video_comment_texts", fake_fetch)

    # No brand_keywords (default empty)
    jid = ms.create_job("keyword", ["bilibili"], 50)
    runner.run(jid)

    assert fetch_calls == [], "fetch_video_comment_texts must not be called without brand_keywords"

    # All videos still excluded=0
    conn = ms.get_conn()
    rows = conn.execute("SELECT excluded FROM videos").fetchall()
    assert all(r["excluded"] == 0 for r in rows)

    job = ms.get_job(jid)
    assert job["status"] == "done"


def test_runner_prefilter_fetch_failure_leaves_null(db, monkeypatch):
    """Empty fetch (failure) must leave brand_comment_hits as NULL, not 0.

    fail-open spec: when fetch_video_comment_texts returns [] we cannot
    distinguish 'no comments exist' from 'fetch failed', so we must NOT
    write brand_comment_hits=0 (which would mean 'checked, 0 brand hits').
    The column must stay NULL (= not yet checked / unknown).
    """
    events = []

    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    cards = [
        VideoCard(platform="bilibili", platform_video_id="X1", url="http://b.com/v/X1", title="t1"),
    ]
    fake_b = FakeAdapter("bilibili", cards)
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p: fake_b)

    # Always return [] — simulates a fetch failure
    def fake_fetch(platform, video_url, limit=30):
        return []

    monkeypatch.setattr("csm_core.mining.runner.fetch_video_comment_texts", fake_fetch)

    jid = ms.create_job("keyword", ["bilibili"], 50, brand_keywords=["石头"])
    runner.run(jid)

    conn = ms.get_conn()
    row = conn.execute(
        "SELECT brand_comment_hits, excluded FROM videos WHERE platform_video_id = 'X1'"
    ).fetchone()

    assert row is not None, "video X1 must be persisted"
    assert row["brand_comment_hits"] is None, (
        f"expected brand_comment_hits=NULL (not checked) but got {row['brand_comment_hits']!r}"
    )
    assert row["excluded"] == 0, "fetch failure must not exclude the video"


def test_runner_cancel_mid_job(db, monkeypatch):
    events = []
    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)

    # Adapter that yields 5 cards but checks cancel between each.
    class SlowAdapter:
        platform = "bilibili"
        def search(self, keyword, target_count, on_card, on_progress, cancel_event):
            emitted = 0
            for i in range(5):
                if cancel_event.is_set():
                    return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
                on_card(VideoCard(platform="bilibili", platform_video_id=f"B{i}", url="u"))
                emitted += 1
            on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p: SlowAdapter())
    jid = ms.create_job("k", ["bilibili"], 50)
    cancel_event = runner.register_cancel_event(jid)
    cancel_event.set()  # cancel before run
    runner.run(jid)
    rows, total = ms.list_videos(commented="all")
    assert total == 0  # nothing emitted
