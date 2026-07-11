"""sqlite3 storage layer for the monitor module.

Why stdlib sqlite3 and not SQLAlchemy: monitor data has a small, stable
schema (tasks, time-series results, credentials, ai_enrichments) and the
queries we run are not relational-heavy — mostly upserts plus
``SELECT ... ORDER BY checked_at DESC LIMIT N``. SQLAlchemy would add a
runtime dependency and a migration tool for zero gain at this size.

Connection lifecycle: each thread gets its own connection via
``threading.local`` — sqlite3.Connection is not thread-safe in the
default check_same_thread=True mode, and our worker QThreads each call
``get_conn()`` once. WAL mode lets the scheduler's read-only "any tasks
due?" query run concurrently with a worker writing the previous tick's
result.
"""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .base import MonitorResult, MonitorTask, TaskType, MonitorStatus


_SCHEMA_VERSION = 10


# ── Schema ──────────────────────────────────────────────────────────────────
_DDL_V1 = [
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monitor_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        target_url TEXT NOT NULL,
        config_json TEXT NOT NULL,
        schedule_cron TEXT NOT NULL DEFAULT 'manual',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_check_at TEXT,
        last_status TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(type, target_url)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monitor_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES monitor_tasks(id) ON DELETE CASCADE,
        checked_at TEXT NOT NULL,
        status TEXT NOT NULL,
        rank INTEGER NOT NULL DEFAULT -1,
        metric_json TEXT NOT NULL DEFAULT '{}',
        error_message TEXT NOT NULL DEFAULT '',
        alert_triggered INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_results_task_time ON monitor_results(task_id, checked_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS platform_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        cookies_text TEXT NOT NULL,
        user_agent TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_used_at TEXT,
        fail_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_creds_platform ON platform_credentials(platform, enabled)",
    """
    CREATE TABLE IF NOT EXISTS ai_enrichments (
        result_id INTEGER PRIMARY KEY REFERENCES monitor_results(id) ON DELETE CASCADE,
        sentiment_json TEXT,
        summary_md TEXT,
        vault_note_path TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
]


# ── Connection management ───────────────────────────────────────────────────
_local = threading.local()
_db_path: Path | None = None
_init_lock = threading.Lock()
_initialized = False


def init_db(db_path: Path) -> None:
    """Configure the storage module for a given on-disk db path.

    Idempotent — calling again with the same path is a no-op. Calling
    with a different path is treated as a programmer error and rejected;
    monitor.db is per-installation, not per-call.
    """
    global _db_path, _initialized
    db_path = Path(db_path)
    with _init_lock:
        if _initialized:
            if _db_path != db_path:
                raise RuntimeError(
                    f"monitor storage already initialized at {_db_path}, refusing to re-init at {db_path}"
                )
            return
        _db_path = db_path
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        # Apply schema using a one-shot connection so migrations finish
        # before any worker thread asks for a connection of its own.
        conn = sqlite3.connect(str(_db_path), isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            _migrate(conn)
        finally:
            conn.close()
        _initialized = True


def _migrate(conn: sqlite3.Connection) -> None:
    for stmt in _DDL_V1:
        conn.execute(stmt)
    # v2: 加 cooldown_until 给多账号轮换用 (see commit history for full why).
    _ensure_column(conn, "platform_credentials", "cooldown_until", "INTEGER NOT NULL DEFAULT 0")
    # v3: 视频引流抓取 (mining) 三表。Migration lives in csm_core/mining/storage.py
    # to keep mining-specific DDL out of this file. Import is lazy to avoid
    # making mining a hard dep of monitor at import time.
    from csm_core.mining import storage as mining_storage
    mining_storage.apply_v3_migration(conn)
    # v4: Outreach Phase 2/3 — video_comments table + videos.ai_summary.
    # Same lazy-import + idempotent rationale as v3.
    mining_storage.apply_v4_migration(conn)
    # v5: comment template library — see csm_core/mining/storage.py
    mining_storage.apply_v5_migration(conn)
    # v6: composite index on monitor_tasks(type, target_url) for dedup lookup.
    mining_storage.apply_v6_migration(conn)
    # v7: GEO 卡位监控两张规范化表（geo_cells / geo_citations）。
    from csm_core.monitor.geo import storage as geo_storage
    geo_storage.apply_v7_migration(conn)
    # v8: 品牌预筛列 — videos.brand_comment_hits / exclude_reason +
    #     mining_jobs.brand_keywords_json。
    mining_storage.apply_v8_migration(conn)
    # v9: 反馈学习闭环四表（creation_records / creation_note_usage /
    #     fact_snapshots / model_fingerprints）。同 v3-v8 lazy import + 幂等。
    from csm_core.feedback import storage as feedback_storage
    feedback_storage.apply_v9_migration(conn)
    # v10: geo_cells.fail_reason —— 失败原因分类列(前端替掉写死「够不到平台」)。
    # geo_storage 已在 v7 段 import(同一函数作用域)。幂等。
    geo_storage.apply_v10_migration(conn)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
        (str(_SCHEMA_VERSION),),
    )


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    """Idempotently add a column. Safe to call on fresh + migrated DBs.

    sqlite3 没有 ``ALTER TABLE ADD COLUMN IF NOT EXISTS``，所以拉
    ``PRAGMA table_info`` 自己判断列存不存在。这种 helper 比写一堆
    try/except sqlite3.OperationalError 干净。
    """
    # PRAGMA returns: (cid, name, type, notnull, dflt, pk). 索引 1 = name。
    # 这里走的是 init 路径，conn 还没设 row_factory，所以用位置而不是 key。
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def get_conn() -> sqlite3.Connection:
    """Return the calling thread's connection, opening one if needed.

    Each connection has WAL + foreign_keys + Row factory pre-applied so
    callers can rely on ``row['col_name']`` access. ``isolation_level=None``
    gives us autocommit; explicit transactions are managed via the
    ``transaction()`` context manager when needed.
    """
    if _db_path is None:
        raise RuntimeError("monitor storage not initialized — call init_db() first")
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(_db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


# ── Task CRUD ───────────────────────────────────────────────────────────────
def create_task(task: MonitorTask) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron, enabled)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(type, target_url) DO UPDATE SET
            name=excluded.name,
            config_json=excluded.config_json,
            schedule_cron=excluded.schedule_cron,
            enabled=excluded.enabled
        RETURNING id
        """,
        (
            task.type,
            task.name,
            task.target_url,
            json.dumps(task.config, ensure_ascii=False),
            task.schedule_cron,
            1 if task.enabled else 0,
        ),
    )
    row = cur.fetchone()
    return int(row[0])


def update_task(task: MonitorTask) -> None:
    if task.id is None:
        raise ValueError("update_task requires task.id")
    conn = get_conn()
    conn.execute(
        """
        UPDATE monitor_tasks SET
            name=?, target_url=?, config_json=?, schedule_cron=?, enabled=?
        WHERE id=?
        """,
        (
            task.name,
            task.target_url,
            json.dumps(task.config, ensure_ascii=False),
            task.schedule_cron,
            1 if task.enabled else 0,
            task.id,
        ),
    )


def delete_task(task_id: int) -> None:
    conn = get_conn()
    # ON DELETE CASCADE drops monitor_results + ai_enrichments automatically.
    conn.execute("DELETE FROM monitor_tasks WHERE id=?", (task_id,))


def list_tasks(type: TaskType | None = None, enabled_only: bool = False) -> list[MonitorTask]:
    conn = get_conn()
    where = []
    args: list[Any] = []
    if type:
        where.append("type=?")
        args.append(type)
    if enabled_only:
        where.append("enabled=1")
    sql = "SELECT * FROM monitor_tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"
    rows = conn.execute(sql, args).fetchall()
    return [_row_to_task(r) for r in rows]


def get_task(task_id: int) -> MonitorTask | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM monitor_tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def _row_to_task(row: sqlite3.Row) -> MonitorTask:
    return MonitorTask(
        id=row["id"],
        type=row["type"],
        name=row["name"],
        target_url=row["target_url"],
        config=json.loads(row["config_json"]) if row["config_json"] else {},
        schedule_cron=row["schedule_cron"],
        enabled=bool(row["enabled"]),
        last_check_at=_parse_iso(row["last_check_at"]),
        last_status=row["last_status"],
        created_at=_parse_iso(row["created_at"]),
    )


# ── Result writes & reads ───────────────────────────────────────────────────
def save_result(result: MonitorResult, alert_triggered: bool = False) -> int:
    """Insert a result row and bump the parent task's last_* columns.

    Atomicity: both writes happen in one transaction so a crash mid-save
    can't leave the task pointing at a result that was never persisted.
    """
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            """
            INSERT INTO monitor_results(task_id, checked_at, status, rank, metric_json, error_message, alert_triggered)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                result.task_id,
                _format_iso(result.checked_at),
                result.status,
                result.rank,
                json.dumps(result.metric, ensure_ascii=False),
                result.error_message,
                1 if alert_triggered else 0,
            ),
        )
        result_id = int(cur.fetchone()[0])
        conn.execute(
            "UPDATE monitor_tasks SET last_check_at=?, last_status=? WHERE id=?",
            (_format_iso(result.checked_at), result.status, result.task_id),
        )
        conn.execute("COMMIT")
        return result_id
    except Exception:
        conn.execute("ROLLBACK")
        raise


def latest_result(task_id: int) -> MonitorResult | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM monitor_results WHERE task_id=? ORDER BY checked_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return _row_to_result(row) if row else None


def list_results(task_id: int, limit: int = 30) -> list[MonitorResult]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM monitor_results WHERE task_id=? ORDER BY checked_at DESC LIMIT ?",
        (task_id, limit),
    ).fetchall()
    return [_row_to_result(r) for r in rows]


def last_alert_at(task_id: int) -> datetime | None:
    """When was the most recent rank-fell-out alert for this task?

    Used by the cooldown check in ``notify`` — if we already alerted
    within the configured window, swallow this tick's alert.
    """
    conn = get_conn()
    row = conn.execute(
        """
        SELECT checked_at FROM monitor_results
        WHERE task_id=? AND alert_triggered=1
        ORDER BY checked_at DESC LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    return _parse_iso(row["checked_at"]) if row else None


def _row_to_result(row: sqlite3.Row) -> MonitorResult:
    return MonitorResult(
        task_id=row["task_id"],
        checked_at=_parse_iso(row["checked_at"]) or datetime.utcnow(),
        status=row["status"],
        rank=row["rank"],
        metric=json.loads(row["metric_json"]) if row["metric_json"] else {},
        error_message=row["error_message"] or "",
    )


# ── Credentials ────────────────────────────────────────────────────────────
def add_credential(platform: str, cookies_text: str, label: str = "", user_agent: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO platform_credentials(platform, label, cookies_text, user_agent)
        VALUES(?, ?, ?, ?)
        RETURNING id
        """,
        (platform, label, cookies_text, user_agent),
    )
    return int(cur.fetchone()[0])


def list_credentials(
    platform: str,
    enabled_only: bool = True,
    *,
    skip_cooldown: bool = False,
) -> list[dict[str, Any]]:
    """List credentials for ``platform``.

    Args:
        enabled_only: drop rows where enabled=0 (auto-disabled by failure).
        skip_cooldown: also drop rows whose ``cooldown_until`` is in the future.
            Used by the rotation picker so a cookie that just hit /unhuman
            stays out of rotation for the configured cool-off window.
            Default False keeps the UI listing path showing every cookie
            (with cooldown shown as a status hint).
    """
    import time as _time
    conn = get_conn()
    sql = "SELECT * FROM platform_credentials WHERE platform=?"
    args: list[Any] = [platform]
    if enabled_only:
        sql += " AND enabled=1"
    if skip_cooldown:
        sql += " AND COALESCE(cooldown_until, 0) <= ?"
        args.append(int(_time.time()))
    sql += " ORDER BY fail_count ASC, last_used_at ASC NULLS FIRST"
    rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def set_credential_cooldown(cred_id: int, cooldown_seconds: int) -> None:
    """Mark a credential as unusable until ``now + cooldown_seconds``.

    Called by CookieStore when a fetch hits /unhuman, 403, or signin —
    those are zhihu's risk-control responses that mean "this account is
    flagged right now; keep using it and you'll torch it permanently".
    Pause N minutes lets the server-side throttle window slide off.
    """
    import time as _time
    until = int(_time.time()) + max(0, int(cooldown_seconds))
    conn = get_conn()
    conn.execute(
        "UPDATE platform_credentials SET cooldown_until=? WHERE id=?",
        (until, cred_id),
    )


def mark_credential_used(cred_id: int, success: bool) -> None:
    conn = get_conn()
    if success:
        conn.execute(
            "UPDATE platform_credentials SET last_used_at=?, fail_count=0 WHERE id=?",
            (_format_iso(datetime.utcnow()), cred_id),
        )
    else:
        conn.execute(
            "UPDATE platform_credentials SET last_used_at=?, fail_count=fail_count+1 WHERE id=?",
            (_format_iso(datetime.utcnow()), cred_id),
        )


def delete_credential(cred_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM platform_credentials WHERE id=?", (cred_id,))


# ── AI enrichments ─────────────────────────────────────────────────────────
def save_enrichment(
    result_id: int,
    *,
    sentiment: dict[str, Any] | None = None,
    summary_md: str | None = None,
    vault_note_path: str | None = None,
) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO ai_enrichments(result_id, sentiment_json, summary_md, vault_note_path)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(result_id) DO UPDATE SET
            sentiment_json=COALESCE(excluded.sentiment_json, ai_enrichments.sentiment_json),
            summary_md=COALESCE(excluded.summary_md, ai_enrichments.summary_md),
            vault_note_path=COALESCE(excluded.vault_note_path, ai_enrichments.vault_note_path)
        """,
        (
            result_id,
            json.dumps(sentiment, ensure_ascii=False) if sentiment is not None else None,
            summary_md,
            vault_note_path,
        ),
    )


def get_enrichment(result_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM ai_enrichments WHERE result_id=?", (result_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "result_id": row["result_id"],
        "sentiment": json.loads(row["sentiment_json"]) if row["sentiment_json"] else None,
        "summary_md": row["summary_md"],
        "vault_note_path": row["vault_note_path"],
        "created_at": _parse_iso(row["created_at"]),
    }


# ── Breakpoint helpers (Task 4: 断点续抓) ──────────────────────────────────
def get_last_resumed_keyword(task_id: int) -> int | None:
    """Return next-keyword-to-try from latest result's metric_json, or None.

    Used by POST /api/monitor/tasks/{id}/resume to resume a risk_control'd
    task from where it paused instead of restarting from keyword 0.
    Returns None when:
    - no results exist for the task
    - the latest result has no ``last_resumed_keyword`` in metric_json
    - the stored value is not a plain int
    """
    conn = get_conn()
    # Tie-break on id DESC: two results can share the same checked_at when
    # saved within the same clock tick (utcnow() resolution is coarse on
    # Windows). Without it, "latest" is non-deterministic on a tie and resume
    # could read an older breakpoint. id is AUTOINCREMENT → higher = inserted
    # later = the real latest.
    row = conn.execute(
        "SELECT metric_json FROM monitor_results WHERE task_id=? ORDER BY checked_at DESC, id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is None or not row["metric_json"]:
        return None
    metric = json.loads(row["metric_json"])
    v = metric.get("last_resumed_keyword")
    return v if isinstance(v, int) else None


# ── Maintenance ────────────────────────────────────────────────────────────
def purge_old_results(keep_days: int = 90) -> int:
    """Delete results older than ``keep_days``, returning rows removed."""
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM monitor_results WHERE checked_at < datetime('now', ?)",
        (f"-{int(keep_days)} days",),
    )
    return cur.rowcount


# ── ISO helpers ────────────────────────────────────────────────────────────
def _format_iso(dt: datetime) -> str:
    # sqlite stores text — use Z-suffixed UTC ISO to keep ordering correct
    # across timezones and to round-trip cleanly through datetime.fromisoformat.
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    # Accept both our own Z-suffixed format and sqlite's strftime output.
    s = s.rstrip("Z")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Fall back to the no-fractional form sqlite produces from strftime.
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
