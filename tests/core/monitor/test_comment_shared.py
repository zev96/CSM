"""SharedCommentStore —— 同视频多评论任务共享一次评论区抓取。

背景：任务身份键改为 (type, target_url, 评论文本) 后，同一条视频下可有
N 条评论任务。派发是逐任务的，没有共享层时同一视频的评论区每轮被完整
抓 N 次（本地模式软封风险、TikHub 模式每页计费 ×N）。共享层语义：

  - 单飞：同 key 并发只放行一个抓取，其余复用结果；
  - served-set：每任务对同一份快照最多消费一次（同任务重跑=强制刷新）；
  - 失败负缓存：组内统一报同一失败原因，不连环重试；
  - 截短快照防错位：因命中即停截短的快照，对「在里面找不到自己评论」的
    任务不可复用（必须自己重抓，绝不误报"评论不在"）。
"""
from __future__ import annotations

import threading
import time

import pytest

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms._comment_shared import (
    CommentSnapshot,
    SharedCommentStore,
)


def _comments(n: int, *, plant: dict[int, str] | None = None) -> list[dict]:
    """构造 n 条带全局 rank 的假评论；plant={rank: text} 在指定位置放目标文本。"""
    plant = plant or {}
    return [
        {"rank": i + 1, "text": plant.get(i + 1, f"路人评论 {i + 1}"), "author": "u", "likes": 0}
        for i in range(n)
    ]


def _snap(n: int = 50, *, depth: int = 150, plant: dict[int, str] | None = None,
          exhausted: bool = False, early: bool = False) -> CommentSnapshot:
    return CommentSnapshot(
        comments=_comments(n, plant=plant), depth=depth,
        exhausted=exhausted, early_stopped=early,
    )


KEY = ("local", "kuaishou_comment", "photoX")


class TestSharedCommentStore:
    def test_second_task_reuses_snapshot(self):
        store = SharedCommentStore()
        calls = []

        def do_fetch():
            calls.append(1)
            return _snap(50, plant={7: "评论甲"}, exhausted=True)

        s1 = store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                       depth=150, cancel_token=None, do_fetch=do_fetch)
        s2 = store.run(KEY, task_id=2, my_text="评论乙", threshold=0.85,
                       depth=150, cancel_token=None, do_fetch=do_fetch)
        assert len(calls) == 1
        assert s1 is s2

    def test_same_task_rerun_refetches(self):
        store = SharedCommentStore()
        calls = []

        def do_fetch():
            calls.append(1)
            return _snap(50, exhausted=True)

        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=do_fetch)
        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=do_fetch)
        assert len(calls) == 2

    def test_negative_cache_unifies_failure(self):
        store = SharedCommentStore()
        calls = []

        def do_fetch():
            calls.append(1)
            return CommentSnapshot(depth=150, error="HTTP 400 — cookie likely invalid")

        s1 = store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                       depth=150, cancel_token=None, do_fetch=do_fetch)
        s2 = store.run(KEY, task_id=2, my_text="评论乙", threshold=0.85,
                       depth=150, cancel_token=None, do_fetch=do_fetch)
        assert len(calls) == 1
        assert s1.error == s2.error == "HTTP 400 — cookie likely invalid"

    def test_early_stopped_snapshot_not_reused_when_unmatched(self):
        # 命中即停截短的快照里没有任务 2 的评论 → 任务 2 必须自己重抓，
        # 绝不能拿截短快照误报"评论不在"。
        store = SharedCommentStore()
        calls = []

        def fetch_short():
            calls.append("short")
            return _snap(20, depth=100, plant={3: "评论甲"}, early=True)

        def fetch_full():
            calls.append("full")
            return _snap(100, depth=100, plant={3: "评论甲", 90: "评论乙"})

        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=100, cancel_token=None, do_fetch=fetch_short)
        s2 = store.run(KEY, task_id=2, my_text="评论乙", threshold=0.85,
                       depth=100, cancel_token=None, do_fetch=fetch_full)
        assert calls == ["short", "full"]
        assert any(c["text"] == "评论乙" for c in s2.comments)

    def test_early_stopped_snapshot_reused_when_matched(self):
        store = SharedCommentStore()
        calls = []

        def fetch_short():
            calls.append(1)
            return _snap(20, depth=100, plant={3: "评论甲", 9: "评论乙"}, early=True)

        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=100, cancel_token=None, do_fetch=fetch_short)
        store.run(KEY, task_id=2, my_text="评论乙", threshold=0.85,
                  depth=100, cancel_token=None, do_fetch=fetch_short)
        assert len(calls) == 1

    def test_exhausted_snapshot_reused_even_unmatched(self):
        # 评论区翻尽（只有 30 条）的快照对任何任务都是完整证据：未命中=真不在。
        store = SharedCommentStore()
        calls = []

        def do_fetch():
            calls.append(1)
            return _snap(30, depth=150, exhausted=True)

        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=do_fetch)
        s2 = store.run(KEY, task_id=2, my_text="不存在的评论", threshold=0.85,
                       depth=150, cancel_token=None, do_fetch=do_fetch)
        assert len(calls) == 1
        assert len(s2.comments) == 30

    def test_full_depth_snapshot_reused_for_unmatched(self):
        # 未截短、覆盖完整深度的快照：未命中=超出深度/被删，可复用。
        store = SharedCommentStore()
        calls = []

        def do_fetch():
            calls.append(1)
            return _snap(150, depth=150)

        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=do_fetch)
        store.run(KEY, task_id=2, my_text="不存在的评论", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=do_fetch)
        assert len(calls) == 1

    def test_shallower_snapshot_not_reused_for_deeper_request(self):
        # 快照深度 100 < 任务要求 150 且未命中未翻尽 → 重抓。
        store = SharedCommentStore()
        calls = []

        def fetch_100():
            calls.append(100)
            return _snap(100, depth=100)

        def fetch_150():
            calls.append(150)
            return _snap(150, depth=150)

        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=100, cancel_token=None, do_fetch=fetch_100)
        store.run(KEY, task_id=2, my_text="不存在的评论", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=fetch_150)
        assert calls == [100, 150]

    def test_linger_expiry_refetches(self):
        store = SharedCommentStore(linger_seconds=0.05)
        calls = []

        def do_fetch():
            calls.append(1)
            return _snap(50, exhausted=True)

        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=do_fetch)
        time.sleep(0.08)
        store.run(KEY, task_id=2, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=do_fetch)
        assert len(calls) == 2

    def test_uncacheable_snapshot_not_stored(self):
        # 用户取消导致的截断快照：返回给取消者本人，但不入缓存。
        store = SharedCommentStore()
        calls = []

        def fetch_cancelled():
            calls.append(1)
            return CommentSnapshot(comments=_comments(5), depth=150,
                                   early_stopped=True, cacheable=False)

        def fetch_full():
            calls.append(2)
            return _snap(150, depth=150)

        s1 = store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                       depth=150, cancel_token=None, do_fetch=fetch_cancelled)
        assert len(s1.comments) == 5
        store.run(KEY, task_id=2, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=fetch_full)
        assert calls == [1, 2]

    def test_concurrent_single_flight(self):
        store = SharedCommentStore()
        calls = []
        release = threading.Event()
        started = threading.Event()

        def slow_fetch():
            calls.append(1)
            started.set()
            release.wait(5)
            return _snap(50, plant={3: "评论甲"}, exhausted=True)

        results: list[CommentSnapshot] = []

        def worker(tid: int):
            results.append(store.run(KEY, task_id=tid, my_text="评论甲", threshold=0.85,
                                     depth=150, cancel_token=None, do_fetch=slow_fetch))

        t1 = threading.Thread(target=worker, args=(1,), daemon=True)
        t1.start()
        assert started.wait(5)
        t2 = threading.Thread(target=worker, args=(2,), daemon=True)
        t2.start()
        time.sleep(0.2)  # 让 t2 进入等待
        release.set()
        t1.join(5)
        t2.join(5)
        assert len(calls) == 1
        assert len(results) == 2
        assert results[0] is results[1]

    def test_cancel_while_waiting_raises(self):
        store = SharedCommentStore()
        release = threading.Event()
        started = threading.Event()

        def slow_fetch():
            started.set()
            release.wait(5)
            return _snap(50, exhausted=True)

        t1 = threading.Thread(
            target=lambda: store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                                     depth=150, cancel_token=None, do_fetch=slow_fetch),
            daemon=True,
        )
        t1.start()
        assert started.wait(5)
        cancel = threading.Event()
        cancel.set()
        try:
            with pytest.raises(Exception, match="cancelled by user"):
                store.run(KEY, task_id=2, my_text="评论甲", threshold=0.85,
                          depth=150, cancel_token=cancel,
                          do_fetch=lambda: _snap(1))
        finally:
            release.set()
            t1.join(5)

    def test_fetcher_exception_releases_waiters(self):
        # fetcher 被取消（异常上抛）不能连累等待者：等待者接棒自己抓。
        store = SharedCommentStore()
        started = threading.Event()
        proceed = threading.Event()
        outcome: list = []

        def failing_fetch():
            started.set()
            proceed.wait(5)
            raise RuntimeError("cancelled by user")

        def good_fetch():
            return _snap(50, plant={2: "评论乙"}, exhausted=True)

        def fetcher():
            try:
                store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                          depth=150, cancel_token=None, do_fetch=failing_fetch)
            except RuntimeError as e:
                outcome.append(str(e))

        t1 = threading.Thread(target=fetcher, daemon=True)
        t1.start()
        assert started.wait(5)

        result: list[CommentSnapshot] = []
        t2 = threading.Thread(
            target=lambda: result.append(
                store.run(KEY, task_id=2, my_text="评论乙", threshold=0.85,
                          depth=150, cancel_token=None, do_fetch=good_fetch)),
            daemon=True,
        )
        t2.start()
        time.sleep(0.2)
        proceed.set()
        t1.join(5)
        t2.join(5)
        assert outcome == ["cancelled by user"]
        assert result and result[0].error is None
        assert any(c["text"] == "评论乙" for c in result[0].comments)

    def test_wait_timeout_falls_back_to_own_fetch(self):
        store = SharedCommentStore(wait_timeout=0.3)
        started = threading.Event()
        release = threading.Event()

        def stuck_fetch():
            started.set()
            release.wait(10)
            return _snap(50)

        t1 = threading.Thread(
            target=lambda: store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                                     depth=150, cancel_token=None, do_fetch=stuck_fetch),
            daemon=True,
        )
        t1.start()
        assert started.wait(5)
        try:
            snap = store.run(KEY, task_id=2, my_text="评论乙", threshold=0.85,
                             depth=150, cancel_token=None,
                             do_fetch=lambda: _snap(9, exhausted=True))
            assert len(snap.comments) == 9
        finally:
            release.set()
            t1.join(5)

    def test_video_id_cache_roundtrip(self):
        store = SharedCommentStore()
        assert store.get_video_id("local", "kuaishou_comment", "https://v.kuaishou.com/x") is None
        store.put_video_id("local", "kuaishou_comment", "https://v.kuaishou.com/x", "photoX")
        assert store.get_video_id("local", "kuaishou_comment", "https://v.kuaishou.com/x") == ("photoX", "")
        store.put_video_id("tikhub", "bilibili_comment", "https://b23.tv/y", "BV1xx", "bvid")
        assert store.get_video_id("tikhub", "bilibili_comment", "https://b23.tv/y") == ("BV1xx", "bvid")

    def test_video_id_cache_expiry(self):
        store = SharedCommentStore(linger_seconds=0.05)
        store.put_video_id("local", "kuaishou_comment", "u", "photoX")
        time.sleep(0.08)
        assert store.get_video_id("local", "kuaishou_comment", "u") is None

    def test_peek_consumes_and_misses(self):
        store = SharedCommentStore()
        assert store.peek(KEY, task_id=1, my_text="评论甲", threshold=0.85, depth=150) is None
        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85, depth=150,
                  cancel_token=None, do_fetch=lambda: _snap(50, exhausted=True))
        snap = store.peek(KEY, task_id=2, my_text="评论乙", threshold=0.85, depth=150)
        assert snap is not None
        # 已消费过（served）→ 同任务 peek 不再命中（重跑应强制刷新）
        assert store.peek(KEY, task_id=2, my_text="评论乙", threshold=0.85, depth=150) is None

    def test_task_id_zero_bypasses_store_entirely(self):
        # 无 id 调用（mining 预筛 / 脚本）不读、不写、不单飞：
        #   - 预筛的浅抓/失败绝不污染监控任务的共享仓；
        #   - 监控快照也不会被预筛消费。
        store = SharedCommentStore()
        calls = []

        def shallow_fetch():
            calls.append("prefilter")
            return CommentSnapshot(comments=_comments(30), depth=30)

        def full_fetch():
            calls.append("monitor")
            return _snap(150, depth=150, exhausted=True)

        # 预筛（task_id=0）先抓 → 不入缓存
        store.run(KEY, task_id=0, my_text="占位", threshold=0.85,
                  depth=30, cancel_token=None, do_fetch=shallow_fetch)
        assert store.peek(KEY, task_id=1, my_text="评论甲", threshold=0.85, depth=150) is None
        # 监控任务照常真实抓取（不消费预筛残留）
        store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85,
                  depth=150, cancel_token=None, do_fetch=full_fetch)
        # 预筛再来（task_id=0）也不消费监控快照、每次都自己抓
        store.run(KEY, task_id=0, my_text="占位", threshold=0.85,
                  depth=30, cancel_token=None, do_fetch=shallow_fetch)
        assert store.peek(KEY, task_id=0, my_text="评论甲", threshold=0.85, depth=150) is None
        assert calls == ["prefilter", "monitor", "prefilter"]

    def test_consumed_result_comments_not_aliased_to_cache(self):
        # metric.hot_comments 随结果落库/发事件 —— 消费产物必须与缓存里的
        # 快照解除别名，下游写者不能跨任务污染缓存。
        from csm_core.monitor.base import MonitorTask
        from csm_core.monitor.platforms._comment_shared import result_from_snapshot

        store = SharedCommentStore()
        snap = store.run(KEY, task_id=1, my_text="评论甲", threshold=0.85, depth=150,
                         cancel_token=None,
                         do_fetch=lambda: _snap(10, plant={2: "评论甲"}, exhausted=True))
        task = MonitorTask(type="kuaishou_comment", name="t", target_url="u",
                           config={"my_comment_text": "评论甲", "top_n": 5})
        result = result_from_snapshot(task, snap, source="curl_cffi")
        hot = result.metric["hot_comments"]
        assert hot and all(a is not b for a, b in zip(hot, snap.comments))
        hot[0]["text"] = "被下游改写"
        assert snap.comments[0]["text"] != "被下游改写"


# ── 快手本地适配器集成：同视频两任务只抓一轮 ────────────────────────────────
class TestKuaishouSharedFetch:
    URL = "https://v.kuaishou.com/7G1uSM4V"

    def _task(self, tid: int, comment: str) -> MonitorTask:
        t = MonitorTask(
            type="kuaishou_comment", name=f"t{tid}", target_url=self.URL,
            config={"my_comment_text": comment, "top_n": 5},
        )
        t.id = tid
        return t

    def _adapter(self, monkeypatch, fetch_impl):
        from csm_core.monitor.platforms.kuaishou_comment import KuaishouCommentAdapter
        a = KuaishouCommentAdapter()
        monkeypatch.setattr(a._pacer, "wait", lambda: None)
        monkeypatch.setattr(a._breaker, "allow", lambda: True)
        monkeypatch.setattr(a._breaker, "record_success", lambda: None)
        monkeypatch.setattr(a._breaker, "record_failure", lambda: None)
        monkeypatch.setattr(a._cookies, "pick", lambda: None)
        monkeypatch.setattr(a, "_extract_video_id", lambda *x, **k: ("photoX", ""))
        monkeypatch.setattr(a, "_fetch_comments", fetch_impl)
        return a

    def test_two_tasks_same_video_single_fetch(self, monkeypatch):
        calls = []

        def fake_fetch(session, photo_id, limit, cancel_token=None, progress_cb=None):
            calls.append(photo_id)
            comments = [
                {"rank": i + 1, "text": f"路人 {i + 1}", "author": "u", "likes": 0}
                for i in range(40)
            ]
            comments[4]["text"] = "评论甲"    # rank 5
            comments[21]["text"] = "评论乙"   # rank 22
            return comments, True, None

        a = self._adapter(monkeypatch, fake_fetch)
        r1 = a.fetch(self._task(1, "评论甲"))
        r2 = a.fetch(self._task(2, "评论乙"))
        assert len(calls) == 1, "同视频第二个任务必须复用快照，不再抓评论区"
        assert r1.status == "ok" and r1.rank == 5
        assert r2.status == "ok" and r2.rank == 22

    def test_same_task_rerun_fetches_fresh(self, monkeypatch):
        calls = []

        def fake_fetch(session, photo_id, limit, cancel_token=None, progress_cb=None):
            calls.append(1)
            return [{"rank": 1, "text": "评论甲", "author": "u", "likes": 0}], True, None

        a = self._adapter(monkeypatch, fake_fetch)
        a.fetch(self._task(1, "评论甲"))
        a.fetch(self._task(1, "评论甲"))
        assert len(calls) == 2, "同一任务重跑应强制刷新快照"

    def test_fetch_failure_shared_across_group(self, monkeypatch):
        calls = []

        def fake_fetch(session, photo_id, limit, cancel_token=None, progress_cb=None):
            calls.append(1)
            return [], False, "HTTP 400 — cookie likely invalid"

        a = self._adapter(monkeypatch, fake_fetch)
        r1 = a.fetch(self._task(1, "评论甲"))
        r2 = a.fetch(self._task(2, "评论乙"))
        assert len(calls) == 1, "抓取失败应负缓存，组内不连环重试"
        assert r1.status == "failed" and r2.status == "failed"
        assert r1.error_message == r2.error_message

    def test_missing_comment_text_fails_without_fetch(self, monkeypatch):
        calls = []

        def fake_fetch(session, photo_id, limit, cancel_token=None, progress_cb=None):
            calls.append(1)
            return [], True, None

        a = self._adapter(monkeypatch, fake_fetch)
        r = a.fetch(MonitorTask(type="kuaishou_comment", name="t",
                                target_url=self.URL, config={"top_n": 5}))
        assert r.status == "failed"
        assert calls == [], "空评论文本不应触发任何抓取"
