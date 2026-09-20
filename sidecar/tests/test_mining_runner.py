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
    """适配器以 done + error_message（如「第 2 页失败已停止」）收尾，TikHub 模式下
    → note 落到 progress，不被最终写抹掉（R7：TikHub 的 error_message 是面向用户
    的中文提示，允许落库；显式钉死 tikhub_api 模式，不依赖本机真实 settings.json）。"""

    class NotingAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            on_card(VideoCard(platform="bilibili", platform_video_id="B1", url="u1", title="t1"))
            return SearchOutcome(platform="bilibili", status="done", cards_emitted=1,
                                 error_message="第 2 页失败已停止：TikHub 限流")

    monkeypatch.setattr(
        "csm_core.config.get_config",
        lambda: SimpleNamespace(mining_data_source_mode="tikhub_api"),
    )
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: NotingAdapter())
    runner = MiningRunner(publish=lambda kind, payload: None)
    jid = ms.create_job("k", ["bilibili"], 50)
    runner.run(jid)
    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert prog["phase"] == "done" and prog["got"] == 1
    assert "第 2 页失败已停止" in (prog.get("note") or "")


def test_local_mode_never_persists_adapter_note(db, monkeypatch):
    """R7：本地（浏览器）路径的 error_message 是面向日志的英文内部诊断（如
    「no SESSDATA in bilibili profile」/ 带 URL+keyword 的异常文本），绝不能
    落到 progress.note 被 UI/DB 看见——local 模式下 note 必须是空字符串，
    与改动前的 base 行为逐字节一致。"""

    class NotingAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            on_card(VideoCard(platform="bilibili", platform_video_id="B1", url="u1", title="t1"))
            return SearchOutcome(platform="bilibili", status="done", cards_emitted=1,
                                 error_message="no SESSDATA in bilibili profile")

    monkeypatch.setattr(
        "csm_core.config.get_config",
        lambda: SimpleNamespace(mining_data_source_mode="local"),
    )
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: NotingAdapter())
    runner = MiningRunner(publish=lambda kind, payload: None)
    jid = ms.create_job("k", ["bilibili"], 50)
    runner.run(jid)
    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert prog["phase"] == "done" and prog["got"] == 1
    assert prog.get("note") == "", (
        f"local-mode adapter note must never be persisted, got {prog.get('note')!r}"
    )


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


# ── R5: _on_progress throttle state must be bound per-closure, not per-name ─

def test_on_progress_closure_binds_its_own_throttle_state(db, monkeypatch):
    """镜像 R3 的 _on_card 闭包测试，换成 _on_progress 的节流状态
    (last_pub_time / last_pub_count)。A（bilibili）先真实调用一次自己的
    on_progress（phase=done，正常收尾，与闭包 bug 无关），再把 on_progress
    存进共享槽位。B（kuaishou）先用槽位里 A 的 on_progress 重放一条
    got=99 的 scrolling 进度，然后才开始发自己真正的 scrolling 进度
    (got=1..6)。

    如果 _on_progress 对 last_pub_time/last_pub_count 是晚绑定闭包（引用
    run() 作用域里的同名变量而不是把列表对象绑成默认参数）——B 平台的循环
    体这时已经为 B 新建了这两个节流状态列表,于是 A 的重放会被错误地写进
    B 自己的节流状态里,把基线拉到 got=99、时间戳拉到刚刚。随后 B 自己
    真正的 1..6 进度全部因为「count 差距是负的 + 时间差距几乎是 0」被节流
    吞掉，一条都发不出来。修复后 A 的 on_progress 操作的是 A 自己在定义时
    捕获的列表对象，B 的节流状态分毫不动,B 的首条 scrolling 进度按时间阈值
    正常发布。"""
    slot: dict = {}

    class StoringAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            slot["on_progress"] = on_progress
            on_progress(ProgressUpdate(platform=self.platform, phase="done", got=1, target=target_count))
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=0)

    class ReplayThenScrollAdapter:
        platform = "kuaishou"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            # 用 A 存下的 on_progress 重放一条大 got 值的 scrolling 进度——
            # 如果闭包晚绑定，这一下会污染 B 自己的节流基线。
            slot["on_progress"](ProgressUpdate(platform="bilibili", phase="scrolling", got=99, target=target_count))
            for i in range(1, 7):
                on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=i, target=target_count))
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=6)

    adapters = {"bilibili": StoringAdapter(), "kuaishou": ReplayThenScrollAdapter()}
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: adapters[p])

    events = []
    runner = MiningRunner(publish=lambda kind, payload: events.append((kind, payload)))
    jid = ms.create_job("k", ["bilibili", "kuaishou"], 50)
    runner.run(jid)

    ks_scrolling = [
        e[1] for e in events
        if e[0] == "job.progress" and e[1]["platform"] == "kuaishou" and e[1]["phase"] == "scrolling"
    ]
    assert ks_scrolling, (
        "kuaishou 自己的 scrolling 进度必须能发布出来——节流基线不该被 A 的重放污染"
    )
    assert any(p["got"] == 1 for p in ks_scrolling), (
        "kuaishou 的首条 scrolling 进度应按时间阈值发布（说明它自己的 last_pub_time "
        "起点还是 0.0，没有被 A 重放时留下的近期时间戳污染）"
    )


# ── R6: final "done" note truncation must match the exception-path cap ─────

def test_final_done_note_truncated_to_200_chars(db, monkeypatch):
    """适配器以 done + 超长 error_message 收尾——最终写落的 note 必须和异常
    路径（note=str(e)[:200]）同一截断口径，不能整段原样写进去。"""

    class VerboseAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            return SearchOutcome(
                platform=self.platform, status="done", cards_emitted=0,
                error_message="警" * 500,
            )

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: VerboseAdapter())
    runner = MiningRunner(publish=lambda kind, payload: None)
    jid = ms.create_job("k", ["bilibili"], 50)
    runner.run(jid)

    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert len(prog.get("note") or "") <= 200


# ── D1: effective target must respect the TikHub per-platform hard cap ─────

def test_effective_target_capped_under_tikhub_mode(db, monkeypatch):
    """job target=200 但数据源是 tikhub_api → 适配器实际只应该收到 HARD_CAP(80)，
    最终 progress.target 也必须是 80，否则一个已经拿满 80 条、真正跑完的 job
    在 UI 进度条上会停在 80/200=40%，看起来像卡住/失败。"""
    from csm_core.mining.platforms.tikhub_search import HARD_CAP

    monkeypatch.setattr(
        "csm_core.config.get_config",
        lambda: SimpleNamespace(mining_data_source_mode="tikhub_api"),
    )
    received: dict = {}

    class CapReportingAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            received["target_count"] = target_count
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=0)

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: CapReportingAdapter())
    jid = ms.create_job("k", ["bilibili"], 200)
    runner = MiningRunner(publish=lambda kind, payload: None)
    runner.run(jid)

    assert received["target_count"] == HARD_CAP == 80
    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert prog["target"] == 80


def test_effective_target_uncapped_under_local_mode(db, monkeypatch):
    """本地（浏览器）路径没有 TikHub 硬顶——job target=200 应原样传给适配器，
    最终 progress.target 也应是 200。"""
    monkeypatch.setattr(
        "csm_core.config.get_config",
        lambda: SimpleNamespace(mining_data_source_mode="local"),
    )
    received: dict = {}

    class CapReportingAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            received["target_count"] = target_count
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=0)

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: CapReportingAdapter())
    jid = ms.create_job("k", ["bilibili"], 200)
    runner = MiningRunner(publish=lambda kind, payload: None)
    runner.run(jid)

    assert received["target_count"] == 200
    prog = ms.get_job(jid)["progress"]["bilibili"]
    assert prog["target"] == 200


# ── L1: job-local balance short-circuit ─────────────────────────────────────

@pytest.fixture
def reset_tikhub_latch():
    """进程级余额闩是全局单例——测试前后都清一次，防串到其它测试。"""
    from csm_core.monitor.tikhub.client import reset_balance_latch
    reset_balance_latch()
    yield
    reset_balance_latch()


def test_balance_402_on_platform1_short_circuits_platform_2_and_3(db, monkeypatch, reset_tikhub_latch):
    """platform 1 撞 402（自己置进程级闩）并以 failed 收尾 → platform 2/3 的
    适配器一次都不应该被调用（未发请求），progress 直接写 failed + 短路 note。"""
    from csm_core.monitor.tikhub.client import _trip_balance_latch

    monkeypatch.setattr(
        "csm_core.config.get_config",
        lambda: SimpleNamespace(mining_data_source_mode="tikhub_api"),
    )
    called: list[str] = []

    class TrippingAdapter:
        def __init__(self, platform):
            self.platform = platform

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            called.append(self.platform)
            _trip_balance_latch()
            return SearchOutcome(platform=self.platform, status="failed", cards_emitted=0,
                                 error_message="TikHub 余额不足")

    class NeverCalledAdapter:
        def __init__(self, platform):
            self.platform = platform

        def search(self, *a, **kw):
            called.append(self.platform)
            raise AssertionError(f"{self.platform} adapter must never be called after latch trips")

    adapters = {
        "bilibili": TrippingAdapter("bilibili"),
        "kuaishou": NeverCalledAdapter("kuaishou"),
        "douyin": NeverCalledAdapter("douyin"),
    }
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: adapters[p])

    jid = ms.create_job("k", ["bilibili", "kuaishou", "douyin"], 50)
    events = []
    runner = MiningRunner(publish=lambda kind, payload: events.append((kind, payload)))
    runner.run(jid)

    assert called == ["bilibili"], f"only bilibili's adapter should ever run, got {called}"

    progress = ms.get_job(jid)["progress"]
    for p in ("kuaishou", "douyin"):
        assert progress[p]["phase"] == "failed"
        assert progress[p]["got"] == 0
        assert "短路" in (progress[p].get("note") or ""), progress[p]

    short_circuit_events = [
        e for e in events
        if e[0] == "job.platform_done" and e[1]["platform"] in ("kuaishou", "douyin")
    ]
    assert len(short_circuit_events) == 2
    for _, payload in short_circuit_events:
        assert payload["status"] == "failed"
        assert payload["count"] == 0


def test_stale_process_latch_does_not_block_a_fresh_job(db, monkeypatch, reset_tikhub_latch):
    """进程级闩在任务开始之前就已经是 True（模拟：monitor 调度器 60s 前留下的一次
    陈旧 402，还没到下一次重置窗口）——这个新任务的 platform 1 仍然必须真正发起
    请求：job_latched 是任务本地状态，循环开始时永远是 False，不看进场时的
    进程闩状态。"""
    from csm_core.monitor.tikhub.client import _trip_balance_latch

    monkeypatch.setattr(
        "csm_core.config.get_config",
        lambda: SimpleNamespace(mining_data_source_mode="tikhub_api"),
    )
    _trip_balance_latch()  # simulate a stale monitor-side 402 latched before this job started

    called: list[str] = []

    class CalledAdapter:
        platform = "bilibili"

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            called.append(self.platform)
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=0)

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: CalledAdapter())
    jid = ms.create_job("k", ["bilibili"], 50)
    runner = MiningRunner(publish=lambda kind, payload: None)
    runner.run(jid)

    assert called == ["bilibili"], "platform 1's adapter must still be called despite a stale pre-existing latch"


def test_local_mode_ignores_balance_latch_entirely(db, monkeypatch, reset_tikhub_latch):
    """local（浏览器）模式下，即便进程级余额闩被置位，也完全不应该短路——余额闩
    是 TikHub 付费路径专属概念，跟本地浏览器采集无关。"""
    from csm_core.monitor.tikhub.client import _trip_balance_latch

    monkeypatch.setattr(
        "csm_core.config.get_config",
        lambda: SimpleNamespace(mining_data_source_mode="local"),
    )
    _trip_balance_latch()

    called: list[str] = []

    class CalledAdapter:
        def __init__(self, platform):
            self.platform = platform

        def search(self, keyword, target_count, on_card, on_progress, cancel_event,
                   max_attempts=None, filters=None):
            called.append(self.platform)
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=0)

    adapters = {"bilibili": CalledAdapter("bilibili"), "kuaishou": CalledAdapter("kuaishou")}
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: adapters[p])

    jid = ms.create_job("k", ["bilibili", "kuaishou"], 50)
    runner = MiningRunner(publish=lambda kind, payload: None)
    runner.run(jid)

    assert called == ["bilibili", "kuaishou"], f"local mode must ignore the balance latch entirely, got {called}"


# ── 取消 / 去重跳过 的事件与 note 口径 ──────────────────────────────────────
def test_runner_cancel_publishes_platform_done_for_skipped_platforms(db, monkeypatch):
    """取消后被跳过的平台也要推 platform_done(cancelled)：前端 activeJob.progress 只靠
    事件更新，不推的话这些平台在托盘里会一直显示 "0/N 抓取中"。"""
    events = []
    runner = MiningRunner(publish=lambda kind, payload: events.append((kind, payload)))
    monkeypatch.setattr(
        "csm_core.mining.runner.get_adapter",
        lambda p, m=None: FakeAdapter(p, []),
    )
    jid = ms.create_job("k", ["bilibili", "douyin"], 50)
    runner.register_cancel_event(jid).set()
    runner.run(jid)

    plat_done = [(p["platform"], p["status"]) for k, p in events if k == "job.platform_done"]
    assert plat_done == [("bilibili", "cancelled"), ("douyin", "cancelled")]
    assert [k for k, _ in events][-1] == "job.finished"
    job = ms.get_job(jid)
    assert all(p["phase"] == "cancelled" for p in job["progress"].values())


def test_runner_dedup_skips_are_counted_in_note_not_progress(db, monkeypatch):
    """用户设 10 条、其中 3 条已在库/已评论 → 进度仍按适配器交付数走到 10/10（不会卡在 7/10），
    跳过数写进 note 让用户知道列表里为什么少了。"""
    events = []
    runner = MiningRunner(publish=lambda kind, payload: events.append((kind, payload)))
    monkeypatch.setattr("csm_core.mining.runner._data_source_mode", lambda cfg=None: "local")
    earlier = [
        VideoCard(platform="bilibili", platform_video_id=f"B{i}", url=f"http://b.com/v/B{i}", title=f"t{i}")
        for i in range(3)
    ]
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: FakeAdapter(p, earlier))
    runner.run(ms.create_job("k", ["bilibili"], 50))

    later = earlier + [
        VideoCard(platform="bilibili", platform_video_id=f"B{i}", url=f"http://b.com/v/B{i}", title=f"t{i}")
        for i in range(3, 10)
    ]
    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p, m=None: FakeAdapter(p, later))
    jid = ms.create_job("k", ["bilibili"], 10)
    runner.run(jid)

    job = ms.get_job(jid)
    prog = job["progress"]["bilibili"]
    assert prog["phase"] == "done"
    assert prog["got"] == 10 and prog["target"] == 10
    assert "3 条已在监控/已采集过" in prog["note"]
    # 只有 7 条新视频挂到这个 job 上
    conn = ms.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM video_source_keywords WHERE job_id=?", (jid,)).fetchone()[0]
    assert n == 7
