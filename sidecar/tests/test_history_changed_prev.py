"""ranking 端点的 changed_prev：上一个窗口的异动数，供大数字卡算「较上周净增减」徽章。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult
from csm_sidecar.services import history_service


# ── zhihu_question（per-task）──────────────────────────────────────────────

def _seed_zhihu_q(client: TestClient) -> int:
    body = {"type": "zhihu_question", "name": "知乎问题-X", "target_url": "https://zhihu.com/q/1",
            "config": {"top_n": 10, "target_brand": "石头"}, "schedule_cron": "manual", "enabled": True}
    return client.post("/api/monitor/tasks", json=body).json()["id"]


def _res_q(tid: int, at: datetime, mc: int):
    storage.save_result(MonitorResult(task_id=tid, checked_at=at, status="ok", rank=1,
        metric={"matched_count": mc, "matched_ranks": [1] * mc, "top_n": 10}, error_message=""))


def test_zhihu_ranking_changed_prev_counts_older_window(client: TestClient, monitor_db: Path):
    tid = _seed_zhihu_q(client)
    now = datetime.now()
    _res_q(tid, now - timedelta(days=9), 2)
    _res_q(tid, now - timedelta(days=8), 4)   # 上一窗口内 up（4 vs 2）
    _res_q(tid, now, 4)                        # 本窗口
    out = history_service.get_zhihu_ranking_history("7d")
    assert out["kpis"]["changed_prev"] == 1


# ── baidu_keyword（per-keyword）────────────────────────────────────────────

def _seed_baidu(client: TestClient, kw: str = "扫地机") -> int:
    body = {"type": "baidu_keyword", "name": "百度-X", "target_url": "https://baidu.com",
            "config": {"search_keywords": [kw], "target_brand": "石头"},
            "schedule_cron": "manual", "enabled": True}
    return client.post("/api/monitor/tasks", json=body).json()["id"]


def _res_baidu(tid: int, at: datetime, kw: str, mc: int, fr: int):
    storage.save_result(MonitorResult(task_id=tid, checked_at=at, status="ok", rank=fr,
        metric={"keywords": [{"keyword": kw, "default_matched_count": mc, "default_first_rank": fr,
                              "default_results": [], "news_results": [], "news_present": False}],
                "search_keywords": [kw], "target_brand": "石头"}, error_message=""))


def test_baidu_changed_prev_counts_older_window(client: TestClient, monitor_db: Path):
    tid = _seed_baidu(client)
    now = datetime.now()
    _res_baidu(tid, now - timedelta(days=9), "扫地机", 1, 5)
    _res_baidu(tid, now - timedelta(days=8), "扫地机", 3, 2)   # up
    _res_baidu(tid, now, "扫地机", 3, 2)
    out = history_service.get_baidu_keyword_history("7d")
    assert out["kpis"]["changed_prev"] == 1


def test_baidu_changed_prev_field_present_when_empty(client: TestClient, monitor_db: Path):
    out = history_service.get_baidu_keyword_history("7d")
    assert out["kpis"]["changed_prev"] == 0


def test_baidu_keyword_row_checked_at_stays_utc(client: TestClient, monitor_db: Path):
    """R6 修正：keyword_rows[].checked_at 仍是原始 UTC —— daily_series 的本地日桶
    只用旁路的 checked_at_local，绝不能把本地时间喂进 _iso_utc（它只归一化 aware
    值，naive-本地会被当 UTC 盖 Z，偏移一个时区）。"""
    tid = _seed_baidu(client)
    utc_at = datetime(2026, 7, 10, 2, 0, 0)  # naive UTC（运行器按 UTC 存）
    _res_baidu(tid, utc_at, "扫地机", 1, 3)
    out = history_service.get_baidu_keyword_history("30d")
    row = next(r for r in out["keywords"] if r["search_keyword"] == "扫地机")
    parsed = storage._parse_iso(row["checked_at"])  # noqa: SLF001
    assert parsed == utc_at, f"checked_at 应为原始 UTC {utc_at}，实际 {row['checked_at']}"


def test_baidu_daily_series_buckets_by_local_day(client: TestClient, monitor_db: Path):
    """R6：daily_series 按**本地日**分桶（与前端本地日 + KPI 口径一致），而不是
    UTC 日。跨日的结果（本地凌晨/深夜、UTC 落在相邻日）不应错分到相邻桶。"""
    import pytest
    from datetime import timezone as _tz
    offset = datetime.now().astimezone().utcoffset()
    if offset is None or offset == timedelta(0):
        pytest.skip("UTC 机器无本地/UTC 日偏移，测不出")
    hour = 6 if offset > timedelta(0) else 22  # 让本地时刻与 UTC 落在相邻日

    tid = _seed_baidu(client)
    target_local = (datetime.now() - timedelta(days=2)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    target_utc = target_local.astimezone(_tz.utc).replace(tzinfo=None)  # 运行器按 UTC 存
    d_local = target_local.strftime("%Y-%m-%d")
    d_utc = target_utc.strftime("%Y-%m-%d")
    assert d_local != d_utc, "构造前提：本地日与 UTC 日必须不同"

    _res_baidu(tid, target_utc, "扫地机", 1, 3)
    out = history_service.get_baidu_keyword_history("30d")
    first_hit = next((b["date"] for b in out["daily_series"] if b["avg_match_rate"] > 0), None)
    assert first_hit == d_local, f"应按本地日 {d_local} 分桶，实际 {first_hit}（UTC 日 {d_utc}）"


def test_zhihu_search_changed_prev_field_present_when_empty(client: TestClient, monitor_db: Path):
    out = history_service.get_zhihu_search_history("7d")
    assert out["kpis"]["changed_prev"] == 0


# ── R6收尾：comment_retention + zhihu_ranking daily_series 本地日桶 ─────────
# #163 已把 baidu/zhihu_search 的 daily_series 改成本地日分桶（前端本地日 + KPI
# 口径一致）。这两处遗留仍按 UTC 日分桶 —— 跨日结果（本地凌晨/深夜、UTC 落相邻
# 日）会错分到相邻桶。checked_at 仍须保持原始 UTC 供 _iso_utc 输出用。

def _seed_comment(client: TestClient, *, ptype: str = "bilibili_comment",
                  name: str = "0514 - BV001", url: str = "https://b23.tv/r6a") -> int:
    body = {"type": ptype, "name": name, "target_url": url,
            "config": {"my_comment_text": "测试评论"}, "schedule_cron": "manual", "enabled": True}
    return client.post("/api/monitor/tasks", json=body).json()["id"]


def _res_comment(tid: int, at: datetime, matched: bool):
    storage.save_result(MonitorResult(
        task_id=tid, checked_at=at, status="ok", rank=1 if matched else -1,
        metric={"matched": matched, "my_comment_text": "测试评论"}, error_message=""))


def _cross_tz_hour() -> "int | None":
    """挑一个让本地墙钟与 UTC 落在相邻日的小时；UTC 机器返回 None（测不出）。"""
    offset = datetime.now().astimezone().utcoffset()
    if offset is None or offset == timedelta(0):
        return None
    return 6 if offset > timedelta(0) else 22


def test_comment_retention_daily_series_buckets_by_local_day(client: TestClient, monitor_db: Path):
    import pytest
    from datetime import timezone as _tz
    hour = _cross_tz_hour()
    if hour is None:
        pytest.skip("UTC 机器无本地/UTC 日偏移，测不出")

    tid = _seed_comment(client)
    target_local = (datetime.now() - timedelta(days=2)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    target_utc = target_local.astimezone(_tz.utc).replace(tzinfo=None)  # 运行器按 UTC 存
    d_local = target_local.strftime("%Y-%m-%d")
    d_utc = target_utc.strftime("%Y-%m-%d")
    assert d_local != d_utc, "构造前提：本地日与 UTC 日必须不同"

    _res_comment(tid, target_utc, matched=True)
    out = history_service.get_comment_retention_history("30d")
    bili = out["platforms"]["bilibili_comment"]
    hit = next((b["date"] for b in bili["daily_series"] if b["total"] > 0), None)
    assert hit == d_local, f"应按本地日 {d_local} 分桶，实际 {hit}（UTC 日 {d_utc}）"


def test_zhihu_ranking_daily_series_buckets_by_local_day(client: TestClient, monitor_db: Path):
    import pytest
    from datetime import timezone as _tz
    hour = _cross_tz_hour()
    if hour is None:
        pytest.skip("UTC 机器无本地/UTC 日偏移，测不出")

    tid = _seed_zhihu_q(client)
    target_local = (datetime.now() - timedelta(days=2)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    target_utc = target_local.astimezone(_tz.utc).replace(tzinfo=None)
    d_local = target_local.strftime("%Y-%m-%d")
    d_utc = target_utc.strftime("%Y-%m-%d")
    assert d_local != d_utc, "构造前提：本地日与 UTC 日必须不同"

    _res_q(tid, target_utc, 3)  # matched_count=3 → avg_share>0
    out = history_service.get_zhihu_ranking_history("30d")
    hit = next((b["date"] for b in out["daily_series"] if b["avg_share"] > 0), None)
    assert hit == d_local, f"应按本地日 {d_local} 分桶，实际 {hit}（UTC 日 {d_utc}）"


def test_comment_retention_event_at_stays_utc(client: TestClient, monitor_db: Path):
    """events[].at 仍是原始 UTC —— 本地日桶只影响分桶，不能把本地时间喂进
    _iso_utc（它只归一化 aware 值，naive-本地会被误盖 Z、偏移一个时区）。"""
    tid = _seed_comment(client, ptype="kuaishou_comment", name="B - vid1", url="https://k.sr/r6b")
    at_in = (datetime.now() - timedelta(hours=2)).replace(microsecond=0)
    _res_comment(tid, at_in, matched=False)
    out = history_service.get_comment_retention_history("30d")
    assert out["events"], "matched=False 应产出一条删除事件"
    parsed = storage._parse_iso(out["events"][0]["at"])  # noqa: SLF001
    assert parsed == at_in, f"event.at 应为原始 UTC {at_in}，实际 {out['events'][0]['at']}"


def test_zhihu_ranking_question_checked_at_stays_utc(client: TestClient, monitor_db: Path):
    """questions[].checked_at 仍是原始 UTC（同上，供 _iso_utc 输出）。"""
    tid = _seed_zhihu_q(client)
    at_in = (datetime.now() - timedelta(hours=2)).replace(microsecond=0)
    _res_q(tid, at_in, 2)
    out = history_service.get_zhihu_ranking_history("30d")
    q = next(q for q in out["questions"] if q["task_id"] == tid)
    parsed = storage._parse_iso(q["checked_at"])  # noqa: SLF001
    assert parsed == at_in, f"checked_at 应为原始 UTC {at_in}，实际 {q['checked_at']}"


# ── R6 收尾-2：changed_prev 窗口 + events cutoff 也按本地日 ─────────────────
# daily_series 已按本地日分桶（#163/#165）；changed_prev 的「上一窗口」cutoff 与
# comment events 的 cutoff 仍拿原始 UTC 和本地 now-cutoff 比 → 边界 8h 内的结果落错
# 窗口。构造一个 checked_at：本地日分类与 UTC 分类落在 cutoff **两侧**，断言按本地
# （正确）分类计数/收录 —— buggy(UTC) 会给相反答案。offset 符号无关、UTC 机器 skip。

def _straddle_utc(cutoff_local: datetime) -> "tuple[datetime, bool] | None":
    """返回一个 naive-UTC checked_at，使其在「本地日 vs UTC」比对下落在 cutoff 两侧；
    外加「本地(正确)分类是否属于上一窗口(< cutoff)」。|offset| 不足则 None(skip)。"""
    offset = datetime.now().astimezone().utcoffset()
    if offset is None or abs(offset) < timedelta(hours=2):
        return None
    half = offset / 2
    checked_local = cutoff_local + half         # offset>0→cutoff 后(当前)；offset<0→前(上一)
    checked_utc = checked_local - offset         # _utc_to_local_naive 映射回 checked_local
    fixed_in_prev = checked_local < cutoff_local  # 本地(正确)分类
    return checked_utc, fixed_in_prev


def test_zhihu_ranking_changed_prev_uses_local_window(client: TestClient, monitor_db: Path):
    import pytest
    now = datetime.now()
    cutoff = now - timedelta(days=7)
    st = _straddle_utc(cutoff)
    if st is None:
        pytest.skip("UTC/小偏移机器测不出")
    checked_utc, fixed_in_prev = st
    tid = _seed_zhihu_q(client)
    _res_q(tid, cutoff - timedelta(days=3), 2)   # 明确在上一窗口，mc=2
    _res_q(tid, checked_utc, 4)                  # 边界结果，mc=4（若落上一窗口=up）
    out = history_service.get_zhihu_ranking_history("7d")
    # 本地(正确)：落上一窗口 → older=[边界,老]=up → 1；落当前窗口 → older=[老]=flat → 0
    assert out["kpis"]["changed_prev"] == (1 if fixed_in_prev else 0)


def test_baidu_changed_prev_uses_local_window(client: TestClient, monitor_db: Path):
    import pytest
    now = datetime.now()
    cutoff = now - timedelta(days=7)
    st = _straddle_utc(cutoff)
    if st is None:
        pytest.skip("UTC/小偏移机器测不出")
    checked_utc, fixed_in_prev = st
    tid = _seed_baidu(client)
    _res_baidu(tid, cutoff - timedelta(days=3), "扫地机", 1, 5)  # 上一窗口
    _res_baidu(tid, checked_utc, "扫地机", 4, 2)                 # 边界，mc↑（若落上一窗口=up）
    out = history_service.get_baidu_keyword_history("7d")
    assert out["kpis"]["changed_prev"] == (1 if fixed_in_prev else 0)


def test_comment_events_cutoff_uses_local_window(client: TestClient, monitor_db: Path):
    import pytest
    now = datetime.now()
    cutoff = now - timedelta(days=7)
    st = _straddle_utc(cutoff)
    if st is None:
        pytest.skip("UTC/小偏移机器测不出")
    checked_utc, fixed_in_prev = st
    tid = _seed_comment(client, ptype="kuaishou_comment", name="C - vid2", url="https://k.sr/r6c")
    _res_comment(tid, checked_utc, matched=False)  # 一条删除事件，卡窗口边界
    out = history_service.get_comment_retention_history("7d")
    present = any(storage._parse_iso(e["at"]) == checked_utc for e in out["events"])  # noqa: SLF001
    # events 收录窗口内(本地 >= cutoff)的删除；本地落当前窗口→收录，落上一窗口→不收录
    assert present == (not fixed_in_prev)
