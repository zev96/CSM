"""GEO 存储层（schema v7）—— 复用 monitor.storage 的连接与迁移 runner。

两张规范化表让信源榜/趋势能 GROUP BY；运行级 KPI 汇总仍存
monitor_results.metric_json（loop 写，adapter 不再自存）。DDL 拆在这里、
由 monitor.storage._migrate 调 apply_v7_migration，仿 mining v3-v6。

**关联模型**：geo_cells/geo_citations 是独立分析存储，不外键
monitor_results(id)。一次运行的明细按 ``(task_id, checked_at)`` 关联
—— adapter 同时控制这两个值（用同一个 ``checked_at`` 盖在 MonitorResult
和这批 cell 上）。这样 adapter 不必先存 result 拿 id，避免与
monitor_loop 的 save_result 双写。
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


def _norm_checked_at(checked_at: "datetime | str") -> str:
    """Normalize a run's correlation timestamp to the ISO string we store.

    Accepts either a ``datetime`` (formatted via :func:`_iso`) or an
    already-ISO string (used as-is). This lets ``record_run`` and
    ``cells_for_run`` agree on the exact key without the caller having to
    pre-format — the adapter stamps ``result.checked_at`` (a datetime) and
    later drill-down passes that same value back.
    """
    if isinstance(checked_at, datetime):
        return _iso(checked_at)
    return str(checked_at)


def record_run(task_id: int, checked_at: "datetime | str", cells: list[GeoCell]) -> None:
    """Write one run's cells + citations in a single transaction. Rolls back on failure.

    The run is identified by ``(task_id, checked_at)`` — the adapter passes
    the SAME ``checked_at`` it stamps on the ``MonitorResult`` so drill-down
    via :func:`cells_for_run` can correlate without an FK to
    monitor_results(id). ``checked_at`` may be a datetime or ISO string;
    a single normalized value is used for every cell AND citation row.
    """
    import json
    conn = monitor_storage.get_conn()
    ts = _norm_checked_at(checked_at)
    conn.execute("BEGIN")
    try:
        for c in cells:
            cur = conn.execute(
                """INSERT INTO geo_cells(task_id, checked_at, platform, keyword,
                       mentioned, rank, sentiment, answer_text, status, raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (task_id, ts, c.platform, c.keyword,
                 1 if c.mentioned else 0, c.rank, c.sentiment,
                 c.answer_text, c.status, json.dumps(c.raw, ensure_ascii=False)),
            )
            cell_id = int(cur.fetchone()[0])
            for cit in c.citations:
                conn.execute(
                    """INSERT INTO geo_citations(cell_id, task_id, checked_at, platform, keyword,
                           url, title, domain, source_type)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (cell_id, task_id, ts, c.platform, c.keyword,
                     cit.url, cit.title, cit.domain, cit.source_type),
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def citation_leaderboard(
    task_id: int, days: int = 30, platform: str | None = None, keyword: str | None = None,
) -> list[dict[str, Any]]:
    """域名频次降序。返回 [{domain, source_type, count, platforms, keywords}].

    平台/关键词聚合在 Python 侧做（不用 group_concat）—— SQLite 的 group_concat
    无法在 DISTINCT 下指定分隔符，关键词里若含逗号会被 split 破坏。
    """
    conn = monitor_storage.get_conn()
    sql = ["SELECT domain, source_type, platform, keyword",
           "FROM geo_citations",
           "WHERE task_id=? AND checked_at >= datetime('now', ?)"]
    args: list[Any] = [task_id, f"-{int(days)} days"]
    if platform:
        sql.append("AND platform=?"); args.append(platform)
    if keyword:
        sql.append("AND keyword=?"); args.append(keyword)
    rows = conn.execute("\n".join(sql), args).fetchall()
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        k = (r["domain"], r["source_type"])
        e = agg.setdefault(k, {"domain": r["domain"], "source_type": r["source_type"],
                               "count": 0, "_plats": set(), "_kws": set()})
        e["count"] += 1
        e["_plats"].add(r["platform"])
        e["_kws"].add(r["keyword"])
    out = [{"domain": e["domain"], "source_type": e["source_type"], "count": e["count"],
            "platforms": sorted(e["_plats"]), "keywords": sorted(e["_kws"])} for e in agg.values()]
    out.sort(key=lambda e: (-e["count"], e["domain"]))
    return out


def cells_for_run(task_id: int, checked_at: "datetime | str") -> list[dict[str, Any]]:
    """All cells for a single run (drill-down: answer text + citations).

    A run is keyed by ``(task_id, checked_at)`` — pass the same
    ``checked_at`` the adapter stamped on the run's ``MonitorResult``.
    ``checked_at`` may be a datetime or ISO string (normalized the same way
    :func:`record_run` does so they match exactly).
    """
    conn = monitor_storage.get_conn()
    ts = _norm_checked_at(checked_at)
    rows = conn.execute(
        "SELECT * FROM geo_cells WHERE task_id=? AND checked_at=? ORDER BY platform, keyword",
        (task_id, ts),
    ).fetchall()
    out = []
    for r in rows:
        cits = conn.execute(
            "SELECT url, title, domain, source_type FROM geo_citations WHERE cell_id=?", (r["id"],)
        ).fetchall()
        out.append({**dict(r), "citations": [dict(c) for c in cits]})
    return out
