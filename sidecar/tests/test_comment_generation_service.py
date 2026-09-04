"""P2 批量生成服务测试：flavor 检查、改写重试、批次流程、模板轮换。

LLM 全程用假 client（记录调用、按脚本返回），不打网络。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import comment_generation_service as gen


def _insert_video(*, video_id: int = 1, platform: str = "bilibili", excluded: int = 0) -> int:
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url, title, excluded, top_comments_json) "
        "VALUES(?,?,?,?,?,?,?)",
        (video_id, platform, f"vid-{video_id}", f"https://example/{video_id}",
         f"标题{video_id}", excluded, '[{"text": "评论样本", "likes": 5, "author": "u"}]'),
    )
    return video_id


def _seed_template(text: str = "模板：这个真不错") -> int:
    return ms.create_template(text=text)


class FakeClient:
    """按脚本吐回复；无脚本时回显固定文案。记录每次 (system, user)。"""

    def __init__(self, replies: list[str] | None = None):
        self.replies = list(replies or [])
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.calls.append((system, user))
        if self.replies:
            return self.replies.pop(0)
        return "自然的评论文案"


# ── flavor_score + _generate_one ───────────────────────────────────────

def test_flavor_score_flags_connectives():
    assert gen.flavor_score("首先这个很好，其次也不贵") >= 3.0
    assert gen.flavor_score("好用，回购了") == 0.0


def _mk_video():
    return {
        "platform": "bilibili", "title": "t", "author": "a", "play_count": 1,
        "summary": "", "top_comments": [], "excluded": False, "id": 1,
    }


def test_generate_one_clean_text_no_retry():
    client = FakeClient(["好用，真的回购了"])
    text, score = gen._generate_one(
        client, gen.DEFAULT_REWRITE_PROMPT_SYSTEM, gen.DEFAULT_REWRITE_PROMPT_USER,
        _mk_video(), "模板", 1, [], "", [],
    )
    assert text == "好用，真的回购了"
    assert score == 0.0
    assert len(client.calls) == 1


def test_generate_one_retries_on_flavor_and_keeps_better():
    # 第一版带「首先/其次」→ 触发重写；第二版干净 → 采用第二版
    client = FakeClient(["首先很好，其次很便宜", "挺好用的，也不贵"])
    text, score = gen._generate_one(
        client, gen.DEFAULT_REWRITE_PROMPT_SYSTEM, gen.DEFAULT_REWRITE_PROMPT_USER,
        _mk_video(), "模板", 1, [], "", [],
    )
    assert text == "挺好用的，也不贵"
    assert score == 0.0
    assert len(client.calls) == 2
    # 重试的 user 消息里带了违规项说明
    assert "AI 痕迹" in client.calls[1][1]


def test_generate_one_keeps_original_when_retry_worse():
    client = FakeClient(["首先很好，其次很便宜", "首先很好，其次很便宜，综上所述必买"])
    text, score = gen._generate_one(
        client, gen.DEFAULT_REWRITE_PROMPT_SYSTEM, gen.DEFAULT_REWRITE_PROMPT_USER,
        _mk_video(), "模板", 1, [], "", [],
    )
    assert text == "首先很好，其次很便宜"
    assert score >= 3.0


# ── _run_batch 集成（直接调 worker，绕开 executor 保确定性）────────────

@pytest.fixture
def quiet_bus(monkeypatch):
    """把 event_bus 换成记录器，免去 create_job/attach 生命周期。"""
    events: list[tuple] = []

    class _Bus:
        def publish(self, qid, kind, **data):
            events.append((kind, data))

        def create_job(self, qid):
            pass

        def finish(self, qid):
            pass

    monkeypatch.setattr(gen, "event_bus", _Bus())
    return events


def _run(video_ids, tiers=1, templates=None, client=None):
    import threading
    batch_id = 999
    gen._cancel_events[batch_id] = threading.Event()
    try:
        gen._run_batch(
            batch_id, video_ids, tiers,
            templates or [{"id": 1, "text": "模板一"}],
            "", client or FakeClient(),
        )
    finally:
        gen._cancel_events.pop(batch_id, None)


def test_run_batch_creates_pending_comments(monitor_db: Path, quiet_bus):
    v1, v2 = _insert_video(video_id=1), _insert_video(video_id=2)
    _run([v1, v2], tiers=2)

    for vid in (v1, v2):
        comments = ms.list_comments(vid)
        assert [c["tier"] for c in comments] == [1, 2]
        assert all(c["review_status"] == "pending" for c in comments)
        assert all(c["source"] == "ai_suggested" for c in comments)

    kinds = [k for k, _ in quiet_bus]
    assert kinds.count("generation.progress") == 2
    assert kinds[-1] == "generation.finished"
    finished = quiet_bus[-1][1]
    assert finished["generated"] == 4
    assert finished["failed"] == 0


def test_run_batch_skips_manual_tier(monitor_db: Path, quiet_bus):
    vid = _insert_video()
    ms.create_comment(vid, 1, "人工写的")  # 占住 tier1
    _run([vid], tiers=2)

    comments = ms.list_comments(vid)
    assert comments[0]["text"] == "人工写的"          # 未被覆盖
    assert comments[1]["review_status"] == "pending"   # tier2 正常生成
    finished = quiet_bus[-1][1]
    assert finished["generated"] == 1
    assert finished["skipped"] == 1


def test_run_batch_skips_excluded_video(monitor_db: Path, quiet_bus):
    vid = _insert_video(excluded=1)
    _run([vid])
    assert ms.list_comments(vid) == []
    finished = quiet_bus[-1][1]
    assert finished["skipped"] == 1
    assert finished["generated"] == 0


def test_run_batch_single_failure_does_not_block(monitor_db: Path, quiet_bus):
    v1, v2 = _insert_video(video_id=1), _insert_video(video_id=2)

    class FlakyClient(FakeClient):
        def complete(self, *, system, user, temperature=None):
            # v1 的标题是「标题1」→ 第一条抛错
            if "标题1" in user:
                raise RuntimeError("boom")
            return super().complete(system=system, user=user)

    _run([v1, v2], client=FlakyClient())
    assert ms.list_comments(v1) == []
    assert len(ms.list_comments(v2)) == 1
    finished = quiet_bus[-1][1]
    assert finished["failed"] == 1
    assert finished["generated"] == 1


def test_run_batch_rotates_templates(monitor_db: Path, quiet_bus):
    v1, v2 = _insert_video(video_id=1), _insert_video(video_id=2)
    templates = [{"id": 11, "text": "模板A"}, {"id": 22, "text": "模板B"}]
    _run([v1, v2], templates=templates)

    t1 = ms.list_comments(v1)[0]["template_id"]
    t2 = ms.list_comments(v2)[0]["template_id"]
    assert {t1, t2} == {11, 22}


def test_run_batch_injects_top_comments_into_prompt(monitor_db: Path, quiet_bus):
    vid = _insert_video()
    client = FakeClient()
    _run([vid], client=client)
    _, user = client.calls[0]
    assert "评论样本" in user      # top_comments_json 快照进了 prompt
    assert "模板一" in user


# ── _resolve_templates ─────────────────────────────────────────────────

def test_resolve_templates_explicit_ids(monitor_db: Path):
    tid = _seed_template("手选模板")
    out = gen._resolve_templates([tid])
    assert out[0]["text"] == "手选模板"
    with pytest.raises(ValueError):
        gen._resolve_templates([9999])


def test_resolve_templates_auto_requires_nonempty_library(monitor_db: Path):
    with pytest.raises(ValueError):
        gen._resolve_templates(None)
    _seed_template()
    assert len(gen._resolve_templates(None)) == 1


def test_submit_batch_clamps_tiers_to_five():
    from csm_sidecar.services import comment_generation_service as cgs
    assert cgs._MAX_TIERS == 5
