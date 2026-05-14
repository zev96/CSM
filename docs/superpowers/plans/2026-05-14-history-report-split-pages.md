# 历史报告页重构：评论留存率 + 知乎排名分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现在统一的「历史报告」单表替换成两个 sub-page（评论留存率 + 知乎排名），各自带 1d/7d/30d 时间范围切换、KPI 卡、折线图、可跳转 drill-down 表，让用户能直接定位「哪个平台在掉评论」/「哪个问题占有率掉了」。

**Architecture:** 两个 sub-page 独立成 Vue SFC 文件（避开 `MonitorView.vue` 已经 3300 行的肥肉），共享一个新 `LineChart.vue` 通用图表组件（封装 `vue-chartjs` 的 `Line`）。后端补两个聚合端点，按日 bucket 跨任务汇总。`MonitorView.vue` 只保留 sub-pivot 状态 + 两个子组件 mount + 跳转回调；旧的 reports 表 + 服务 + AlertDetailModal 的 `history_report` 分支一并清理。

**Tech Stack:** Vue 3 SFC（Composition API）/ chart.js v4 + vue-chartjs v5（树摇引入）/ FastAPI / sqlite3 / pytest。

**Spec:** [docs/superpowers/specs/2026-05-14-history-report-split-pages-design.md](../specs/2026-05-14-history-report-split-pages-design.md)

**Mockups (validated):**
- 评论页 v3：`.superpowers/brainstorm/2685-1778748075/content/comment-retention-layout-v3.html`
- 知乎页：`.superpowers/brainstorm/2685-1778748075/content/zhihu-ranking-layout.html`

---

## File Structure

**新增**：
- `sidecar/csm_sidecar/services/history_service.py` — 两端 aggregation 服务（拆出来不挤 monitor_service.py，按 spec「文件大小」约束）
- `sidecar/tests/test_history_routes.py` — 两端 endpoint + service 单测
- `frontend/src/components/monitor/history/LineChart.vue` — Chart.js 封装
- `frontend/src/components/monitor/history/RetentionPage.vue` — 评论留存率页
- `frontend/src/components/monitor/history/ZhihuRankingPage.vue` — 知乎排名页

**修改**：
- `frontend/package.json` — 加 `chart.js`、`vue-chartjs`
- `sidecar/csm_sidecar/routes/monitor.py` — 加两条 GET 路由，删 `/api/monitor/reports` 路由
- `frontend/src/views/MonitorView.vue` — 历史报告 tab 整段替换，加 `historySubtab` ref + 两个跳转回调
- `frontend/src/components/monitor/AlertDetailModal.vue` — 删 `kind="history_report"` 分支
- `sidecar/tests/test_monitor_routes.py` — 删 `test_reports_*` 三个用例
- `docs/migration/feature-ui-mapping.md` — 把「历史监测报告」行更新到新两端

**删除**：
- `sidecar/csm_sidecar/services/monitor_service.py` 的 `get_reports()` + `_bucket_key()`
- `MonitorView.vue` 的 `reports`/`SAMPLE_REPORTS`/`loadReports`/`openReport`/`selectedReport` + 旧表 template

---

## Task 1: 后端 `comment-retention` 聚合服务（TDD）

**Files:**
- Create: `sidecar/csm_sidecar/services/history_service.py`
- Create: `sidecar/tests/test_history_routes.py`

- [ ] **Step 1: 写第一个失败测试 — 空 DB 不挂**

Create `sidecar/tests/test_history_routes.py`:

```python
"""Tests for /api/monitor/history/* — comment retention + zhihu ranking aggregation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult


def _seed_task(client: TestClient, **overrides) -> int:
    body = {
        "type": "bilibili_comment",
        "name": "0514 - BV001",
        "target_url": "https://www.bilibili.com/video/BV001",
        "config": {"my_comment_text": "test", "top_n": 5},
        "schedule_cron": "manual",
        "enabled": True,
    }
    body.update(overrides)
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_result(task_id: int, *, checked_at: datetime, matched: bool, status: str = "ok",
                 hot_comments=None, my_comment_text: str = "test"):
    """Insert a MonitorResult row directly via storage (bypassing the HTTP layer)."""
    storage.save_result(MonitorResult(
        task_id=task_id,
        checked_at=checked_at,
        status=status,
        rank=1 if matched else -1,
        metric={
            "matched": matched,
            "my_comment_text": my_comment_text,
            "total_fetched": 17 if matched else 0,
            "scope_total": 17 if matched else 0,
            "hot_comments": hot_comments or [],
            "scrape_top_n": 150,
            "alert_top_n": 5,
        },
        error_message=None,
    ))


def test_comment_retention_empty_db_returns_zero_platforms(client: TestClient, monitor_db: Path):
    """空 DB 时三个平台都返回 0/0，不挂。"""
    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "7d"
    assert set(body["platforms"].keys()) == {"bilibili_comment", "douyin_comment", "kuaishou_comment"}
    for p in body["platforms"].values():
        assert p["current_total"] == 0
        assert p["current_retained"] == 0
        assert p["daily_series"] == []
    assert body["events"] == []
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `cd sidecar && python -m pytest tests/test_history_routes.py::test_comment_retention_empty_db_returns_zero_platforms -v`
Expected: FAIL — 404 (route not registered yet)

- [ ] **Step 3: 写 `history_service.get_comment_retention_history()`**

Create `sidecar/csm_sidecar/services/history_service.py`:

```python
"""Aggregation queries for the 历史报告 page (comment retention + zhihu ranking).

Pulled out of monitor_service.py so that file doesn't keep growing — these
are UI-shaped views, computed on the fly from monitor_results + monitor_tasks
joins. No new tables, no schema changes.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from csm_core.monitor import storage


COMMENT_PLATFORMS = ("bilibili_comment", "douyin_comment", "kuaishou_comment")
PLATFORM_LABELS = {
    "bilibili_comment": "B 站",
    "douyin_comment": "抖音",
    "kuaishou_comment": "快手",
}


def _parse_range(range_str: str) -> int:
    if range_str == "1d":
        return 1
    if range_str == "7d":
        return 7
    if range_str == "30d":
        return 30
    raise ValueError(f"range must be '1d' / '7d' / '30d', got {range_str!r}")


def get_comment_retention_history(range_str: str) -> dict[str, Any]:
    """Per-platform retention rate over time + recent deletion events.

    For each platform we compute:
      - ``current_retained / current_total / current_deleted`` — the most
        recent day's snapshot (matched=True / status=ok counts).
      - ``rate_today / rate_prev`` — for the delta chip. rate_prev is the
        same kind of snapshot but ``range_days`` ago, so 7d shows ↑/↓ vs
        last week, 30d shows vs last month, 1d shows vs yesterday.
      - ``daily_series`` — one bucket per day in range. Each bucket
        dedupes per-task to that task's latest result on that day.
    Recent deletion ``events`` are gathered across all 3 platforms and
    sorted desc by timestamp, capped at 50.
    """
    range_days = _parse_range(range_str)
    now = datetime.now()
    cutoff = now - timedelta(days=range_days)
    # Pull one extra day before cutoff so rate_prev has anchor data.
    extended_cutoff = now - timedelta(days=range_days * 2 if range_days > 1 else 2)
    conn = storage.get_conn()
    rows = conn.execute(
        """
        SELECT r.task_id, r.checked_at, r.status, r.rank, r.metric_json,
               t.type AS task_type, t.name AS task_name
        FROM monitor_results r
        JOIN monitor_tasks t ON t.id = r.task_id
        WHERE t.type IN ('bilibili_comment','douyin_comment','kuaishou_comment')
          AND r.checked_at >= ?
        ORDER BY r.checked_at ASC
        """,
        (storage._format_iso(extended_cutoff),),  # noqa: SLF001
    ).fetchall()

    # Group rows by (platform, date) -> {task_id: (matched, checked_at, metric_dict)}
    # Keeping only the latest result per task per day handles "ran twice that
    # day" cleanly — the later result wins.
    by_platform_date: dict[str, dict[str, dict[int, dict]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        if row["status"] != "ok":
            continue
        m = json.loads(row["metric_json"] or "{}")
        checked = storage._parse_iso(row["checked_at"])  # noqa: SLF001
        if not checked:
            continue
        date_key = checked.strftime("%Y-%m-%d")
        prev = by_platform_date[row["task_type"]][date_key].get(row["task_id"])
        if prev is None or prev["checked_at"] < checked:
            by_platform_date[row["task_type"]][date_key][row["task_id"]] = {
                "matched": bool(m.get("matched")),
                "checked_at": checked,
                "metric": m,
                "task_name": row["task_name"],
            }

    platforms_out: dict[str, dict[str, Any]] = {}
    today_key = now.strftime("%Y-%m-%d")
    for ptype in COMMENT_PLATFORMS:
        daily = by_platform_date.get(ptype, {})
        # Build daily_series strictly within [cutoff..now], one bucket per day,
        # including empty days (so the chart's X-axis is continuous).
        series = []
        for d in range(range_days):
            day = (now - timedelta(days=range_days - 1 - d)).strftime("%Y-%m-%d")
            entries = daily.get(day, {})
            total = len(entries)
            retained = sum(1 for e in entries.values() if e["matched"])
            series.append({
                "date": day,
                "retained": retained,
                "total": total,
                "rate": (retained / total) if total else 0.0,
            })
        # Snapshot: latest day; rate_prev: same-shape snapshot one range_days earlier.
        today_entries = daily.get(today_key, {})
        current_retained = sum(1 for e in today_entries.values() if e["matched"])
        current_total = len(today_entries)
        current_deleted = current_total - current_retained
        prev_day = (now - timedelta(days=range_days)).strftime("%Y-%m-%d")
        prev_entries = daily.get(prev_day, {})
        prev_total = len(prev_entries)
        prev_retained = sum(1 for e in prev_entries.values() if e["matched"])
        platforms_out[ptype] = {
            "label": PLATFORM_LABELS[ptype],
            "current_retained": current_retained,
            "current_total": current_total,
            "current_deleted": current_deleted,
            "rate_today": (current_retained / current_total) if current_total else 0.0,
            "rate_prev": (prev_retained / prev_total) if prev_total else 0.0,
            "daily_series": series,
        }

    events = _collect_deletion_events(by_platform_date, cutoff=cutoff, limit=50)
    return {"range": range_str, "platforms": platforms_out, "events": events}


def _collect_deletion_events(
    by_platform_date: dict[str, dict[str, dict[int, dict]]],
    *,
    cutoff: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull the matched=False rows from each platform/date bucket within the
    range and shape them for the drill-down table. v0 simplification: we just
    surface "currently deleted/folded" rows rather than computing prev→now
    transitions; the user mostly cares about "which comments are gone right
    now", not "exactly when each one fell off"."""
    events: list[dict[str, Any]] = []
    for ptype, daily in by_platform_date.items():
        for date_key, entries in daily.items():
            for task_id, entry in entries.items():
                if entry["checked_at"] < cutoff:
                    continue
                if entry["matched"]:
                    continue
                # Parse batch_name (任务名 "0514 - BV001" → "0514"); same logic
                # as frontend parseBatchName but kept simple here.
                name = entry["task_name"]
                batch = name.split(" - ")[0] if " - " in name else name
                video_title = name.split(" - ", 1)[1] if " - " in name else name
                events.append({
                    "platform": ptype,
                    "task_id": task_id,
                    "batch_name": batch,
                    "video_title": video_title,
                    "comment_text": (entry["metric"].get("my_comment_text") or "")[:200],
                    "rank_from": None,
                    "rank_to": None,
                    "status": "deleted",
                    "at": entry["checked_at"].isoformat(),
                })
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]
```

- [ ] **Step 4: 在 route 文件加这一条**

Edit `sidecar/csm_sidecar/routes/monitor.py`, find the `# ── Summary + reports ──` section header, and insert below the existing `get_reports` route:

```python
@router.get("/api/monitor/history/comment-retention")
async def get_comment_retention_history(range: str = "7d") -> dict[str, Any]:
    _require_storage()
    from ..services import history_service
    try:
        return history_service.get_comment_retention_history(range_str=range)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

(The `_require_storage()` helper already exists at the top of the routes file. Imports `from typing import Any` and `from fastapi import HTTPException` are already there.)

- [ ] **Step 5: 跑测试确认 PASS**

Run: `cd sidecar && python -m pytest tests/test_history_routes.py::test_comment_retention_empty_db_returns_zero_platforms -v`
Expected: PASS

- [ ] **Step 6: 加 daily bucket 聚合测试**

Append to `sidecar/tests/test_history_routes.py`:

```python
def test_comment_retention_groups_by_day_and_dedups_same_task(client: TestClient, monitor_db: Path):
    """同一 task 同一天有两次 result，取最新那次。"""
    tid = _seed_task(client, type="bilibili_comment", name="0514 - BV001")
    now = datetime.now()
    # 早上跑了一次 matched=True
    _seed_result(tid, checked_at=now.replace(hour=9, minute=0, second=0), matched=True)
    # 下午跑了一次 matched=False（这次应胜出）
    _seed_result(tid, checked_at=now.replace(hour=15, minute=0, second=0), matched=False)

    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    body = resp.json()
    bili = body["platforms"]["bilibili_comment"]
    assert bili["current_total"] == 1
    assert bili["current_retained"] == 0  # 下午那次 matched=False 胜出
    assert bili["current_deleted"] == 1
    # daily_series 应有 7 天，最后一天是今天
    assert len(bili["daily_series"]) == 7
    today = now.strftime("%Y-%m-%d")
    last = bili["daily_series"][-1]
    assert last["date"] == today
    assert last["total"] == 1 and last["retained"] == 0


def test_comment_retention_rate_prev_uses_range_days_offset(client: TestClient, monitor_db: Path):
    """rate_prev 取 N 日前同形态的快照。7d range → 7 天前；1d range → 昨天。"""
    tid = _seed_task(client, type="douyin_comment", name="A - vid1")
    now = datetime.now()
    # 7 天前 matched=True，今天 matched=False → rate 从 1.0 → 0.0
    _seed_result(tid, checked_at=now - timedelta(days=7), matched=True)
    _seed_result(tid, checked_at=now, matched=False)

    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    douyin = resp.json()["platforms"]["douyin_comment"]
    assert douyin["rate_today"] == 0.0
    assert douyin["rate_prev"] == 1.0


def test_comment_retention_events_surface_unmatched_rows(client: TestClient, monitor_db: Path):
    """matched=False 的最新 result 进 events 列表。"""
    tid = _seed_task(client, type="kuaishou_comment", name="0514 - X-7Ellfy")
    now = datetime.now()
    _seed_result(tid, checked_at=now - timedelta(hours=2), matched=False,
                 my_comment_text="抽烟可以，但麻烦避开人群")
    resp = client.get("/api/monitor/history/comment-retention?range=7d")
    events = resp.json()["events"]
    assert len(events) == 1
    e = events[0]
    assert e["platform"] == "kuaishou_comment"
    assert e["task_id"] == tid
    assert e["batch_name"] == "0514"
    assert e["video_title"] == "X-7Ellfy"
    assert "抽烟可以" in e["comment_text"]
    assert e["status"] == "deleted"


def test_comment_retention_invalid_range_400(client: TestClient, monitor_db: Path):
    resp = client.get("/api/monitor/history/comment-retention?range=2d")
    assert resp.status_code == 400
    assert "range" in resp.json()["detail"]
```

- [ ] **Step 7: 跑所有 Task 1 测试**

Run: `cd sidecar && python -m pytest tests/test_history_routes.py -v -k comment_retention`
Expected: 4 PASS

- [ ] **Step 8: Commit**

```bash
git add sidecar/csm_sidecar/services/history_service.py \
        sidecar/csm_sidecar/routes/monitor.py \
        sidecar/tests/test_history_routes.py
git commit -m "$(cat <<'EOF'
feat(monitor): add /api/monitor/history/comment-retention endpoint

按日 bucket 跨任务汇总三个评论平台的留存率，dedupe 同一 task 同一
天的多次 result（取最新），rate_prev 取 range_days 前同形态快照供
前端环比 chip 使用，events 表给未匹配的 result 行做 drill-down。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 后端 `zhihu-ranking` 聚合服务（TDD）

**Files:**
- Modify: `sidecar/csm_sidecar/services/history_service.py`
- Modify: `sidecar/csm_sidecar/routes/monitor.py`
- Modify: `sidecar/tests/test_history_routes.py`

- [ ] **Step 1: 写 change_kind 分类的失败测试**

Append to `sidecar/tests/test_history_routes.py`:

```python
def _seed_zhihu_result(task_id: int, *, checked_at: datetime, matched_count: int,
                       best_rank: int = -1, top_n: int = 10):
    """Insert a zhihu MonitorResult."""
    storage.save_result(MonitorResult(
        task_id=task_id,
        checked_at=checked_at,
        status="ok",
        rank=best_rank if matched_count > 0 else -1,
        metric={
            "matched_count": matched_count,
            "matched_ranks": list(range(1, matched_count + 1)),  # 简化，rank=1..N
            "top_n": top_n,
            "alert_top_n": 5,
            "target_brand": "拾梧",
        },
        error_message=None,
    ))


def test_zhihu_change_kind_down_when_match_count_drops(client: TestClient, monitor_db: Path):
    """matched_count 减少 → change_kind=down。"""
    tid = _seed_task(client, type="zhihu_question", name="Q1",
                     target_url="https://www.zhihu.com/question/1",
                     config={"target_brand": "拾梧", "top_n": 10})
    now = datetime.now()
    _seed_zhihu_result(tid, checked_at=now - timedelta(hours=2), matched_count=5)
    _seed_zhihu_result(tid, checked_at=now, matched_count=3)
    resp = client.get("/api/monitor/history/zhihu-ranking?range=7d")
    assert resp.status_code == 200
    q = next(q for q in resp.json()["questions"] if q["task_id"] == tid)
    assert q["change_kind"] == "down"
    assert q["matched_count"] == 3
    assert q["matched_count_prev"] == 5


def test_zhihu_change_kind_dropped_when_all_hits_gone(client: TestClient, monitor_db: Path):
    """有命中 → 无命中 → dropped。"""
    tid = _seed_task(client, type="zhihu_question", name="Q2",
                     target_url="https://www.zhihu.com/question/2",
                     config={"target_brand": "拾梧", "top_n": 10})
    now = datetime.now()
    _seed_zhihu_result(tid, checked_at=now - timedelta(hours=2), matched_count=2)
    _seed_zhihu_result(tid, checked_at=now, matched_count=0)
    q = next(q for q in client.get("/api/monitor/history/zhihu-ranking?range=7d").json()["questions"]
             if q["task_id"] == tid)
    assert q["change_kind"] == "dropped"


def test_zhihu_change_kind_new_when_first_hit(client: TestClient, monitor_db: Path):
    """无命中 → 有命中 → new。"""
    tid = _seed_task(client, type="zhihu_question", name="Q3",
                     target_url="https://www.zhihu.com/question/3",
                     config={"target_brand": "拾梧", "top_n": 10})
    now = datetime.now()
    _seed_zhihu_result(tid, checked_at=now - timedelta(hours=2), matched_count=0)
    _seed_zhihu_result(tid, checked_at=now, matched_count=2)
    q = next(q for q in client.get("/api/monitor/history/zhihu-ranking?range=7d").json()["questions"]
             if q["task_id"] == tid)
    assert q["change_kind"] == "new"


def test_zhihu_change_kind_flat_first_time_seen(client: TestClient, monitor_db: Path):
    """只跑过一次（prev 不存在）→ flat。"""
    tid = _seed_task(client, type="zhihu_question", name="Q4",
                     target_url="https://www.zhihu.com/question/4",
                     config={"target_brand": "拾梧", "top_n": 10})
    _seed_zhihu_result(tid, checked_at=datetime.now(), matched_count=3)
    q = next(q for q in client.get("/api/monitor/history/zhihu-ranking?range=7d").json()["questions"]
             if q["task_id"] == tid)
    assert q["change_kind"] == "flat"


def test_zhihu_kpis_aggregate_across_questions(client: TestClient, monitor_db: Path):
    """跨多个问题聚合：avg_share = ∑matched / ∑top_n，changed_count 统计。"""
    now = datetime.now()
    # Q1: 5/10 命中（旧）→ 3/10（新） — down
    t1 = _seed_task(client, type="zhihu_question", name="Q1",
                    target_url="https://www.zhihu.com/question/1",
                    config={"target_brand": "拾梧", "top_n": 10})
    _seed_zhihu_result(t1, checked_at=now - timedelta(hours=2), matched_count=5)
    _seed_zhihu_result(t1, checked_at=now, matched_count=3)
    # Q2: 0/10 → 2/10 — up (其实是 new，但 KPI 只看异动 / 不分细类)
    t2 = _seed_task(client, type="zhihu_question", name="Q2",
                    target_url="https://www.zhihu.com/question/2",
                    config={"target_brand": "拾梧", "top_n": 10})
    _seed_zhihu_result(t2, checked_at=now - timedelta(hours=2), matched_count=0)
    _seed_zhihu_result(t2, checked_at=now, matched_count=2)

    body = client.get("/api/monitor/history/zhihu-ranking?range=7d").json()
    k = body["kpis"]
    assert k["monitored_questions"] == 2
    # avg_share_today = (3+2) / (10+10) = 0.25
    assert k["avg_share_today"] == pytest.approx(0.25)
    # changed_questions = 2 (Q1 down + Q2 new)
    assert k["changed_questions"] == 2
    assert k["changed_down"] == 1
    assert k["changed_up"] == 1  # "new" 也算 up 类（新增命中）
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `cd sidecar && python -m pytest tests/test_history_routes.py -v -k zhihu`
Expected: 5 FAIL (route not registered yet)

- [ ] **Step 3: 实现 `get_zhihu_ranking_history`**

Append to `sidecar/csm_sidecar/services/history_service.py`:

```python
def get_zhihu_ranking_history(range_str: str) -> dict[str, Any]:
    """KPI + 每日趋势 + 全量问题列表（前端按 change_kind 自行 filter）。

    A question's ``change_kind`` is computed from its two most recent
    successful results: ``current`` (latest) vs ``prev`` (second-to-latest):
      - prev missing → "flat" (首次监测，无对比基准)
      - prev.matched_count > 0 & curr.matched_count == 0 → "dropped"
      - prev.matched_count == 0 & curr.matched_count > 0 → "new"
      - tuple(curr.matched_count, -curr.best_rank) > tuple(prev...) → "up"
      - 反向 → "down"
      - 相等 → "flat"
    """
    range_days = _parse_range(range_str)
    now = datetime.now()
    cutoff = now - timedelta(days=range_days)
    conn = storage.get_conn()
    rows = conn.execute(
        """
        SELECT r.task_id, r.checked_at, r.status, r.rank, r.metric_json,
               t.id AS t_id, t.name AS task_name, t.config_json
        FROM monitor_results r
        JOIN monitor_tasks t ON t.id = r.task_id
        WHERE t.type = 'zhihu_question'
          AND t.enabled = 1
          AND r.status = 'ok'
        ORDER BY r.task_id ASC, r.checked_at DESC
        """,
    ).fetchall()
    # Also need to enumerate tasks even if they have zero results yet, so
    # monitored_questions count is right.
    all_tasks = conn.execute(
        "SELECT id, name, config_json FROM monitor_tasks "
        "WHERE type='zhihu_question' AND enabled=1",
    ).fetchall()

    # Group results per task in checked_at DESC order; take top 2 for prev/curr.
    per_task: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        m = json.loads(row["metric_json"] or "{}")
        checked = storage._parse_iso(row["checked_at"])  # noqa: SLF001
        if not checked:
            continue
        per_task[row["task_id"]].append({
            "checked_at": checked,
            "matched_count": int(m.get("matched_count") or 0),
            "matched_ranks": list(m.get("matched_ranks") or []),
            "best_rank": int(m.get("matched_ranks", [-1])[0]) if m.get("matched_ranks") else -1,
            "top_n": int(m.get("top_n") or m.get("alert_top_n") or 10),
            "target_brand": m.get("target_brand", ""),
            "task_name": row["task_name"],
        })

    questions = []
    for t in all_tasks:
        cfg = json.loads(t["config_json"] or "{}")
        results = per_task.get(t["id"], [])
        curr = results[0] if results else None
        prev = results[1] if len(results) > 1 else None
        kind, share = _classify_zhihu_change(curr, prev)
        top_n = (curr or {}).get("top_n") or int(cfg.get("top_n") or 10)
        target_brand = (curr or {}).get("target_brand") or cfg.get("target_brand", "")
        questions.append({
            "task_id": t["id"],
            "title": t["name"],
            "target_brand": target_brand,
            "matched_count": (curr or {}).get("matched_count", 0),
            "matched_count_prev": (prev or {}).get("matched_count", 0) if prev else None,
            "top_n": top_n,
            "matched_ranks": (curr or {}).get("matched_ranks", []),
            "best_rank": (curr or {}).get("best_rank", -1),
            "best_rank_prev": (prev or {}).get("best_rank", -1) if prev else None,
            "change_kind": kind,
            "checked_at": (curr["checked_at"].isoformat() if curr else None),
        })

    # KPIs aggregated across all questions
    monitored = len(questions)
    hit_count_total = sum(q["matched_count"] for q in questions)
    topn_total = sum(q["top_n"] for q in questions)
    avg_share_today = (hit_count_total / topn_total) if topn_total else 0.0
    hit_count_prev = sum((q["matched_count_prev"] or 0) for q in questions if q["matched_count_prev"] is not None)
    topn_prev_total = sum(q["top_n"] for q in questions if q["matched_count_prev"] is not None)
    avg_share_prev = (hit_count_prev / topn_prev_total) if topn_prev_total else 0.0

    changed_down = sum(1 for q in questions if q["change_kind"] in ("down", "dropped"))
    changed_up = sum(1 for q in questions if q["change_kind"] in ("up", "new"))
    changed_total = changed_down + changed_up

    # Per-day series (just changed_count + avg_share for the line chart)
    daily_series = _zhihu_daily_series(per_task, range_days=range_days, now=now)

    return {
        "range": range_str,
        "kpis": {
            "monitored_questions": monitored,
            "questions_added_this_week": 0,  # v0 不算，避免再多一次查询
            "brands_covered": len({q["target_brand"] for q in questions if q["target_brand"]}),
            "avg_share_today": avg_share_today,
            "avg_share_prev": avg_share_prev,
            "hit_count_total": hit_count_total,
            "topn_total": topn_total,
            "changed_questions": changed_total,
            "changed_up": changed_up,
            "changed_down": changed_down,
        },
        "daily_series": daily_series,
        "questions": questions,
    }


def _classify_zhihu_change(curr: dict | None, prev: dict | None) -> tuple[str, float]:
    if curr is None:
        return "flat", 0.0
    if prev is None:
        return "flat", curr["matched_count"] / max(curr["top_n"], 1)
    if prev["matched_count"] > 0 and curr["matched_count"] == 0:
        return "dropped", 0.0
    if prev["matched_count"] == 0 and curr["matched_count"] > 0:
        return "new", curr["matched_count"] / max(curr["top_n"], 1)
    # Compare tuple (matched_count, -best_rank). Higher matched_count wins;
    # tie-break: smaller best_rank (better) wins. -best_rank flips so larger
    # is better in the natural tuple comparison. Handle -1 (no hits) sentinels.
    def _score(r: dict) -> tuple[int, int]:
        return r["matched_count"], -(r["best_rank"] if r["best_rank"] > 0 else 9999)
    s_curr, s_prev = _score(curr), _score(prev)
    share = curr["matched_count"] / max(curr["top_n"], 1)
    if s_curr > s_prev:
        return "up", share
    if s_curr < s_prev:
        return "down", share
    return "flat", share


def _zhihu_daily_series(
    per_task: dict[int, list[dict]],
    *,
    range_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """For each day in range, compute avg_share + change counts.

    Per-task per-day = the latest result on that day (or carry-forward from
    earlier day if none); aggregated across tasks then.
    """
    series = []
    for d in range(range_days):
        day = (now - timedelta(days=range_days - 1 - d)).date()
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        hits = 0
        topn = 0
        changed_up = changed_down = 0
        for results in per_task.values():
            # results is DESC; find first result whose checked_at < day_end
            curr_on_day = next((r for r in results if r["checked_at"] < day_end), None)
            if not curr_on_day:
                continue
            hits += curr_on_day["matched_count"]
            topn += curr_on_day["top_n"]
            # 当天的 prev：当天 day_start 之前最近一次
            prev_for_day = next(
                (r for r in results if r["checked_at"] < day_start),
                None,
            )
            kind, _ = _classify_zhihu_change(curr_on_day, prev_for_day)
            if kind in ("up", "new"):
                changed_up += 1
            elif kind in ("down", "dropped"):
                changed_down += 1
        series.append({
            "date": day.strftime("%Y-%m-%d"),
            "avg_share": (hits / topn) if topn else 0.0,
            "changed_count": changed_up + changed_down,
            "changed_up": changed_up,
            "changed_down": changed_down,
        })
    return series
```

- [ ] **Step 4: 加 route**

Edit `sidecar/csm_sidecar/routes/monitor.py`, right below the `comment-retention` route from Task 1, add:

```python
@router.get("/api/monitor/history/zhihu-ranking")
async def get_zhihu_ranking_history(range: str = "7d") -> dict[str, Any]:
    _require_storage()
    from ..services import history_service
    try:
        return history_service.get_zhihu_ranking_history(range_str=range)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 5: 跑 zhihu 全部测试**

Run: `cd sidecar && python -m pytest tests/test_history_routes.py -v -k zhihu`
Expected: 5 PASS

- [ ] **Step 6: 跑 comment_retention 确认没回归**

Run: `cd sidecar && python -m pytest tests/test_history_routes.py -v`
Expected: 9 PASS（5 zhihu + 4 comment）

- [ ] **Step 7: Commit**

```bash
git add sidecar/csm_sidecar/services/history_service.py \
        sidecar/csm_sidecar/routes/monitor.py \
        sidecar/tests/test_history_routes.py
git commit -m "$(cat <<'EOF'
feat(monitor): add /api/monitor/history/zhihu-ranking endpoint

跨所有 enabled 知乎任务聚合品牌占有率（∑matched ÷ ∑top_n）、按日
计算 changed_up/changed_down 趋势、每问题输出 change_kind 五分类
（down/up/new/dropped/flat）供前端表过滤。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 删除旧 `/api/monitor/reports` 路由 + 旧 service + 旧测试

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py`
- Modify: `sidecar/csm_sidecar/services/monitor_service.py`
- Modify: `sidecar/tests/test_monitor_routes.py`

- [ ] **Step 1: 删 route 端点**

Edit `sidecar/csm_sidecar/routes/monitor.py`:

```python
# 删掉这一段（line ~241-248）：
@router.get("/api/monitor/reports")
async def get_reports(
    period: str = "daily",
    limit: int = 30,
) -> dict[str, Any]:
    _require_storage()
    try:
        return monitor_service.get_reports(period=period, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 2: 删 service 函数**

Edit `sidecar/csm_sidecar/services/monitor_service.py`, find `def get_reports(` and `def _bucket_key(`, delete both functions entirely (the public one + the helper).

- [ ] **Step 3: 删旧测试**

Edit `sidecar/tests/test_monitor_routes.py`, delete `test_reports_empty_returns_no_items` / `test_reports_groups_by_day` / `test_reports_invalid_period_400` (search for `def test_reports_`).

- [ ] **Step 4: 跑全 sidecar 测试**

Run: `cd sidecar && python -m pytest tests/ -v`
Expected: all PASS, no `test_reports_*` referenced

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/monitor.py \
        sidecar/csm_sidecar/services/monitor_service.py \
        sidecar/tests/test_monitor_routes.py
git commit -m "$(cat <<'EOF'
refactor(monitor): drop legacy /api/monitor/reports

新增的 /api/monitor/history/comment-retention 与 .../zhihu-ranking 接管
原 reports 端点的「按日 bucket」聚合视图，且做了按业务拆分（评论 vs
知乎）。前端不再调用 reports，相关服务函数 + 旧测试一并清理。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 安装 chart.js + vue-chartjs + 写 LineChart 通用组件

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`（npm 自动更新）
- Create: `frontend/src/components/monitor/history/LineChart.vue`

- [ ] **Step 1: 安装依赖**

Run: `cd frontend && npm install chart.js@^4.4.0 vue-chartjs@^5.3.0`
Expected: 两个包安装成功，`package.json` 多两条 dep

- [ ] **Step 2: 写通用 LineChart.vue**

Create `frontend/src/components/monitor/history/LineChart.vue`:

```vue
<script setup lang="ts">
/**
 * 通用折线图 —— 封装 vue-chartjs 的 Line，统一应用色板和默认 tooltip 行为。
 *
 * 用法（评论留存率页 / 知乎排名页共用）：
 *   <LineChart
 *     :labels="['5/8','5/9','5/10',...]"
 *     :series="[
 *       { label:'B 站', color:'#ee6a2a', data:[80,75,72,...] },
 *       { label:'抖音', color:'#1e1c19', data:[90,90,88,...] },
 *     ]"
 *     :y-axis-formatter="(v) => `${v}%`"
 *   />
 *
 * dualAxis 模式（知乎页占有率% + 异动数）：
 *   <LineChart :labels="..." :series="..." dual-axis />
 *   第一条线绑左轴，第二条线绑右轴。
 *
 * 我们只 register 真正用到的 controllers/elements/scales —— chart.js v4
 * tree-shake 友好，避免引入完整 ~150KB 的非压缩 bundle。
 */
import { computed } from "vue";
import { Line } from "vue-chartjs";
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler,
} from "chart.js";

Chart.register(
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler,
);

interface Series {
  label: string;
  color: string;
  data: number[];
}

const props = defineProps<{
  labels: string[];
  series: Series[];
  yAxisFormatter?: (v: number) => string;
  dualAxis?: boolean;
}>();

const data = computed(() => ({
  labels: props.labels,
  datasets: props.series.map((s, i) => ({
    label: s.label,
    borderColor: s.color,
    backgroundColor: s.color + "20",  // 12% alpha 填充
    data: s.data,
    borderWidth: 2.2,
    tension: 0.25,
    pointRadius: 0,
    pointHoverRadius: 4,
    fill: false,
    yAxisID: props.dualAxis && i === 1 ? "y1" : "y",
  })),
}));

const options = computed<any>(() => {
  const base = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },  // 外部 legend 由父组件绘，更可控
      tooltip: {
        backgroundColor: "#1c1a17",
        titleColor: "#fbf7ec",
        bodyColor: "#fbf7ec",
        borderColor: "rgba(255,255,255,0.1)",
        borderWidth: 1,
        padding: 10,
        boxPadding: 4,
        callbacks: props.yAxisFormatter
          ? { label: (ctx: any) => `${ctx.dataset.label}: ${props.yAxisFormatter!(ctx.parsed.y)}` }
          : undefined,
      },
    },
    scales: {
      x: {
        grid: { color: "rgba(28,26,23,0.05)" },
        ticks: { color: "#7a7569", font: { size: 10 } },
      },
      y: {
        beginAtZero: true,
        grid: { color: "rgba(28,26,23,0.05)" },
        ticks: {
          color: props.dualAxis ? props.series[0]?.color || "#7a7569" : "#7a7569",
          font: { size: 10 },
          callback: props.yAxisFormatter
            ? function (this: any, v: any) { return props.yAxisFormatter!(Number(v)); }
            : undefined,
        },
      },
    } as Record<string, any>,
  };
  if (props.dualAxis) {
    base.scales.y1 = {
      position: "right",
      beginAtZero: true,
      grid: { drawOnChartArea: false },
      ticks: {
        color: props.series[1]?.color || "#7a7569",
        font: { size: 10 },
      },
    };
  }
  return base;
});
</script>

<template>
  <div style="position: relative; height: 170px;">
    <Line :data="data" :options="options" />
  </div>
</template>
```

- [ ] **Step 3: 手动 smoke test**

不写单元测（前端没 vitest）。靠后续 Task 6/7 在真实页面里渲染验证。

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json \
        frontend/src/components/monitor/history/LineChart.vue
git commit -m "$(cat <<'EOF'
feat(frontend): add chart.js + vue-chartjs deps and LineChart wrapper

LineChart 封装 chart.js v4 的 Line component，注册时只引入实际用到
的 controllers/elements/scales 保持 tree-shake；统一应用色板 +
深色 tooltip 风格；支持 dualAxis 模式给知乎排名页双轴线用。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 写 RetentionPage.vue（评论留存率页）

**Files:**
- Create: `frontend/src/components/monitor/history/RetentionPage.vue`

参考 mockup：`.superpowers/brainstorm/2685-1778748075/content/comment-retention-layout-v3.html`

- [ ] **Step 1: 写完整组件**

Create `frontend/src/components/monitor/history/RetentionPage.vue`:

```vue
<script setup lang="ts">
/**
 * 评论留存率页 —— 历史报告 tab 的「评论留存率」子页。
 *
 * 数据从 GET /api/monitor/history/comment-retention?range=1d|7d|30d 拉。
 * range 切换时重新 fetch；1d 时隐藏主折线（24h 内无法画）。
 * drill-down 行点击 emit('navigate', {platform, batchName, taskId})。
 */
import { ref, computed, onMounted, watch } from "vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import LineChart from "./LineChart.vue";

type Range = "1d" | "7d" | "30d";
type PlatformKey = "bilibili_comment" | "douyin_comment" | "kuaishou_comment";

interface PlatformView {
  label: string;
  current_retained: number;
  current_total: number;
  current_deleted: number;
  rate_today: number;
  rate_prev: number;
  daily_series: Array<{ date: string; retained: number; total: number; rate: number }>;
}
interface DeletionEvent {
  platform: PlatformKey;
  task_id: number;
  batch_name: string;
  video_title: string;
  comment_text: string;
  status: "deleted" | "folded";
  at: string;
}
interface RetentionResponse {
  range: Range;
  platforms: Record<PlatformKey, PlatformView>;
  events: DeletionEvent[];
}

const emit = defineEmits<{
  navigate: [payload: { platform: PlatformKey; batchName: string; taskId: number }];
}>();

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();
const range = ref<Range>("7d");
const data = ref<RetentionResponse | null>(null);
const loading = ref(false);
const eventFilter = ref<"all" | PlatformKey>("all");

const PLATFORM_COLOR: Record<PlatformKey, string> = {
  bilibili_comment: "#ee6a2a",
  douyin_comment: "#1e1c19",
  kuaishou_comment: "#f5c042",
};
const PLATFORM_CHIP_BG: Record<PlatformKey, string> = {
  bilibili_comment: "rgba(238,106,42,0.15)",
  douyin_comment: "rgba(30,28,25,0.10)",
  kuaishou_comment: "rgba(245,192,66,0.18)",
};
const PLATFORM_CHIP_FG: Record<PlatformKey, string> = {
  bilibili_comment: "#c9521f",
  douyin_comment: "#1c1a17",
  kuaishou_comment: "#8a6810",
};

async function load() {
  loading.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/comment-retention", {
      params: { range: range.value },
    });
    data.value = r.data;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const platformList = computed(() => {
  if (!data.value) return [];
  return (["bilibili_comment", "douyin_comment", "kuaishou_comment"] as PlatformKey[]).map((k) => ({
    key: k,
    color: PLATFORM_COLOR[k],
    ...data.value!.platforms[k],
  }));
});

const filteredEvents = computed(() => {
  if (!data.value) return [];
  return eventFilter.value === "all"
    ? data.value.events
    : data.value.events.filter((e) => e.platform === eventFilter.value);
});

const chartLabels = computed(() => {
  const series = data.value?.platforms.bilibili_comment.daily_series ?? [];
  return series.map((s) => s.date.slice(5));  // "MM-DD"
});
const chartSeries = computed(() =>
  platformList.value.map((p) => ({
    label: p.label,
    color: p.color,
    data: p.daily_series.map((d) => Math.round(d.rate * 100)),
  })),
);

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function fmtPct(x: number): string { return `${Math.round(x * 100)}%`; }
function fmtDelta(curr: number, prev: number): { text: string; tone: "up" | "down" | "flat" } {
  const diff = Math.round((curr - prev) * 100);
  if (diff > 0) return { text: `↑ ${diff} pts`, tone: "up" };
  if (diff < 0) return { text: `↓ ${Math.abs(diff)} pts`, tone: "down" };
  return { text: "持平", tone: "flat" };
}
</script>

<template>
  <div v-if="loading && !data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">
    加载中…
  </div>
  <div v-else-if="!data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">
    暂无数据
  </div>
  <div v-else class="flex flex-col gap-3">
    <!-- range picker -->
    <div class="flex items-center justify-between flex-shrink-0">
      <div>
        <div class="font-display text-[14px] font-semibold">评论平台 · 留存率分析</div>
        <div class="text-[11px] mt-0.5" :style="{ color: 'var(--ink-3)' }">看哪个平台在掉评论、什么时候开始掉</div>
      </div>
      <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card)', border: '1px solid var(--line)' }">
        <button
          v-for="r in (['1d','7d','30d'] as Range[])" :key="r"
          @click="range = r"
          class="px-3.5 py-1 rounded-full text-[12px] font-medium transition-colors"
          :style="{
            background: range === r ? 'var(--dark)' : 'transparent',
            color: range === r ? 'var(--card)' : 'var(--ink-3)',
          }"
        >
          {{ r === "1d" ? "最近 1 天" : r === "7d" ? "最近 7 天" : "最近 30 天" }}
        </button>
      </div>
    </div>

    <!-- 3 KPI cards -->
    <div class="grid grid-cols-3 gap-2.5">
      <div
        v-for="p in platformList" :key="p.key"
        :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
        class="flex flex-col gap-1.5"
      >
        <div class="flex justify-between items-start">
          <div class="flex items-center gap-1.5 text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">
            <span :style="{ width: '8px', height: '8px', borderRadius: '50%', background: p.color }" />
            {{ p.label }}
          </div>
          <span
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            :style="{
              background: fmtDelta(p.rate_today, p.rate_prev).tone === 'up' ? 'rgba(122,155,94,0.15)'
                : fmtDelta(p.rate_today, p.rate_prev).tone === 'down' ? 'rgba(216,90,72,0.12)'
                : 'rgba(28,26,23,0.05)',
              color: fmtDelta(p.rate_today, p.rate_prev).tone === 'up' ? '#5e7848'
                : fmtDelta(p.rate_today, p.rate_prev).tone === 'down' ? 'var(--red)'
                : 'var(--ink-3)',
            }"
          >{{ fmtDelta(p.rate_today, p.rate_prev).text }}</span>
        </div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1, letterSpacing: '-0.5px' }">
          {{ fmtPct(p.rate_today) }}
        </div>
        <Sparkline
          v-if="range !== '1d' && p.daily_series.length > 0"
          :values="p.daily_series.map((d) => d.rate * 100)"
          :color="p.color"
          :height="28"
        />
        <div class="flex justify-between text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          <span>在显 <b :style="{ color: 'var(--ink)' }">{{ p.current_retained }}</b> / {{ p.current_total }}</span>
          <span>被删 <b :style="{ color: 'var(--red)' }">{{ p.current_deleted }}</b></span>
        </div>
      </div>
    </div>

    <!-- 主图（1d 时隐藏） -->
    <div
      v-if="range !== '1d'"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
    >
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">留存率趋势（按日）</div>
        <div class="flex gap-3 text-[11px]" :style="{ color: 'var(--ink-2)' }">
          <span v-for="p in platformList" :key="p.key">
            <span :style="{ display:'inline-block', width:'8px', height:'8px', background:p.color, borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />{{ p.label }}
          </span>
        </div>
      </div>
      <LineChart :labels="chartLabels" :series="chartSeries" :y-axis-formatter="(v) => `${v}%`" />
    </div>

    <!-- drill-down 表 -->
    <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '12px' }">
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">
          被删 / 折叠评论详情 <span class="font-normal" :style="{ color: 'var(--ink-3)' }">({{ filteredEvents.length }} 条 · 点行进详情)</span>
        </div>
        <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)' }">
          <button
            v-for="f in (['all','bilibili_comment','douyin_comment','kuaishou_comment'] as const)" :key="f"
            @click="eventFilter = f"
            class="px-3 py-1 rounded-full text-[11.5px] font-medium"
            :style="{
              background: eventFilter === f ? 'var(--dark)' : 'transparent',
              color: eventFilter === f ? 'var(--card)' : 'var(--ink-3)',
            }"
          >
            {{ f === "all" ? "全部" : f === "bilibili_comment" ? "B 站" : f === "douyin_comment" ? "抖音" : "快手" }}
          </button>
        </div>
      </div>
      <div v-if="!filteredEvents.length" class="py-6 text-center text-[12px]" :style="{ color: 'var(--ink-3)' }">
        无被删 / 折叠记录
      </div>
      <div v-else>
        <div
          v-for="e in filteredEvents" :key="e.task_id + '-' + e.at"
          @click="emit('navigate', { platform: e.platform, batchName: e.batch_name, taskId: e.task_id })"
          class="grid items-center gap-2 cursor-pointer transition-colors"
          :style="{
            gridTemplateColumns: '60px 1fr 110px 80px 18px',
            padding: '9px 12px',
            fontSize: '11.5px',
            borderRadius: '8px',
            borderTop: '1px solid rgba(28,26,23,0.06)',
          }"
          @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
          @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <div>
            <span
              class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
              :style="{ background: PLATFORM_CHIP_BG[e.platform], color: PLATFORM_CHIP_FG[e.platform] }"
            >{{ e.platform === "bilibili_comment" ? "B 站" : e.platform === "douyin_comment" ? "抖音" : "快手" }}</span>
          </div>
          <div>
            <div :style="{ color: 'var(--ink)' }">{{ e.comment_text || "（无文本）" }}</div>
            <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">{{ e.video_title }} · {{ e.batch_name }} 批次</div>
          </div>
          <div>
            <span
              class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
              :style="{ background: 'rgba(216,90,72,0.12)', color: 'var(--red)' }"
            >在显 → 无</span>
          </div>
          <div :style="{ color: 'var(--ink-3)' }">{{ fmtTime(e.at) }}</div>
          <div class="text-[16px] text-center" :style="{ color: 'var(--ink-4)', lineHeight: 1 }">›</div>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 手动 smoke**

不能孤立测——等 Task 7 把它挂进 MonitorView 再一起验证。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/monitor/history/RetentionPage.vue
git commit -m "$(cat <<'EOF'
feat(history): add RetentionPage component

评论留存率页：range picker + 3 平台 KPI 卡（含 sparkline）+ 主折线图
（1d 时隐藏）+ 被删评论 drill-down 表（行可点 emit navigate）。
数据从 /api/monitor/history/comment-retention 拉。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 写 ZhihuRankingPage.vue（知乎排名页）

**Files:**
- Create: `frontend/src/components/monitor/history/ZhihuRankingPage.vue`

参考 mockup：`.superpowers/brainstorm/2685-1778748075/content/zhihu-ranking-layout.html`

- [ ] **Step 1: 写完整组件**

Create `frontend/src/components/monitor/history/ZhihuRankingPage.vue`:

```vue
<script setup lang="ts">
/**
 * 知乎排名页 —— 历史报告 tab 的「知乎排名」子页。
 * 数据从 GET /api/monitor/history/zhihu-ranking?range=1d|7d|30d。
 * drill-down 行点击 emit('navigate', {taskId})。
 */
import { ref, computed, onMounted, watch } from "vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import LineChart from "./LineChart.vue";

type Range = "1d" | "7d" | "30d";
type ChangeKind = "down" | "up" | "new" | "dropped" | "flat";
type Filter = "all" | "down" | "up" | "new" | "dropped";

interface Kpis {
  monitored_questions: number;
  questions_added_this_week: number;
  brands_covered: number;
  avg_share_today: number;
  avg_share_prev: number;
  hit_count_total: number;
  topn_total: number;
  changed_questions: number;
  changed_up: number;
  changed_down: number;
}
interface DailyPoint {
  date: string;
  avg_share: number;
  changed_count: number;
  changed_up: number;
  changed_down: number;
}
interface Question {
  task_id: number;
  title: string;
  target_brand: string;
  matched_count: number;
  matched_count_prev: number | null;
  top_n: number;
  matched_ranks: number[];
  best_rank: number;
  best_rank_prev: number | null;
  change_kind: ChangeKind;
  checked_at: string | null;
}
interface ZhihuResponse {
  range: Range;
  kpis: Kpis;
  daily_series: DailyPoint[];
  questions: Question[];
}

const emit = defineEmits<{ navigate: [payload: { taskId: number }] }>();

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();
const range = ref<Range>("7d");
const data = ref<ZhihuResponse | null>(null);
const loading = ref(false);
const filter = ref<Filter>("all");

async function load() {
  loading.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/zhihu-ranking", {
      params: { range: range.value },
    });
    data.value = r.data;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const filtered = computed<Question[]>(() => {
  if (!data.value) return [];
  if (filter.value === "all") return data.value.questions;
  return data.value.questions.filter((q) => q.change_kind === filter.value);
});

const chartLabels = computed(() =>
  (data.value?.daily_series ?? []).map((d) => d.date.slice(5)),
);
const chartSeries = computed(() => {
  if (!data.value) return [];
  return [
    { label: "占有率 %", color: "#ee6a2a", data: data.value.daily_series.map((d) => Math.round(d.avg_share * 100)) },
    { label: "异动问题数", color: "#1e1c19", data: data.value.daily_series.map((d) => d.changed_count) },
  ];
});

function fmtPct(x: number): string { return `${Math.round(x * 100)}%`; }
function fmtDeltaPts(curr: number, prev: number) {
  const diff = Math.round((curr - prev) * 100);
  if (diff > 0) return { text: `↑ ${diff} pts`, tone: "up" as const };
  if (diff < 0) return { text: `↓ ${Math.abs(diff)} pts`, tone: "down" as const };
  return { text: "持平", tone: "flat" as const };
}
function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function arrowFor(kind: ChangeKind): { glyph: string; color: string } {
  if (kind === "up" || kind === "new") return { glyph: "▲", color: "#5e7848" };
  if (kind === "down" || kind === "dropped") return { glyph: "▼", color: "var(--red)" };
  return { glyph: "—", color: "#a89f8d" };
}
function rankChangeText(q: Question): { text: string; tone: "up" | "down" | "flat" } {
  if (q.change_kind === "dropped") return { text: `#${q.best_rank_prev} → 无`, tone: "down" };
  if (q.change_kind === "new") return { text: `无 → #${q.best_rank}`, tone: "up" };
  if (q.best_rank_prev == null) return { text: "首次", tone: "flat" };
  if (q.best_rank === q.best_rank_prev) return { text: `#${q.best_rank} 持平`, tone: "flat" };
  const tone = q.best_rank < q.best_rank_prev ? "up" : "down";
  return { text: `#${q.best_rank_prev} → #${q.best_rank}`, tone };
}
</script>

<template>
  <div v-if="loading && !data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">加载中…</div>
  <div v-else-if="!data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">暂无数据</div>
  <div v-else class="flex flex-col gap-3">
    <!-- range picker -->
    <div class="flex items-center justify-between flex-shrink-0">
      <div>
        <div class="font-display text-[14px] font-semibold">知乎排名 · 品牌占有率分析</div>
        <div class="text-[11px] mt-0.5" :style="{ color: 'var(--ink-3)' }">看品牌在监测问题里的占位变化、谁掉了 / 谁起来了</div>
      </div>
      <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card)', border: '1px solid var(--line)' }">
        <button
          v-for="r in (['1d','7d','30d'] as Range[])" :key="r"
          @click="range = r"
          class="px-3.5 py-1 rounded-full text-[12px] font-medium"
          :style="{
            background: range === r ? 'var(--dark)' : 'transparent',
            color: range === r ? 'var(--card)' : 'var(--ink-3)',
          }"
        >{{ r === "1d" ? "最近 1 天" : r === "7d" ? "最近 7 天" : "最近 30 天" }}</button>
      </div>
    </div>

    <!-- 3 KPI -->
    <div class="grid grid-cols-3 gap-2.5">
      <!-- KPI 1: 监测问题数 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">监测问题数</div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.monitored_questions }}</div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          覆盖品牌词 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.brands_covered }}</b> 个
        </div>
      </div>
      <!-- KPI 2: 品牌占有率均值 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="flex justify-between items-start">
          <div class="flex items-center gap-1.5 text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">
            <span :style="{ width: '8px', height: '8px', borderRadius: '50%', background: '#ee6a2a' }" />
            品牌占有率（平均）
          </div>
          <span
            class="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            :style="{
              background: fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'down' ? 'rgba(216,90,72,0.12)' :
                          fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'up'   ? 'rgba(122,155,94,0.15)' : 'rgba(28,26,23,0.05)',
              color: fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'down' ? 'var(--red)' :
                     fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'up'   ? '#5e7848' : 'var(--ink-3)',
            }"
          >{{ fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).text }}</span>
        </div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ fmtPct(data.kpis.avg_share_today) }}</div>
        <Sparkline
          v-if="range !== '1d' && data.daily_series.length > 0"
          :values="data.daily_series.map((d) => d.avg_share * 100)"
          color="#ee6a2a"
          :height="28"
        />
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          命中位 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.hit_count_total }}</b> / {{ data.kpis.topn_total }}
        </div>
      </div>
      <!-- KPI 3: 异动问题数 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">排名异动问题</div>
        <div class="flex items-baseline gap-2">
          <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.changed_questions }}</div>
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
            <span :style="{ color: 'var(--red)' }">↓ {{ data.kpis.changed_down }}</span>
            <span class="mx-1">·</span>
            <span :style="{ color: '#5e7848' }">↑ {{ data.kpis.changed_up }}</span>
          </div>
        </div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">近 {{ range === "1d" ? "1 天" : range === "7d" ? "7 天" : "30 天" }}累计</div>
      </div>
    </div>

    <!-- 主图（1d 时隐藏） -->
    <div
      v-if="range !== '1d'"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
    >
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">占有率与异动趋势</div>
        <div class="flex gap-3 text-[11px]" :style="{ color: 'var(--ink-2)' }">
          <span><span :style="{ display:'inline-block', width:'8px', height:'8px', background:'#ee6a2a', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />占有率 %</span>
          <span><span :style="{ display:'inline-block', width:'8px', height:'8px', background:'#1e1c19', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />异动问题数</span>
        </div>
      </div>
      <LineChart :labels="chartLabels" :series="chartSeries" dual-axis />
    </div>

    <!-- 问题列表 -->
    <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '12px' }">
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">
          问题列表 <span class="font-normal" :style="{ color: 'var(--ink-3)' }">({{ filtered.length }} 条 · 点行进详情)</span>
        </div>
        <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)' }">
          <button
            v-for="f in (['all','down','up','new','dropped'] as Filter[])" :key="f"
            @click="filter = f"
            class="px-3 py-1 rounded-full text-[11.5px] font-medium"
            :style="{
              background: filter === f ? 'var(--dark)' : 'transparent',
              color: filter === f ? 'var(--card)' : 'var(--ink-3)',
            }"
          >
            {{ f === "all" ? "全部" : f === "down" ? "↓ 下降" : f === "up" ? "↑ 上升" : f === "new" ? "新上榜" : "掉出 Top" }}
          </button>
        </div>
      </div>
      <div v-if="!filtered.length" class="py-6 text-center text-[12px]" :style="{ color: 'var(--ink-3)' }">无符合条件的问题</div>
      <div v-else>
        <div
          v-for="q in filtered" :key="q.task_id"
          @click="emit('navigate', { taskId: q.task_id })"
          class="grid items-center gap-2.5 cursor-pointer"
          :style="{
            gridTemplateColumns: '24px 1.6fr 100px 110px 80px 18px',
            padding: '9px 12px',
            fontSize: '11.5px',
            borderRadius: '8px',
            borderTop: '1px solid rgba(28,26,23,0.06)',
          }"
          @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
          @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <div class="text-[14px] text-center" :style="{ color: arrowFor(q.change_kind).color }">{{ arrowFor(q.change_kind).glyph }}</div>
          <div>
            <div :style="{ color: 'var(--ink)' }">{{ q.title }}</div>
            <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
              target:
              <span class="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10.5px]"
                :style="{ background: 'rgba(238,106,42,0.12)', color: '#c9521f' }">{{ q.target_brand }}</span>
              <span v-if="q.matched_ranks.length"> · 命中位 {{ q.matched_ranks.map((r) => "#" + r).join(" ") }} ({{ q.matched_count }}/{{ q.top_n }})</span>
            </div>
          </div>
          <div>
            <div class="text-[12px] font-semibold">{{ q.matched_count }} / {{ q.top_n }}</div>
            <div :style="{ height: '6px', background: 'rgba(28,26,23,0.06)', borderRadius: '3px', overflow: 'hidden', marginTop: '4px' }">
              <div :style="{ height: '100%', background: '#ee6a2a', borderRadius: '3px', width: `${Math.min(100, (q.matched_count / q.top_n) * 100)}%` }" />
            </div>
          </div>
          <div>
            <span
              class="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium"
              :style="{
                background: rankChangeText(q).tone === 'up' ? 'rgba(122,155,94,0.15)' :
                            rankChangeText(q).tone === 'down' ? 'rgba(216,90,72,0.12)' : 'rgba(28,26,23,0.05)',
                color: rankChangeText(q).tone === 'up' ? '#5e7848' :
                       rankChangeText(q).tone === 'down' ? 'var(--red)' : 'var(--ink-3)',
              }"
            >{{ rankChangeText(q).text }}</span>
          </div>
          <div :style="{ color: 'var(--ink-3)' }">{{ fmtTime(q.checked_at) }}</div>
          <div class="text-[16px] text-center" :style="{ color: 'var(--ink-4)', lineHeight: 1 }">›</div>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/monitor/history/ZhihuRankingPage.vue
git commit -m "$(cat <<'EOF'
feat(history): add ZhihuRankingPage component

知乎排名页：range picker + 3 KPI（监测数 / 占有率 / 异动数）+
双轴主图（占有率% 左轴 + 异动数 右轴）+ 问题列表（5 种过滤）。
每行带 ▲▼— 方向标 + 占有率进度条 + 排名变化 chip。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 整合到 MonitorView.vue（sub-pivot + mount + navigate 回调）

**Files:**
- Modify: `frontend/src/views/MonitorView.vue`

- [ ] **Step 1: 加 import + ref**

In `MonitorView.vue` script section, near other component imports (around line 50-60), add:

```ts
import RetentionPage from "@/components/monitor/history/RetentionPage.vue";
import ZhihuRankingPage from "@/components/monitor/history/ZhihuRankingPage.vue";
import { nextTick } from "vue";
```

Near where `commentSubtab` is defined (line ~74), add:

```ts
type HistorySubtab = "retention" | "zhihu";
const historySubtab = ref<HistorySubtab>("retention");
```

- [ ] **Step 2: 写两个 navigate 回调**

Near `runBatch` / `batchRunState` (around line ~970-980, after the recent batch button feature work), add:

```ts
// 历史报告 drill-down 跳转 ── RetentionPage 行点击 emit navigate({platform, batchName, taskId}) → 这里。
// 切到平台评论 tab、平台 chip、批次 L2、视频 L3。靠 nextTick 等
// watch(activeTab) / watch(commentSubtab) 的 atomic-load 跑完
// 再设 selectedCommentTaskId/selectedVideoId，否则 atomic-load
// 内部的「selectedTaskId.value = newTasks[0].id」会盖掉我们的设置。
async function goToCommentTask(payload: {
  platform: "bilibili_comment" | "douyin_comment" | "kuaishou_comment";
  batchName: string;
  taskId: number;
}) {
  const subtabKey: CommentPlatform =
    payload.platform === "bilibili_comment" ? "bilibili"
    : payload.platform === "douyin_comment" ? "douyin"
    : "kuaishou";
  activeTab.value = "comment";
  commentSubtab.value = subtabKey;
  await nextTick();
  await nextTick();  // 一个 tick 不够；watch handler 是 async，等两 tick 让 atomic load 跑完
  selectedCommentTaskId.value = payload.batchName;
  selectedVideoId.value = `task-${payload.taskId}`;
}

async function goToZhihuTask(payload: { taskId: number }) {
  activeTab.value = "zhihu";
  await nextTick();
  await nextTick();
  selectedTaskId.value = payload.taskId;
}
```

- [ ] **Step 3: 替换历史报告 tab 整段 template**

Find the 历史报告 template block (line ~3137-3220 or so, starts with `<!-- ── 历史报告 ─────...`) and replace it entirely with:

```vue
<!-- ── 历史报告（重构后：sub-pivot + 两个子页）──────────────────── -->
<template v-else>
  <section
    class="flex min-h-0 flex-1 flex-col"
    :style="{
      background: 'var(--card)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-card)',
      padding: '22px',
    }"
  >
    <!-- sub-pivot：评论留存率 / 知乎排名 -->
    <div class="mb-3 flex-shrink-0 flex justify-between items-center">
      <div>
        <div class="font-display text-[14px] font-semibold">历史监测报告</div>
        <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
          按业务拆分：评论平台留存率 / 知乎品牌排名分析
        </div>
      </div>
      <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }">
        <button
          @click="historySubtab = 'retention'"
          class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
          :style="{
            background: historySubtab === 'retention' ? 'var(--dark)' : 'transparent',
            color: historySubtab === 'retention' ? 'var(--card)' : 'var(--ink-3)',
          }"
        >评论留存率</button>
        <button
          @click="historySubtab = 'zhihu'"
          class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
          :style="{
            background: historySubtab === 'zhihu' ? 'var(--dark)' : 'transparent',
            color: historySubtab === 'zhihu' ? 'var(--card)' : 'var(--ink-3)',
          }"
        >知乎排名</button>
      </div>
    </div>

    <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <RetentionPage v-if="historySubtab === 'retention'" @navigate="goToCommentTask" />
      <ZhihuRankingPage v-else @navigate="goToZhihuTask" />
    </div>
  </section>
</template>
```

- [ ] **Step 4: 验证 HMR 无错**

The dev server is already running (Tauri / Vite). Wait a moment and tail vite log:

```bash
tail -10 /c/Users/EDY/AppData/Local/Temp/claude/D--CSM--claude-worktrees-nostalgic-pare-def8f0/d5a922ac-9e76-42e2-8607-bde02839270e/tasks/bdfipus63.output 2>/dev/null | grep -E "hmr|error"
```

Expected: HMR update success lines, no error

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/MonitorView.vue
git commit -m "$(cat <<'EOF'
feat(history): mount RetentionPage + ZhihuRankingPage in 历史报告 tab

新增 historySubtab ref 切换两个子页；navigate 事件回调链到既有
activeTab/commentSubtab/selectedCommentTaskId/selectedVideoId
（及知乎的 selectedTaskId），双 nextTick 等 atomic-load 跑完
再下钻 L3。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 删除旧 reports + AlertDetailModal `history_report` 分支

**Files:**
- Modify: `frontend/src/views/MonitorView.vue`
- Modify: `frontend/src/components/monitor/AlertDetailModal.vue`
- Modify: `docs/migration/feature-ui-mapping.md`

- [ ] **Step 1: 删 MonitorView 里 reports 相关代码**

在 `frontend/src/views/MonitorView.vue` 删除以下符号 / template：

1. `reports` ref（搜 `const reports = ref(`，删整行）
2. `SAMPLE_REPORTS`（搜 `const SAMPLE_REPORTS =`，删整段定义）
3. `loadReports()` 函数（搜 `async function loadReports`，删整个函数体）
4. `openReport()` 函数（搜 `function openReport`，删整个函数）
5. `selectedReport` ref（搜 `const selectedReport = ref(`，删整个 ref 含 type 定义）
6. `alertKind` 联合类型里 `"history_report"`（搜 `"history_report"`，把这个 literal 从 alertKind ref 的类型里去掉）
7. `await loadReports()` 调用（应该在两处，line ~976 和 line ~1371 watch 里。把 `} else { await loadReports() }` 改成 `} else { /* nothing — history page self-loads */ }`）
8. AlertDetailModal 的 `:report="selectedReport ?? undefined"` 这个 prop binding（搜 `:report="selectedReport`，删整个 prop）

- [ ] **Step 2: 删 AlertDetailModal `history_report` 分支**

In `frontend/src/components/monitor/AlertDetailModal.vue`:

1. 从 `Kind` 类型里去掉 `"history_report"`：`type Kind = "zhihu_alert" | "comment_alert";`
2. 删除 `HistoryReportProps` interface 定义和 `report?: HistoryReportProps` prop
3. 删除 `report:` 派生 computed（搜 `by = props.report?.by_platform`）
4. 删除 template 里所有 `v-if="kind === 'history_report'"` / `v-else-if="kind === 'history_report'"` 分支整块（应该有 3-4 处条件染色样式）
5. 文件头注释里把 `kind="history_report" 历史监测报告` 那一行删掉

- [ ] **Step 3: 更新 migration 文档**

In `docs/migration/feature-ui-mapping.md`, find the row mentioning `历史监测报告` and replace its description column to:

```
历史监测报告（重构）→ 拆分为「评论留存率」/「知乎排名」两个 sub-page；旧 /api/monitor/reports 端点废弃，由 /api/monitor/history/comment-retention 与 .../zhihu-ranking 接管。
```

- [ ] **Step 4: 验证 HMR 无错 + 视觉无残留**

`tail` vite log 看 HMR 是否 OK。然后浏览器/Tauri 端切到「历史报告」tab，确认两个子 pivot 都能正常打开（数据可能没有，但 UI 骨架要出现）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/MonitorView.vue \
        frontend/src/components/monitor/AlertDetailModal.vue \
        docs/migration/feature-ui-mapping.md
git commit -m "$(cat <<'EOF'
refactor(history): remove legacy reports table and AlertDetailModal history_report mode

旧的单一 reports 表 + AlertDetailModal 的 history_report kind 分支
都已被新的两个 sub-page（RetentionPage / ZhihuRankingPage）替代。
clearEditOnClose、selectedReport ref、openReport 等同伴代码一并清掉。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 重打 sidecar + 端到端手动验证

**Files:** （不改文件）

- [ ] **Step 1: 杀掉现有 Tauri dev 进程**

确保用户的当前 Tauri dev 不再占用 sidecar binary：

```bash
tasklist | grep -iE "csm-tauri|csm-sidecar" 2>&1 | awk '{print $2}' | xargs -r -I {} powershell -NoProfile -Command "Stop-Process -Id {} -Force -ErrorAction SilentlyContinue"
```

确认 vite 端口空：

```bash
netstat -ano | grep ":5173 " | grep LISTENING
# 若有进程占用，kill 它
```

- [ ] **Step 2: 重打 PyInstaller sidecar**

```bash
python scripts/build_sidecar.py --clean
```

Expected: 5-10 分钟，产物 `frontend/src-tauri/binaries/csm-sidecar-x86_64-pc-windows-msvc.exe` 更新

- [ ] **Step 3: 重启 Tauri dev**

```bash
cd frontend && npm run tauri:dev
```

等 sidecar handshake 日志：`sidecar handshake received: port=XXXX version=1`

- [ ] **Step 4: 走 spec 里的验证清单**

切到「历史报告 → 评论留存率」：
- [ ] 顶部 sub-pivot 高亮「评论留存率」
- [ ] range picker 默认 7d
- [ ] 切 1d 隐藏折线 + sparkline，KPI 卡仍在
- [ ] 切 30d 折线点更密
- [ ] 3 KPI 卡显示各平台 retained/total/delta/sparkline
- [ ] 主图三条线，hover 显示三平台同日值
- [ ] drill-down 表行可点 → 跳到「平台评论 → 对应平台 → 对应批次 → L3 视频详情」

切到「历史报告 → 知乎排名」：
- [ ] 3 KPI 卡显示问题数 / 平均占有率 / 异动问题数
- [ ] 主图双轴线（占有率% 左轴 / 异动数 右轴）
- [ ] 筛选 pill 切换正确过滤
- [ ] drill-down 表行可点 → 跳到「知乎问题 → 该任务 L2」

跨页：
- [ ] 历史报告 ↔ 平台评论 ↔ 知乎问题 三 tab 切换不闪动
- [ ] 跳转后再返回历史报告，sub-pivot 状态保留

任何一项不通过 → 停下查问题，修后回到 Step 1 重打。

- [ ] **Step 5: 全 sidecar 测试再跑一遍兜底**

```bash
cd sidecar && python -m pytest tests/ -v
```

Expected: 全 PASS（含 Task 1 / Task 2 新增的 9 个测试，旧 reports 测试已删除）

---

## Self-Review Result

**Spec coverage：**
- 「sub-pivot 切换」→ Task 7 Step 3
- 「评论留存率页（KPI / chart / table / 1d 视图）」→ Task 5
- 「知乎排名页（KPI / 双轴图 / 5 种过滤）」→ Task 6
- 「跳转回调实现」→ Task 7 Step 2
- 「后端聚合接口（comment-retention）」→ Task 1
- 「后端聚合接口（zhihu-ranking）」→ Task 2 含 `change_kind` 五分类规则
- 「Chart.js 引入 + LineChart 通用组件」→ Task 4
- 「删除清单 7 项」→ Task 3（后端）+ Task 8（前端 + 文档）
- 「测试策略（pytest）」→ Task 1+2 共 9 个用例覆盖空 DB / 按日 bucket / dedup / change_kind / KPI 聚合 / invalid range
- 「文件大小约束（不挤进 MonitorView）」→ Task 5/6 拆独立组件文件 + 后端 history_service.py 拆出来不挤 monitor_service.py

**Placeholder scan：** 无 TBD / TODO；所有代码块都是完整可粘贴片段。`questions_added_this_week` 这个字段在 spec 是 v0 占位（暂返 0），Task 2 实现里写明了「v0 不算，避免再多一次查询」，是 honest scoping 不是 placeholder。

**Type consistency：**
- `PlatformKey` / `ChangeKind` / `Range` / `Filter` 在 Task 5/6 一致
- emit 名 `'navigate'` 跨两组件一致
- 后端 response 字段（`platforms`/`events`/`kpis`/`daily_series`/`questions`/`change_kind`）跨 Task 1/2 与前端 Task 5/6 一一对应
- `goToCommentTask` 接 `{platform, batchName, taskId}`、`goToZhihuTask` 接 `{taskId}`，跟两组件 emit payload 同形

**测试缺位声明：** 仓库前端无 vitest/jest（已在批量立刻监测计划里确认过），所以本次新增的前端三个组件文件不写自动化测，靠 Task 9 的端到端手动验证清单兜底——跟仓库前端验证现状一致。
