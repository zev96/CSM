"""GEO 存储层（schema v7）—— 复用 monitor.storage 的连接与迁移 runner。

两张规范化表让信源榜/趋势能 GROUP BY；运行级 KPI 汇总仍存
monitor_results.metric_json（adapter 写）。DDL 拆在这里、由
monitor.storage._migrate 调 apply_v7_migration，仿 mining v3-v6。
"""
from __future__ import annotations
import sqlite3
from datetime import datetime
from typing import Any

from csm_core.monitor import storage as monitor_storage
from .models import GeoCell

_DDL_V7_GEO: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS geo_cells (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        result_id   INTEGER NOT NULL REFERENCES monitor_results(id) ON DELETE CASCADE,
        task_id     INTEGER NOT NULL,
        checked_at  TEXT NOT NULL,
        platform    TEXT NOT NULL,
        keyword     TEXT NOT NULL,
        mentioned   INTEGER NOT NULL DEFAULT 0,
        rank        INTEGER NOT NULL DEFAULT -1,
        sentiment   TEXT NOT NULL DEFAULT 'na',
        answer_text TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'ok',
        raw_json    TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_geo_cells_task_time ON geo_cells(task_id, checked_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_geo_cells_result ON geo_cells(result_id)",
    """
    CREATE TABLE IF NOT EXISTS geo_citations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        cell_id     INTEGER NOT NULL REFERENCES geo_cells(id) ON DELETE CASCADE,
        task_id     INTEGER NOT NULL,
        checked_at  TEXT NOT NULL,
        platform    TEXT NOT NULL,
        keyword     TEXT NOT NULL,
        url         TEXT NOT NULL,
        title       TEXT NOT NULL DEFAULT '',
        domain      TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT '其他'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_geo_cit_task_domain ON geo_citations(task_id, domain)",
    "CREATE INDEX IF NOT EXISTS idx_geo_cit_cell ON geo_citations(cell_id)",
]


def apply_v7_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v6 -> v7. Idempotent."""
    for stmt in _DDL_V7_GEO:
        conn.execute(stmt)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def record_run(result_id: int, task_id: int, cells: list[GeoCell]) -> None:
    """Write one run's cells + citations in a single transaction. Rolls back on failure."""
    import json
    conn = monitor_storage.get_conn()
    now = _iso(datetime.utcnow())
    conn.execute("BEGIN")
    try:
        for c in cells:
            cur = conn.execute(
                """INSERT INTO geo_cells(result_id, task_id, checked_at, platform, keyword,
                       mentioned, rank, sentiment, answer_text, status, raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (result_id, task_id, now, c.platform, c.keyword,
                 1 if c.mentioned else 0, c.rank, c.sentiment,
                 c.answer_text, c.status, json.dumps(c.raw, ensure_ascii=False)),
            )
            cell_id = int(cur.fetchone()[0])
            for cit in c.citations:
                conn.execute(
                    """INSERT INTO geo_citations(cell_id, task_id, checked_at, platform, keyword,
                           url, title, domain, source_type)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (cell_id, task_id, now, c.platform, c.keyword,
                     cit.url, cit.title, cit.domain, cit.source_type),
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def citation_leaderboard(
    task_id: int, days: int = 30, platform: str | None = None, keyword: str | None = None,
) -> list[dict[str, Any]]:
    """Domain frequency descending. Returns [{domain, source_type, count, platforms, keywords}]."""
    conn = monitor_storage.get_conn()
    sql = ["SELECT domain, source_type, count(*) AS cnt,",
           "  group_concat(DISTINCT platform) AS plats,",
           "  group_concat(DISTINCT keyword) AS kws",
           "FROM geo_citations",
           "WHERE task_id=? AND checked_at >= datetime('now', ?)"]
    args: list[Any] = [task_id, f"-{int(days)} days"]
    if platform:
        sql.append("AND platform=?"); args.append(platform)
    if keyword:
        sql.append("AND keyword=?"); args.append(keyword)
    sql.append("GROUP BY domain, source_type ORDER BY cnt DESC, domain ASC")
    rows = conn.execute("\n".join(sql), args).fetchall()
    return [{"domain": r["domain"], "source_type": r["source_type"], "count": r["cnt"],
             "platforms": (r["plats"] or "").split(","),
             "keywords": (r["kws"] or "").split(",")} for r in rows]


def cells_for_run(result_id: int) -> list[dict[str, Any]]:
    """All cells for a single run (drill-down: answer text + citations)."""
    conn = monitor_storage.get_conn()
    rows = conn.execute(
        "SELECT * FROM geo_cells WHERE result_id=? ORDER BY platform, keyword", (result_id,)
    ).fetchall()
    out = []
    for r in rows:
        cits = conn.execute(
            "SELECT url, title, domain, source_type FROM geo_citations WHERE cell_id=?", (r["id"],)
        ).fetchall()
        out.append({**dict(r), "citations": [dict(c) for c in cits]})
    return out
