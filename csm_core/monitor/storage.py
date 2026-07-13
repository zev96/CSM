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


_SCHEMA_VERSION = 11


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
            # busy_timeout：WAL 下读不挡写，但写-写仍抢独占 WAL 锁；默认 timeout=0 时
            # 抢锁失败的一方立刻 "database is locked" 抛错。R2 把 baidu 从 1 写/轮变成
            # ~N 写/轮，撞上并发 zhihu/comment 的 save_result 概率升高 —— 后者失败会
            # 被当成整条结果落库失败误报。给 5s 退避把这类瞬时抢锁抹平。
            conn.execute("PRAGMA busy_timeout=5000")
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
    # v11: R2 增量落库 —— 在跑 run 的崩溃安全草稿表（task_id 主键，一行一个在跑的
    # baidu run）。每抓完一个关键词 UPSERT 头段；任何中断后 materialize 成断点。
    # 属核心 monitor 域（同 monitor_results），直接建在这里，不走 lazy 子模块。
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_run_progress (
            task_id INTEGER PRIMARY KEY REFERENCES monitor_tasks(id) ON DELETE CASCADE,
            next_keyword INTEGER NOT NULL,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            resume_from INTEGER NOT NULL DEFAULT 0,
            total_keywords INTEGER NOT NULL DEFAULT 0,
            search_keywords_json TEXT NOT NULL DEFAULT '[]',
            target_brand TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
        """
    )
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
        # 见 init_db：5s 退避避免写-写抢锁瞬时失败误报（R2 高频落库放大了该窗口）。
        conn.execute("PRAGMA busy_timeout=5000")
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
    # Tie-break on id DESC — see get_last_resumed_keyword: two results can
    # share the same checked_at within one coarse utcnow() tick, and without
    # the tiebreaker "latest" is non-deterministic (resume then reads a stale
    # breakpoint, KPI flickers between the two).
    row = conn.execute(
        "SELECT * FROM monitor_results WHERE task_id=? ORDER BY checked_at DESC, id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return _row_to_result(row) if row else None


def list_results(task_id: int, limit: int = 30) -> list[MonitorResult]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM monitor_results WHERE task_id=? ORDER BY checked_at DESC, id DESC LIMIT ?",
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


# ── Run-progress scratchpad (R2 增量落库：崩溃安全) ─────────────────────────
def save_run_progress(
    task_id: int,
    *,
    next_keyword: int,
    keywords: "list[dict[str, Any]]",
    resume_from: int = 0,
    total_keywords: int = 0,
    search_keywords: "list[str] | None" = None,
    target_brand: str = "",
) -> None:
    """UPSERT 一个在跑 baidu run 的头段进度（崩溃安全草稿）。

    一行一个 task（task_id PRIMARY KEY），每抓完一个关键词覆盖一次，让硬杀 /
    崩溃后已抓完的头段仍可恢复。任何 clean 终态由 ``clear_run_progress`` 清掉 ——
    所以存活到下次启动的草稿行 = 定义上的「孤儿中断 run」。

    ``next_keyword`` 绝对 0-based 下一个待抓关键词（= resume 位置）；
    ``keywords`` 本轮已抓完的行（[resume_from:next_keyword]）；
    ``resume_from`` 本 run 自己的起点（恢复时和上次断点头段合并的依据）。
    """
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO monitor_run_progress(
            task_id, next_keyword, keywords_json, resume_from,
            total_keywords, search_keywords_json, target_brand, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(task_id) DO UPDATE SET
            next_keyword=excluded.next_keyword,
            keywords_json=excluded.keywords_json,
            resume_from=excluded.resume_from,
            total_keywords=excluded.total_keywords,
            search_keywords_json=excluded.search_keywords_json,
            target_brand=excluded.target_brand,
            updated_at=excluded.updated_at
        """,
        (
            task_id,
            int(next_keyword),
            json.dumps(keywords or [], ensure_ascii=False),
            int(resume_from),
            int(total_keywords),
            json.dumps(search_keywords or [], ensure_ascii=False),
            target_brand or "",
        ),
    )


def get_run_progress(task_id: int) -> "dict[str, Any] | None":
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM monitor_run_progress WHERE task_id=?", (task_id,)
    ).fetchone()
    return _row_to_run_progress(row) if row else None


def list_run_progress() -> "list[dict[str, Any]]":
    """所有在跑草稿行。启动恢复扫描用（进程还活着时不该有别的 run 在写）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM monitor_run_progress ORDER BY task_id"
    ).fetchall()
    return [_row_to_run_progress(r) for r in rows]


def clear_run_progress(task_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM monitor_run_progress WHERE task_id=?", (task_id,))


def _row_to_run_progress(row: sqlite3.Row) -> "dict[str, Any]":
    return {
        "task_id": row["task_id"],
        "next_keyword": row["next_keyword"],
        "keywords": json.loads(row["keywords_json"]) if row["keywords_json"] else [],
        "resume_from": row["resume_from"],
        "total_keywords": row["total_keywords"],
        "search_keywords": (
            json.loads(row["search_keywords_json"]) if row["search_keywords_json"] else []
        ),
        "target_brand": row["target_brand"] or "",
        "updated_at": _parse_iso(row["updated_at"]),
    }


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
