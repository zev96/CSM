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


def get_geo_exposure_summary(range_str: str) -> dict[str, Any]:
    """全部 geo 任务近 range 天的全局曝光率 + 较上一窗口 delta（首页 GEO 仪表盘卡）。

    soc = Σmentioned / Σok_cells（全局口径，跨所有 geo 任务，复用 geo.metrics 的
    soc 定义与 band 阈值 0.2/0.5）。soc_prev 取上一个同长窗口，delta = soc - soc_prev。
    """
    range_days = _parse_range(range_str)
    from csm_core.monitor.geo import storage as geo_storage
    from csm_core.monitor.geo.metrics import band

    m_cur, ok_cur = geo_storage.exposure_window(range_days, offset_days=0)
    m_prev, ok_prev = geo_storage.exposure_window(range_days, offset_days=range_days)
    soc = (m_cur / ok_cur) if ok_cur else 0.0
    soc_prev = (m_prev / ok_prev) if ok_prev else 0.0
    return {
        "range": range_str,
        "soc": round(soc, 4),
        "soc_prev": round(soc_prev, 4),
        "delta": round(soc - soc_prev, 4),
        "band": band(soc),          # hidden / weak / strong
        "mentioned": m_cur,
        "ok_cells": ok_cur,
    }


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

    新数据模型：config.search_keywords (list) + config.target_brand (str)。
    keywords[] 是 (task, keyword) 的笛卡尔展开，每行一个关键词。

    Metric fields (new shape):
      - keywords[].default_matched_count  → per-keyword matched count
      - keywords[].default_first_rank     → per-keyword best rank
      - keywords[].default_results        → list of result dicts
      - keywords[].news_present           → bool
      - target_brand                      → single brand str
      - captcha_hit                       → bool (task-level)
      - best_default_first_rank           → task-level aggregation
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

    # per_task: task_id → list of result dicts in checked_at DESC order
    # Each entry represents one full task run (covers all keywords in that run).
    per_task: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        m = json.loads(row["metric_json"] or "{}")
        checked = storage._parse_iso(row["checked_at"])  # noqa: SLF001
        if not checked:
            continue
        per_task[row["task_id"]].append({
            "checked_at": checked,
            "metric": m,
            "task_name": row["task_name"],
        })

    keyword_rows = []
    captcha_set: set[int] = set()   # task_ids whose latest result had captcha_hit
    news_present_kw_count = 0

    for t in all_tasks:
        cfg = json.loads(t["config_json"] or "{}")
        results = per_task.get(t["id"], [])
        curr_result = results[0] if results else None
        prev_result = results[1] if len(results) > 1 else None

        curr_m = curr_result["metric"] if curr_result else {}
        prev_m = prev_result["metric"] if prev_result else {}

        # Task-level captcha flag from latest result
        if curr_m.get("captcha_hit"):
            captcha_set.add(t["id"])

        # Enumerate per-keyword entries from config (so tasks with 0 results
        # still appear in the list with curr=None)
        search_keywords = list(cfg.get("search_keywords") or [])
        target_brand = cfg.get("target_brand", "")

        # If no keywords in config, fall back to metric for backwards compat
        if not search_keywords and curr_m.get("search_keywords"):
            search_keywords = list(curr_m["search_keywords"])

        for kw in search_keywords:
            # Find per-keyword entry in curr and prev metrics
            curr_kw = _find_keyword_entry(curr_m, kw)
            prev_kw = _find_keyword_entry(prev_m, kw)

            curr_matched = curr_kw["default_matched_count"] if curr_kw else 0
            curr_best = curr_kw["default_first_rank"] if curr_kw else -1
            prev_matched = prev_kw["default_matched_count"] if prev_kw else None
            prev_best = prev_kw["default_first_rank"] if prev_kw else None

            # Build synthetic curr/prev dicts for _classify_zhihu_change
            _curr = {"matched_count": curr_matched, "best_rank": curr_best, "top_n": 10} if curr_kw else None
            _prev = {"matched_count": (prev_matched or 0), "best_rank": (prev_best or -1), "top_n": 10} if prev_kw else None
            kind, _ = _classify_zhihu_change(_curr, _prev)

            default_results = (curr_kw or {}).get("default_results") or []
            matched_ranks = [r["rank"] for r in default_results if r.get("matches_brand")]

            # 资讯卡位 —— news SERP 里命中目标品牌的条数；UI 「资讯卡位」列
            # 直接读这个值，没命中显示"无"。
            news_results = (curr_kw or {}).get("news_results") or []
            news_matched_count = sum(1 for r in news_results if r.get("matches_brand"))

            news_present_flag = bool((curr_kw or {}).get("news_present"))
            if news_present_flag:
                news_present_kw_count += 1

            keyword_rows.append({
                "task_id": t["id"],
                "task_name": t["name"],
                "search_keyword": kw,
                "target_brand": target_brand,
                "matched_count": curr_matched,
                "matched_count_prev": prev_matched,
                "news_matched_count": news_matched_count,
                "top_n": 10,
                "matched_ranks": matched_ranks,
                "best_rank": curr_best,
                "best_rank_prev": prev_best,
                "change_kind": kind,
                "checked_at": (curr_result["checked_at"].isoformat() if curr_result else None),
            })

    # KPIs
    monitored_keywords = len(keyword_rows)
    hit_count_total = sum(k["matched_count"] for k in keyword_rows)
    topn_total = monitored_keywords * 10
    avg_match_rate_today = (hit_count_total / topn_total) if topn_total else 0.0
    hit_count_prev = sum((k["matched_count_prev"] or 0) for k in keyword_rows if k["matched_count_prev"] is not None)
    topn_prev_total = sum(10 for k in keyword_rows if k["matched_count_prev"] is not None)
    avg_match_rate_prev = (hit_count_prev / topn_prev_total) if topn_prev_total else 0.0

    changed_down = sum(1 for k in keyword_rows if k["change_kind"] in ("down", "dropped"))
    changed_up = sum(1 for k in keyword_rows if k["change_kind"] in ("up", "new"))
    changed_total = changed_down + changed_up

    # Distinct brand values across tasks
    brands_covered = len({
        json.loads(t["config_json"] or "{}").get("target_brand", "")
        for t in all_tasks
        if json.loads(t["config_json"] or "{}").get("target_brand")
    })

    captcha_count = len(captcha_set)

    # Daily series — build per-keyword-row series using (task_id, keyword) as unit
    daily_series = _baidu_daily_series(per_task, all_tasks, range_days=range_days, now=now)

    return {
        "range": range_str,
        "kpis": {
            "monitored_keywords": monitored_keywords,
            "brands_covered": brands_covered,
            "avg_match_rate_today": avg_match_rate_today,
            "avg_match_rate_prev": avg_match_rate_prev,
            "hit_count_total": hit_count_total,
            "topn_total": topn_total,
            "changed_keywords": changed_total,
            "changed_up": changed_up,
            "changed_down": changed_down,
            "captcha_count": captcha_count,
            "news_present_count": news_present_kw_count,
        },
        "daily_series": daily_series,
        "keywords": keyword_rows,
    }


def _find_keyword_entry(metric: dict, keyword: str) -> dict | None:
    """Find the per-keyword sub-result in a metric dict by keyword string."""
    kw_list = metric.get("keywords") or []
    for entry in kw_list:
        if entry.get("keyword") == keyword:
            return entry
    return None


def _baidu_daily_series(
    per_task: dict[int, list[dict]],
    all_tasks: list,
    *,
    range_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Per-day series for baidu: avg_match_rate + change counts.

    For each day, we aggregate across all (task, keyword) pairs: the
    latest result on or before that day's end contributes its per-keyword
    matched_count / 10 to the avg_match_rate bucket.
    """
    series = []
    # Build task→keywords map from config
    task_keywords: dict[int, list[str]] = {}
    for t in all_tasks:
        cfg = json.loads(t["config_json"] or "{}")
        kws = list(cfg.get("search_keywords") or [])
        task_keywords[t["id"]] = kws

    for d in range(range_days):
        day = (now - timedelta(days=range_days - 1 - d)).date()
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        hits = 0
        topn = 0
        changed_up = changed_down = 0

        for task_id, results in per_task.items():
            keywords_for_task = task_keywords.get(task_id, [])
            # results is DESC by checked_at; find latest on or before day_end
            curr_on_day = next((r for r in results if r["checked_at"] < day_end), None)
            if not curr_on_day:
                continue
            prev_for_day = next((r for r in results if r["checked_at"] < day_start), None)

            curr_m = curr_on_day["metric"]
            prev_m = prev_for_day["metric"] if prev_for_day else {}

            for kw in keywords_for_task:
                curr_kw = _find_keyword_entry(curr_m, kw)
                prev_kw = _find_keyword_entry(prev_m, kw)
                if curr_kw is None:
                    continue
                c_matched = curr_kw.get("default_matched_count", 0)
                c_best = curr_kw.get("default_first_rank", -1)
                hits += c_matched
                topn += 10

                _curr = {"matched_count": c_matched, "best_rank": c_best, "top_n": 10}
                _prev = None
                if prev_kw:
                    _prev = {"matched_count": prev_kw.get("default_matched_count", 0),
                             "best_rank": prev_kw.get("default_first_rank", -1), "top_n": 10}
                kind, _ = _classify_zhihu_change(_curr, _prev)
                if kind in ("up", "new"):
                    changed_up += 1
                elif kind in ("down", "dropped"):
                    changed_down += 1

        series.append({
            "date": day.strftime("%Y-%m-%d"),
            "avg_match_rate": (hits / topn) if topn else 0.0,
            "changed_count": changed_up + changed_down,
            "changed_up": changed_up,
            "changed_down": changed_down,
        })
    return series


def get_zhihu_search_history(range_str: str) -> dict[str, Any]:
    """知乎搜索 KPI + 每日趋势 + (task×keyword) 关键词列表。

    镜像 get_baidu_keyword_history，但读 zhihu_search 字段名
    (matched_count / first_rank)。每行 = 一个 (task, search_keyword)。
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
        WHERE t.type = 'zhihu_search' AND t.enabled = 1 AND r.status = 'ok'
        ORDER BY r.task_id ASC, r.checked_at DESC
        """,
    ).fetchall()
    all_tasks = conn.execute(
        "SELECT id, name, config_json FROM monitor_tasks WHERE type='zhihu_search' AND enabled=1",
    ).fetchall()

    per_task: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        m = json.loads(row["metric_json"] or "{}")
        checked = storage._parse_iso(row["checked_at"])  # noqa: SLF001
        if not checked:
            continue
        per_task[row["task_id"]].append({
            "checked_at": checked,
            "metric": m,
            "task_name": row["task_name"],
        })

    keyword_rows = []
    for t in all_tasks:
        cfg = json.loads(t["config_json"] or "{}")
        results = per_task.get(t["id"], [])
        curr_result = results[0] if results else None
        prev_result = results[1] if len(results) > 1 else None
        curr_m = curr_result["metric"] if curr_result else {}
        prev_m = prev_result["metric"] if prev_result else {}
        search_keywords = list(cfg.get("search_keywords") or [])
        if not search_keywords and curr_m.get("search_keywords"):
            search_keywords = list(curr_m["search_keywords"])
        target_brand = cfg.get("target_brand", "")
        for kw in search_keywords:
            # _find_keyword_entry matches entry.get("keyword")==kw — confirmed present
            curr_kw = _find_keyword_entry(curr_m, kw)
            prev_kw = _find_keyword_entry(prev_m, kw)
            curr_matched = int((curr_kw or {}).get("matched_count") or 0)
            curr_best = int((curr_kw or {}).get("first_rank") or -1)
            prev_matched = (int(prev_kw.get("matched_count") or 0)) if prev_kw else None
            prev_best = (int(prev_kw.get("first_rank") or -1)) if prev_kw else None
            _curr = {"matched_count": curr_matched, "best_rank": curr_best, "top_n": 10} if curr_kw else None
            _prev = {"matched_count": (prev_matched or 0), "best_rank": (prev_best or -1), "top_n": 10} if prev_kw else None
            kind, _ = _classify_zhihu_change(_curr, _prev)
            results_list = (curr_kw or {}).get("results") or []
            matched_ranks = [r["rank"] for r in results_list if r.get("matches_brand")]
            keyword_rows.append({
                "task_id": t["id"],
                "task_name": t["name"],
                "search_keyword": kw,
                "target_brand": target_brand,
                "matched_count": curr_matched,
                "matched_count_prev": prev_matched,
                "top_n": 10,
                "matched_ranks": matched_ranks,
                "best_rank": curr_best,
                "best_rank_prev": prev_best,
                "change_kind": kind,
                "checked_at": (curr_result["checked_at"].isoformat() if curr_result else None),
            })

    monitored_keywords = len(keyword_rows)
    hit_count_total = sum(k["matched_count"] for k in keyword_rows)
    topn_total = monitored_keywords * 10
    avg_match_rate_today = (hit_count_total / topn_total) if topn_total else 0.0
    hit_count_prev = sum((k["matched_count_prev"] or 0) for k in keyword_rows if k["matched_count_prev"] is not None)
    topn_prev_total = sum(10 for k in keyword_rows if k["matched_count_prev"] is not None)
    avg_match_rate_prev = (hit_count_prev / topn_prev_total) if topn_prev_total else 0.0
    changed_down = sum(1 for k in keyword_rows if k["change_kind"] in ("down", "dropped"))
    changed_up = sum(1 for k in keyword_rows if k["change_kind"] in ("up", "new"))
    brands_covered = len({
        json.loads(t["config_json"] or "{}").get("target_brand", "")
        for t in all_tasks
        if json.loads(t["config_json"] or "{}").get("target_brand")
    })
    daily_series = _zhihu_search_daily_series(per_task, all_tasks, range_days=range_days, now=now)

    return {
        "range": range_str,
        "kpis": {
            "monitored_keywords": monitored_keywords,
            "brands_covered": brands_covered,
            "avg_match_rate_today": avg_match_rate_today,
            "avg_match_rate_prev": avg_match_rate_prev,
            "hit_count_total": hit_count_total,
            "topn_total": topn_total,
            "changed_keywords": changed_down + changed_up,
            "changed_up": changed_up,
            "changed_down": changed_down,
        },
        "daily_series": daily_series,
        "keywords": keyword_rows,
    }


def _zhihu_search_daily_series(
    per_task: dict[int, list[dict]],
    all_tasks: list,
    *,
    range_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Per-day series for zhihu_search: avg_match_rate + change counts.

    Mirrors _baidu_daily_series but reads matched_count / first_rank
    (zhihu_search field names) instead of default_matched_count / default_first_rank.
    """
    series = []
    # Build task→keywords map from config
    task_keywords: dict[int, list[str]] = {}
    for t in all_tasks:
        cfg = json.loads(t["config_json"] or "{}")
        kws = list(cfg.get("search_keywords") or [])
        task_keywords[t["id"]] = kws

    for d in range(range_days):
        day = (now - timedelta(days=range_days - 1 - d)).date()
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        hits = 0
        topn = 0
        changed_up = changed_down = 0

        for task_id, results in per_task.items():
            keywords_for_task = task_keywords.get(task_id, [])
            curr_on_day = next((r for r in results if r["checked_at"] < day_end), None)
            if not curr_on_day:
                continue
            prev_for_day = next((r for r in results if r["checked_at"] < day_start), None)

            curr_m = curr_on_day["metric"]
            prev_m = prev_for_day["metric"] if prev_for_day else {}

            for kw in keywords_for_task:
                curr_kw = _find_keyword_entry(curr_m, kw)
                prev_kw = _find_keyword_entry(prev_m, kw)
                if curr_kw is None:
                    continue
                c_matched = int(curr_kw.get("matched_count") or 0)
                c_best = int(curr_kw.get("first_rank") or -1)
                hits += c_matched
                topn += 10

                _curr = {"matched_count": c_matched, "best_rank": c_best, "top_n": 10}
                _prev = None
                if prev_kw:
                    _prev = {
                        "matched_count": int(prev_kw.get("matched_count") or 0),
                        "best_rank": int(prev_kw.get("first_rank") or -1),
                        "top_n": 10,
                    }
                kind, _ = _classify_zhihu_change(_curr, _prev)
                if kind in ("up", "new"):
                    changed_up += 1
                elif kind in ("down", "dropped"):
                    changed_down += 1

        series.append({
            "date": day.strftime("%Y-%m-%d"),
            "avg_match_rate": (hits / topn) if topn else 0.0,
            "changed_count": changed_up + changed_down,
            "changed_up": changed_up,
            "changed_down": changed_down,
        })
    return series


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
