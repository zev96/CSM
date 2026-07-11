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
from .classify import authority
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
        fail_reason TEXT NOT NULL DEFAULT '',
        raw_json    TEXT NOT NULL DEFAULT '{}',
        extraction_json TEXT NOT NULL DEFAULT '{}'
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
    # 给「已存在的」旧 geo_cells 表补后加的列 —— 就地改 CREATE TABLE 的语句
    # 对已建表是 no-op（CREATE IF NOT EXISTS 不改 schema），早期建了 v7 表的
    # 库会缺这些列，读到就 OperationalError。_ensure_column 幂等：列在则跳过。
    monitor_storage._ensure_column(
        conn, "geo_cells", "extraction_json", "TEXT NOT NULL DEFAULT '{}'"
    )


def apply_v10_migration(conn: sqlite3.Connection) -> None:
    """v9 -> v10: geo_cells.fail_reason —— 失败原因分类列(前端映射人话,替掉写死
    「够不到平台」)。旧库(v7 表已建但无此列)靠 _ensure_column 幂等补上;新库 CREATE
    已含此列,_ensure_column 探到即跳过。Idempotent。"""
    monitor_storage._ensure_column(
        conn, "geo_cells", "fail_reason", "TEXT NOT NULL DEFAULT ''"
    )


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
                       mentioned, rank, sentiment, answer_text, status, fail_reason,
                       raw_json, extraction_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (task_id, ts, c.platform, c.keyword,
                 1 if c.mentioned else 0, c.rank, c.sentiment,
                 c.answer_text, c.status, c.fail_reason,
                 json.dumps(c.raw, ensure_ascii=False),
                 json.dumps({"recommended": [r.model_dump() for r in c.recommended],
                             "summary": c.summary}, ensure_ascii=False)),
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
    task_id: int | None, days: int = 30, platform: str | None = None,
    keyword: str | None = None, offset_days: int = 0,
) -> list[dict[str, Any]]:
    """域名频次降序。返回 [{domain, source_type, count, platforms, keywords, weight}].

    ``task_id=None`` → 跨全部任务聚合（首页全局高权重信源榜）。
    ``offset_days>0`` → 查 ``[now-(days+offset) .. now-offset)`` 窗口（排名周对比用）。
    ``offset_days=0``（默认）→ 最近 ``days`` 天，**只加下界**：stored checked_at 是
    local+'Z'，而 SQL ``datetime('now')`` 是 UTC —— 给当前窗口加 ``< now`` 上界会把
    今天 local 时间戳（比 UTC 提前数小时、读成"未来"）误杀，故 offset=0 时不加上界，
    与历史行为一致。

    平台/关键词聚合在 Python 侧做（不用 group_concat）—— SQLite 的 group_concat
    无法在 DISTINCT 下指定分隔符，关键词里若含逗号会被 split 破坏。
    """
    conn = monitor_storage.get_conn()
    sql = ["SELECT domain, source_type, platform, keyword",
           "FROM geo_citations",
           "WHERE checked_at >= datetime('now', ?)"]
    args: list[Any] = [f"-{int(days) + int(offset_days)} days"]
    if offset_days > 0:
        sql.append("AND checked_at < datetime('now', ?)"); args.append(f"-{int(offset_days)} days")
    if task_id is not None:
        sql.append("AND task_id=?"); args.append(task_id)
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
    out = [{
        "domain": e["domain"], "source_type": e["source_type"], "count": e["count"],
        "platforms": sorted(e["_plats"]), "keywords": sorted(e["_kws"]),
        "weight": round(e["count"] * len(e["_plats"]) * authority(e["source_type"]), 2),
    } for e in agg.values()]
    out.sort(key=lambda e: (-e["weight"], -e["count"], e["domain"]))
    return out


def exposure_window(days: int, offset_days: int = 0) -> tuple[int, int]:
    """全局曝光窗口聚合：返回 ``(mentioned, ok_total)``，跨所有任务。

    口径同 metrics._block：分母 = ``status='ok'`` 的 cell 数（采集失败不算入
    分母 —— 是"没问到"不是"问了没提及"）；分子 = 其中 ``mentioned=1`` 的数。

    ``offset_days=0`` → 最近 ``days`` 天，**仅下界**（stored checked_at 是 local+'Z'，
    SQL ``datetime('now')`` 是 UTC，给当前窗口加 ``< now`` 上界会误杀今天的 cell）。
    ``offset_days>0`` → ``[now-(days+offset) .. now-offset)`` 窗口（较上周 delta 用）。
    用 ``CASE WHEN`` 而非 ``FILTER`` 以兼容旧 SQLite。
    """
    conn = monitor_storage.get_conn()
    where = ["checked_at >= datetime('now', ?)"]
    args: list[Any] = [f"-{int(days) + int(offset_days)} days"]
    if offset_days > 0:
        where.append("checked_at < datetime('now', ?)")
        args.append(f"-{int(offset_days)} days")
    row = conn.execute(
        f"""
        SELECT
          COALESCE(SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END), 0) AS ok_total,
          COALESCE(SUM(CASE WHEN status='ok' AND mentioned=1 THEN 1 ELSE 0 END), 0) AS mentioned
        FROM geo_cells
        WHERE {' AND '.join(where)}
        """,
        args,
    ).fetchone()
    return int(row["mentioned"] or 0), int(row["ok_total"] or 0)


def _hydrate_cells(conn: sqlite3.Connection, rows: list) -> list[dict[str, Any]]:
    """Shared cell-row hydration for both drill paths.

    Each cell dict carries the raw column values plus ``citations`` (joined
    from geo_citations) and ``recommended`` / ``summary`` (parsed out of
    extraction_json — the L2 下钻 needs 谁排第 1/第 2、自己在第几、AI 总评)。
    """
    import json
    out = []
    for r in rows:
        cits = conn.execute(
            "SELECT url, title, domain, source_type FROM geo_citations WHERE cell_id=?", (r["id"],)
        ).fetchall()
        # extraction_json 存 cell 抽取的 recommended 列表 + summary。解析回 dict 列表 + 字符串。
        try:
            ext = json.loads(r["extraction_json"] or "{}")
        except (ValueError, TypeError):
            ext = {}
        out.append({
            **dict(r),
            "citations": [dict(c) for c in cits],
            "recommended": ext.get("recommended") or [],
            "summary": ext.get("summary") or "",
        })
    return out


def cells_for_run(task_id: int, checked_at: "datetime | str") -> list[dict[str, Any]]:
    """All cells for a single run (drill-down: answer text + citations).

    A run is keyed by ``(task_id, checked_at)`` — pass the same
    ``checked_at`` the adapter stamped on the run's ``MonitorResult``.
    ``checked_at`` may be a datetime or ISO string (normalized the same way
    :func:`record_run` does so they match exactly).

    The comparison is tolerant of a trailing ``Z`` mismatch: geo_cells stores
    the correlation timestamp WITH a trailing ``Z`` (see :func:`_iso`), but
    the value the frontend gets back from ``/api/monitor/results`` comes
    WITHOUT it. ``rtrim(...,'Z')`` on both sides makes either form match the
    same rows instead of silently returning 0 cells.
    """
    conn = monitor_storage.get_conn()
    ts = _norm_checked_at(checked_at)
    rows = conn.execute(
        "SELECT * FROM geo_cells WHERE task_id=? AND rtrim(checked_at,'Z') = rtrim(?,'Z') "
        "ORDER BY platform, keyword",
        (task_id, ts),
    ).fetchall()
    return _hydrate_cells(conn, rows)


def cells_for_latest_run(task_id: int) -> list[dict[str, Any]]:
    """All cells for the task's most recent run — no ``checked_at`` needed.

    Robust drill path for the L2 卡位仪表盘: rather than make the caller pass
    a ``checked_at`` (which can fail to match because results expose it
    without the trailing ``Z`` that geo_cells stores), this resolves the
    latest run server-side via ``max(checked_at)`` and hydrates that run's
    cells the same way :func:`cells_for_run` does. Returns ``[]`` if the task
    has no runs.
    """
    conn = monitor_storage.get_conn()
    row = conn.execute(
        "SELECT max(checked_at) AS ts FROM geo_cells WHERE task_id=?", (task_id,)
    ).fetchone()
    latest = row["ts"] if row is not None else None
    if not latest:
        return []
    rows = conn.execute(
        "SELECT * FROM geo_cells WHERE task_id=? AND checked_at=? ORDER BY platform, keyword",
        (task_id, latest),
    ).fetchall()
    return _hydrate_cells(conn, rows)
