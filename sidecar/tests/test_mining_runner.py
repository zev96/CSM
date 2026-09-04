"""Runner integration test with a fake adapter — no real browser."""
import threading
from pathlib import Path
from types import SimpleNamespace

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
        self.seen_filters = None

    def search(self, keyword, target_count, on_card, on_progress, cancel_event,
               max_attempts=None, filters=None):
        self.seen_filters = filters
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

    def fake_get_adapter(platform, mode=None):
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

    def fake_get_adapter(platform, mode=None):
        return {"bilibili": good, "douyin": bad}[platform]

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", fake_get_adapter)

    jid = ms.create_job("k", ["bilibili", "douyin"], 50)
    runner.run(jid)
    job = ms.get_job(jid)
    assert job["status"] == "partial_done"
    rows, total = ms.list_videos(commented="all")
    assert total == 1  # bilibili's one card persisted


def _comments(*texts):
    """fetch_video_comments 返回形状：[{text, likes, author}, ...]。"""
    return [{"text": t, "likes": None, "author": ""} for t in texts]


def test_runner_prefilter_excludes_brand_seeded(db, monkeypatch):
    """Brand-keyword job: videos with >=threshold(1) brand-hit comments get excluded=1."""
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

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: fake_b)
    # 钉死 (top_n, threshold)，与用户机器上的 settings.json 解耦。
    monkeypatch.setattr("csm_core.mining.runner._prefilter_params", lambda cfg=None: (20, 1))

    # 阈值=1（2026-08-31 拍板：命中 1 条即排除）：
    # B1: 3 comments with 石头 → excluded, hits=3
    # B2: 1 comment with 石头 → excluded, hits=1
    # B3: 0 brand comments → kept, brand_comment_hits=0
    def fake_fetch(platform, video_url, limit=20):
        if "B1" in video_url:
            return _comments("石头很好", "石头真棒", "石头不错")
        if "B2" in video_url:
            return _comments("石头还行", "其他内容")
        return _comments("无关评论", "another")

    monkeypatch.setattr("csm_core.mining.runner.fetch_video_comments", fake_fetch)

    jid = ms.create_job("keyword", ["bilibili"], 50, brand_keywords=["石头"])
    runner.run(jid)

    # Job must still end as "done" (prefilter must restore done phase)
    job = ms.get_job(jid)
    assert job["status"] == "done", f"expected done, got {job['status']}"

    # Query videos table directly — list_videos hides excluded=1
    conn = ms.get_conn()
    rows = conn.execute(
        "SELECT platform_video_id, excluded, exclude_reason, brand_comment_hits, top_comments_json "
        "FROM videos ORDER BY platform_video_id"
    ).fetchall()
    row_by_id = {r["platform_video_id"]: dict(r) for r in rows}

    # B1: excluded by brand detection
    assert row_by_id["B1"]["excluded"] == 1, "B1 should be excluded"
    assert row_by_id["B1"]["exclude_reason"] == "brand_seeded"
    assert row_by_id["B1"]["brand_comment_hits"] >= 3

    # B2: threshold=1 → 命中 1 条也排除
    assert row_by_id["B2"]["excluded"] == 1, "B2 should be excluded (threshold=1)"
    assert row_by_id["B2"]["brand_comment_hits"] == 1

    # B3: kept, hits=0
    assert row_by_id["B3"]["excluded"] == 0, "B3 should NOT be excluded"
    assert row_by_id["B3"]["brand_comment_hits"] == 0

    # 热评快照持久化：检查过的视频（含被排除的）都应有 top_comments_json
    for vid in ("B1", "B2", "B3"):
        assert row_by_id[vid]["top_comments_json"], f"{vid} should have top_comments snapshot"

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
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: fake_b)

    fetch_calls = []

    def fake_fetch(platform, video_url, limit=20):
        fetch_calls.append((platform, video_url))
        return []

    monkeypatch.setattr("csm_core.mining.runner.fetch_video_comments", fake_fetch)

    # No brand_keywords (default empty)
    jid = ms.create_job("keyword", ["bilibili"], 50)
    runner.run(jid)

    assert fetch_calls == [], "fetch_video_comments must not be called without brand_keywords"

    # All videos still excluded=0
    conn = ms.get_conn()
    rows = conn.execute("SELECT excluded FROM videos").fetchall()
    assert all(r["excluded"] == 0 for r in rows)

    job = ms.get_job(jid)
    assert job["status"] == "done"


def test_runner_prefilter_fetch_failure_leaves_null(db, monkeypatch):
    """Empty fetch (failure) must leave brand_comment_hits as NULL, not 0.

    fail-open spec: when fetch_video_comments returns [] we cannot
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
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: fake_b)

    # Always return [] — simulates a fetch failure
    def fake_fetch(platform, video_url, limit=20):
        return []

    monkeypatch.setattr("csm_core.mining.runner.fetch_video_comments", fake_fetch)

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
        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            emitted = 0
            for i in range(5):
                if cancel_event.is_set():
                    return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
                on_card(VideoCard(platform="bilibili", platform_video_id=f"B{i}", url="u"))
                emitted += 1
            on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: SlowAdapter())
    jid = ms.create_job("k", ["bilibili"], 50)
    cancel_event = runner.register_cancel_event(jid)
    cancel_event.set()  # cancel before run
    runner.run(jid)
    rows, total = ms.list_videos(commented="all")
    assert total == 0  # nothing emitted


def test_done_outcome_note_is_persisted(db, monkeypatch):
    """适配器以 done + error_message（如「第 2 页失败已停止」）收尾 → note 落到 progress，不被最终写抹掉。"""

    class NotingAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            on_card(VideoCard(platform="bilibili", platform_video_id="B1", url="u1", title="t1"))
            return SearchOutcome(platform="bilibili", status="done", cards_emitted=1,
                                 error_message="第 2 页失败已停止：TikHub 限流")

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: NotingAdapter())
    runner = MiningRunner(publish=lambda kind, payload: None)
    jid = ms.create_job("k", ["bilibili"], 50)
    runner.run(jid)
    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert prog["phase"] == "done" and prog["got"] == 1
    assert "第 2 页失败已停止" in (prog.get("note") or "")


def test_adapter_exception_reports_cards_already_emitted(db, monkeypatch):
    """适配器在吐出 2 张卡后抛异常 → phase=failed 但 got=2（不再写死 0）。"""

    class ExplodingAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            on_card(VideoCard(platform="bilibili", platform_video_id="B1", url="u1", title="t1"))
            on_card(VideoCard(platform="bilibili", platform_video_id="B2", url="u2", title="t2"))
            raise RuntimeError("boom")

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: ExplodingAdapter())
    events = []
    runner = MiningRunner(publish=lambda kind, payload: events.append((kind, payload)))
    jid = ms.create_job("k", ["bilibili"], 50)
    runner.run(jid)
    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert prog["phase"] == "failed" and prog["got"] == 2
    done_evt = [p for k, p in events if k == "job.platform_done"][-1]
    assert done_evt["status"] == "failed" and done_evt["count"] == 2


# ── R1: progress-publish throttle state must reset between platforms ───────

class ScrollingAdapter:
    """每张卡都紧跟一条 phase="scrolling" 的 on_progress —— 用来验证发布节流
    状态（last_pub_count/last_pub_time）在平台之间被重置，而不是从上一个平台
    带着"已经发布过"的残留计数进入下一个平台，导致下一个平台的早期进度被
    节流吞掉、一条都发不出来。"""

    def __init__(self, platform, n=6):
        self.platform = platform
        self.n = n

    def search(self, keyword, target_count, on_card, on_progress, cancel_event,
               max_attempts=None, filters=None):
        for i in range(1, self.n + 1):
            on_card(VideoCard(platform=self.platform, platform_video_id=f"{self.platform}{i}", url=f"u{i}"))
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=i, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=self.n)


def test_progress_events_published_for_every_platform(db, monkeypatch):
    """两个平台各自吐 6 张卡、每张卡后带一条 scrolling 进度。PUBLISH_EVERY_N_CARDS=5
    时第一个平台理应在 got=5 时发布一条；如果节流状态没有按平台重置，第二个
    平台会继承第一个平台已经"发过"的计数基线，导致它的 6 条 scrolling 进度
    一条都发不出来（此前的真实 bug：只有第一个平台能看到滚动进度）。"""
    events = []

    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    adapters = {"bilibili": ScrollingAdapter("bilibili"), "kuaishou": ScrollingAdapter("kuaishou")}
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: adapters[p])

    jid = ms.create_job("k", ["bilibili", "kuaishou"], 50)
    runner.run(jid)

    scrolling_platforms = {
        e[1]["platform"] for e in events if e[0] == "job.progress" and e[1]["phase"] == "scrolling"
    }
    assert scrolling_platforms == {"bilibili", "kuaishou"}, (
        f"expected scrolling progress from both platforms, got {scrolling_platforms}"
    )


# ── R2: got must count every card the adapter handed us, incl. dedup skips ─

def test_got_counts_fetched_cards_including_dedup_skips(db, monkeypatch):
    """预先插入一条"已存在"的视频，让适配器再次吐出它 + 1 张新卡后抛异常。
    got 的语义是"适配器交给我们的卡数"（与 adapter 自己的 cards_emitted /
    在制 got 同一口径），不是"成功入库的卡数"——去重跳过的那张卡也要计入，
    否则采集进度看起来比实际吞吐慢一大截。同时确认真正落库/挂到本 job 的
    视频只有 1 条（被去重的那条压根没链接到这个 job）。"""
    conn = ms.get_conn()
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) VALUES(?,?,?)",
        ("bilibili", "DUP1", "http://b.com/v/DUP1"),
    )
    conn.commit()

    class DupThenNewAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            on_card(VideoCard(platform="bilibili", platform_video_id="DUP1", url="http://b.com/v/DUP1", title="dup"))
            on_card(VideoCard(platform="bilibili", platform_video_id="NEW1", url="http://b.com/v/NEW1", title="new"))
            raise RuntimeError("boom")

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: DupThenNewAdapter())
    events = []
    runner = MiningRunner(publish=lambda kind, payload: events.append((kind, payload)))
    jid = ms.create_job("k", ["bilibili"], 50)
    runner.run(jid)

    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert prog["phase"] == "failed" and prog["got"] == 2, f"expected got=2 (fetched), got {prog}"

    done_evt = [p for k, p in events if k == "job.platform_done"][-1]
    assert done_evt["count"] == 2

    linked = conn.execute(
        "SELECT COUNT(*) AS c FROM video_source_keywords WHERE job_id = ?", (jid,)
    ).fetchone()["c"]
    assert linked == 1, "only the genuinely new card should be linked to this job"


# ── R3: _on_card closures must bind their OWN platform's emitted counter ───

def test_on_card_closure_binds_its_own_platform_counter(db, monkeypatch):
    """A（bilibili）先真实调用一次自己的 on_card（自身计数=1，走 outcome.cards_emitted
    的正常路径,与闭包 bug 无关，纯粹确认 A 正常跑完），再把 on_card 存进一个共享
    槽位留给后面用。B（kuaishou）自己一次都不调用 on_card，只是把 A 存的
    on_card 拿出来对一张 bilibili 平台的卡重放一次，然后抛异常。

    B 的 except 分支上报的 got 来自 run() 里当前平台对应的 emitted 影子计数器
    ——如果 _on_card 闭包对 emitted 是"晚绑定"（旧 bug：闭包体内直接引用外层
    变量名,而不是把列表对象绑成默认参数）,重放调用发生时 run() 作用域里的
    emitted 名字已经指向 B 平台新建的列表,于是这次重放会被错误地记到 B 头上，
    B 的 got 变成 1（明明 B 自己一次都没有收到过卡）。修复后重放操作的是 A
    自己在定义时捕获到的列表对象,B 的计数器分毫不动,B 的 got 正确地是 0。"""
    slot: dict = {}

    class StoringAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            on_card(VideoCard(platform="bilibili", platform_video_id="A-own", url="ua"))
            slot["on_card"] = on_card
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=1)

    class ReplayThenRaiseAdapter:
        platform = "kuaishou"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            slot["on_card"](VideoCard(platform="bilibili", platform_video_id="A-replayed", url="ub"))
            raise RuntimeError("boom")

    adapters = {"bilibili": StoringAdapter(), "kuaishou": ReplayThenRaiseAdapter()}
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: adapters[p])

    jid = ms.create_job("k", ["bilibili", "kuaishou"], 50)
    runner = MiningRunner(publish=lambda kind, payload: None)
    runner.run(jid)

    progress = ms.get_job(jid)["progress"]
    assert progress["bilibili"]["got"] == 1
    assert progress["kuaishou"]["phase"] == "failed"
    assert progress["kuaishou"]["got"] == 0, (
        "kuaishou never called its own on_card — replaying bilibili's stored "
        "callback must not credit kuaishou's shadow counter"
    )


# ── R4: data-source mode is resolved once per job, not once per platform ───

def test_mode_resolved_once_per_job(db, monkeypatch):
    """config stub 第一次调用返回 'local'，之后每次都返回 'tikhub_api' ——
    如果 runner 在每个平台的循环体内各读一次配置，两个平台会分别拿到
    'local' 和 'tikhub_api'（同一个任务内用了两种不同数据源，语义上不该
    发生：分派层设计上是"每个任务开始时读一次，任务内三平台同一数据源"）。"""
    call_count = {"n": 0}

    def fake_get_config():
        call_count["n"] += 1
        mode = "local" if call_count["n"] == 1 else "tikhub_api"
        return SimpleNamespace(mining_data_source_mode=mode)

    monkeypatch.setattr("csm_core.config.get_config", fake_get_config)

    recorded = []

    def fake_get_adapter(platform, mode=None):
        recorded.append((platform, mode))
        return FakeAdapter(platform, [])

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", fake_get_adapter)

    jid = ms.create_job("k", ["bilibili", "kuaishou"], 50)
    runner = MiningRunner(publish=lambda kind, payload: None)
    runner.run(jid)

    assert recorded == [("bilibili", "local"), ("kuaishou", "local")]
    assert call_count["n"] == 1, f"config.get_config should be read exactly once per job, called {call_count['n']}x"
