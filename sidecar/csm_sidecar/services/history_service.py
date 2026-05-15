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
            "best_rank": int(min(m["matched_ranks"])) if m.get("matched_ranks") else -1,
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

    Per-task per-day = the latest result whose ``checked_at < day_end`` —
    i.e. the most recent observation on or before that day. Days before a
    task's first observation contribute nothing; days after carry forward
    the latest known state until the next observation lands. Aggregated
    across tasks for each bucket.
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
            # 当天的 prev：当天 day_start 之前最近一次。注意这跟 questions[]
            # 列表里的 prev（取「倒数第二条 result」无视日期）语义不一样
            # ——同一 task 当天跑了两次，daily_series 算 flat（午夜前无 prev）
            # 而 questions[] 可能算 up/down。这是有意为之：日级别系列要稳定
            # 反映「跨天的变化」，不被同一天的两次抓取扰动。
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


def get_baidu_keyword_history(range_str: str) -> dict[str, Any]:
    """KPI + 每日趋势 + 全量关键词列表（前端按 change_kind 自行 filter）。

    Mirrors get_zhihu_ranking_history but adapted for baidu_keyword tasks.
    Metric fields:
      - default_matched_count  → matched_count
      - default_first_rank     → best_rank (positive int or -1)
      - default_results        → list of result dicts, derive matched_ranks
      - target_brands          → list[str]
      - news_present           → bool
      - captcha_hit            → bool
    """
    range_days = _parse_range(range_str)
    now = datetime.now()
    conn = storage.get_conn()
    rows = conn.execute(
        """
        SELECT r.task_id, r.checked_at, r.status, r.rank, r.metric_json,
               t.id AS t_id, t.name AS task_name, t.config_json
        FROM monitor_results r
        JOIN monitor_tasks t ON t.id = r.task_id
        WHERE t.type = 'baidu_keyword'
          AND t.enabled = 1
          AND r.status = 'ok'
        ORDER BY r.task_id ASC, r.checked_at DESC
        """,
    ).fetchall()
    all_tasks = conn.execute(
        "SELECT id, name, config_json FROM monitor_tasks "
        "WHERE type='baidu_keyword' AND enabled=1",
    ).fetchall()

    per_task: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        m = json.loads(row["metric_json"] or "{}")
        checked = storage._parse_iso(row["checked_at"])  # noqa: SLF001
        if not checked:
            continue
        default_results = m.get("default_results") or []
        matched_ranks = [r["rank"] for r in default_results if r.get("matches_brand")]
        per_task[row["task_id"]].append({
            "checked_at": checked,
            "matched_count": int(m.get("default_matched_count") or 0),
            "matched_ranks": matched_ranks,
            "best_rank": int(m.get("default_first_rank") or -1),
            "top_n": 10,
            "target_brands": list(m.get("target_brands") or []),
            "news_present": bool(m.get("news_present")),
            "captcha_hit": bool(m.get("captcha_hit")),
            "task_name": row["task_name"],
        })

    keywords = []
    for t in all_tasks:
        cfg = json.loads(t["config_json"] or "{}")
        results = per_task.get(t["id"], [])
        curr = results[0] if results else None
        prev = results[1] if len(results) > 1 else None
        # Reuse _classify_zhihu_change — same matched_count + best_rank semantics.
        kind, _ = _classify_zhihu_change(curr, prev)
        target_brands = (curr or {}).get("target_brands") or list(cfg.get("target_brands") or [])
        keywords.append({
            "task_id": t["id"],
            "search_keyword": cfg.get("search_keyword", t["name"]),
            "task_name": t["name"],
            "target_brands": target_brands,
            "matched_count": (curr or {}).get("matched_count", 0),
            "matched_count_prev": (prev or {}).get("matched_count", 0) if prev else None,
            "top_n": 10,
            "matched_ranks": (curr or {}).get("matched_ranks", []),
            "best_rank": (curr or {}).get("best_rank", -1),
            "best_rank_prev": (prev or {}).get("best_rank", -1) if prev else None,
            "change_kind": kind,
            "news_present": (curr or {}).get("news_present", False),
            "captcha_hit": (curr or {}).get("captcha_hit", False),
            "checked_at": (curr["checked_at"].isoformat() if curr else None),
        })

    # KPIs
    monitored = len(keywords)
    hit_count_total = sum(k["matched_count"] for k in keywords)
    topn_total = monitored * 10
    avg_match_rate_today = (hit_count_total / topn_total) if topn_total else 0.0
    hit_count_prev = sum((k["matched_count_prev"] or 0) for k in keywords if k["matched_count_prev"] is not None)
    topn_prev_total = sum(10 for k in keywords if k["matched_count_prev"] is not None)
    avg_match_rate_prev = (hit_count_prev / topn_prev_total) if topn_prev_total else 0.0

    changed_down = sum(1 for k in keywords if k["change_kind"] in ("down", "dropped"))
    changed_up = sum(1 for k in keywords if k["change_kind"] in ("up", "new"))
    changed_total = changed_down + changed_up

    captcha_count = sum(1 for k in keywords if k["captcha_hit"])
    news_present_count = sum(1 for k in keywords if k["news_present"])

    # Distinct brand words across all tasks
    all_brands: set[str] = set()
    for k in keywords:
        all_brands.update(k["target_brands"])
    brands_covered = len(all_brands)

    # Daily series — reuse _zhihu_daily_series (per_task dicts have same keys)
    daily_series_raw = _zhihu_daily_series(per_task, range_days=range_days, now=now)
    # Rename avg_share → avg_match_rate for baidu
    daily_series = [
        {
            "date": d["date"],
            "avg_match_rate": d["avg_share"],
            "changed_count": d["changed_count"],
            "changed_up": d["changed_up"],
            "changed_down": d["changed_down"],
        }
        for d in daily_series_raw
    ]

    return {
        "range": range_str,
        "kpis": {
            "monitored_keywords": monitored,
            "brands_covered": brands_covered,
            "avg_match_rate_today": avg_match_rate_today,
            "avg_match_rate_prev": avg_match_rate_prev,
            "hit_count_total": hit_count_total,
            "topn_total": topn_total,
            "changed_keywords": changed_total,
            "changed_up": changed_up,
            "changed_down": changed_down,
            "captcha_count": captcha_count,
            "news_present_count": news_present_count,
        },
        "daily_series": daily_series,
        "keywords": keywords,
    }


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
