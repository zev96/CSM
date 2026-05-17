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
