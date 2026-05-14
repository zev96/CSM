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
