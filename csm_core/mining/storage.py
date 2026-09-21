"""SQLite storage layer for the mining module.

Shares the monitor DB file (same ``init_db`` path). The 3 mining tables
are added in schema v3 — see ``_DDL_V3_MINING`` below; the actual
``ALTER`` / ``CREATE`` is run by ``csm_core.monitor.storage._migrate``
which knows the current version. Splitting the DDL list out here keeps
mining-specific concerns out of monitor/storage.py while still using
the same migration runner.

Connection model: re-uses ``monitor.storage.get_conn()`` — there is one
sqlite3.Connection per thread, WAL + foreign_keys on. Mining inserts
are autocommit (each ``on_card`` callback writes one row triple), no
explicit transactions needed; the runner already throttles cards to
≤1/200ms so WAL doesn't thrash.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from csm_core.monitor import storage as monitor_storage


# ── Schema v3 additions ─────────────────────────────────────────────────
_DDL_V3_MINING: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS mining_jobs (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword             TEXT NOT NULL,
        platforms_json      TEXT NOT NULL,
        target_per_platform INTEGER NOT NULL DEFAULT 50,
        status              TEXT NOT NULL,
        progress_json       TEXT NOT NULL DEFAULT '{}',
        error_message       TEXT NOT NULL DEFAULT '',
        created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        started_at          TEXT,
        finished_at         TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mining_jobs_keyword ON mining_jobs(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_mining_jobs_created ON mining_jobs(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS videos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        platform            TEXT NOT NULL,
        platform_video_id   TEXT NOT NULL,
        url                 TEXT NOT NULL,
        title               TEXT NOT NULL DEFAULT '',
        author_name         TEXT NOT NULL DEFAULT '',
        author_id           TEXT NOT NULL DEFAULT '',
        cover_url           TEXT NOT NULL DEFAULT '',
        duration_sec        INTEGER,
        play_count          INTEGER,
        like_count          INTEGER,
        published_at        TEXT,
        raw_json            TEXT NOT NULL DEFAULT '{}',
        excluded            INTEGER NOT NULL DEFAULT 0,
        already_commented   INTEGER NOT NULL DEFAULT 0,
        commented_source    TEXT,
        commented_at        TEXT,
        first_seen_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(platform, platform_video_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_videos_platform ON videos(platform)",
    "CREATE INDEX IF NOT EXISTS idx_videos_first_seen ON videos(first_seen_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_videos_already_commented ON videos(already_commented, platform)",
    """
    CREATE TABLE IF NOT EXISTS video_source_keywords (
        video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
        keyword         TEXT NOT NULL,
        job_id          INTEGER NOT NULL REFERENCES mining_jobs(id) ON DELETE CASCADE,
        rank_in_search  INTEGER NOT NULL,
        found_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY (video_id, keyword, job_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vsk_keyword ON video_source_keywords(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_vsk_job ON video_source_keywords(job_id)",
]


def apply_v3_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v2 → v3.

    Idempotent (all statements use IF NOT EXISTS).
    """
    for stmt in _DDL_V3_MINING:
        conn.execute(stmt)


# ── Schema v4 additions ─────────────────────────────────────────────────
# Phase 2 / 3 of Outreach: comment-drafting (video_comments) + AI summary.
# UNIQUE(video_id, tier) is the integrity backstop for "next tier =
# MAX(tier)+1 calculated client-side"; concurrent tabs can race the
# computation and the DB will reject the second writer with IntegrityError.
_DDL_V4_MINING: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS video_comments (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
        tier            INTEGER NOT NULL,
        text            TEXT NOT NULL DEFAULT '',
        image_ids_json  TEXT NOT NULL DEFAULT '[]',
        status          TEXT NOT NULL DEFAULT 'draft',
        source          TEXT NOT NULL DEFAULT 'manual',
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(video_id, tier)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_video_comments_video ON video_comments(video_id)",
]


def apply_v4_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v3 → v4.

    Idempotent: CREATE TABLE IF NOT EXISTS on video_comments; the
    ai_summary column on videos is added via a PRAGMA-guarded ALTER
    because sqlite has no ``ADD COLUMN IF NOT EXISTS``.
    """
    for stmt in _DDL_V4_MINING:
        conn.execute(stmt)
    # PRAGMA returns: (cid, name, type, notnull, dflt, pk).
    # row_factory may or may not be set on this conn (init path uses
    # default tuple rows; later upgrades come through a Row factory).
    cols = set()
    for row in conn.execute("PRAGMA table_info(videos)").fetchall():
        # Tolerate both tuple and sqlite3.Row.
        try:
            cols.add(row[1])
        except (IndexError, TypeError):
            cols.add(row["name"])
    if "ai_summary" not in cols:
        conn.execute("ALTER TABLE videos ADD COLUMN ai_summary TEXT")


# ── Schema v5 additions ─────────────────────────────────────────────────
# Comment template library (cross-video reusable evaluation snippets).
# UNIQUE(text_hash) ensures dedup on normalized text; ON CONFLICT updates
# use_count + last_used_at.
_DDL_V5_TEMPLATES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS comment_templates (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        text                TEXT NOT NULL,
        text_hash           TEXT NOT NULL UNIQUE,
        tags_json           TEXT NOT NULL DEFAULT '[]',
        source_platform     TEXT,
        source_comment_id   INTEGER REFERENCES video_comments(id) ON DELETE SET NULL,
        starred             INTEGER NOT NULL DEFAULT 0,
        hidden              INTEGER NOT NULL DEFAULT 0,
        use_count           INTEGER NOT NULL DEFAULT 0,
        first_seen_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        last_used_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_templates_starred_last ON comment_templates(starred DESC, last_used_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_templates_hidden ON comment_templates(hidden)",
]


def apply_v5_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v4 → v5.

    Idempotent: CREATE TABLE / CREATE INDEX use IF NOT EXISTS;
    backfill is gated by a schema_meta marker so it runs exactly once.

    Why the marker: ``_migrate`` is invoked on every ``init_db()`` (i.e.
    every app launch) and re-runs every migration function unconditionally
    — there's no ``current_version < target`` guard. Other v3/v4 migrations
    are safe under this regime because they're pure CREATE/PRAGMA-ALTER
    with no side effects. T3's backfill IS a side effect: without the
    gate, every done comment would bump its template's ``use_count`` by
    +1 on each startup, inflating counts and breaking the chips top-5
    sort. Spec §3.4 calls this out as "一次性回填".

    Transactional wrap (spec §3.4 "异常时整事务回滚"): we use an explicit
    BEGIN/COMMIT/ROLLBACK rather than ``with conn:`` because monitor.storage
    opens connections with ``isolation_level=None`` (autocommit). Under
    autocommit, Python's sqlite3 connection context manager does NOT issue
    BEGIN — it's a no-op for transaction wrapping. So we issue BEGIN
    manually, then COMMIT on success / ROLLBACK on any exception (then
    re-raise so the migration runner sees the failure).
    """
    conn.execute("BEGIN")
    try:
        for stmt in _DDL_V5_TEMPLATES:
            conn.execute(stmt)
        # One-time backfill, gated by schema_meta marker.
        already_done = conn.execute(
            "SELECT value FROM schema_meta WHERE key='templates_v5_backfilled'"
        ).fetchone()
        if not already_done:
            _backfill_v5_templates(conn)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('templates_v5_backfilled', '1')"
            )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _backfill_v5_templates(conn: sqlite3.Connection) -> None:
    """Scan all existing done comments and upsert them as templates.

    Iterates by `created_at ASC` so `source_comment_id` points at the
    chronologically-earliest occurrence of duplicate text. Note that
    `first_seen_at` itself defaults to migration-run time (strftime
    'now' in the INSERT), not the source comment's `created_at` — the
    chronological iteration affects which row "wins" the source link,
    not the timestamp on the template row.

    Safe to re-run (ON CONFLICT bumps use_count).
    """
    rows = conn.execute(
        "SELECT id, video_id, text FROM video_comments "
        "WHERE status='done' ORDER BY created_at ASC"
    ).fetchall()
    for row in rows:
        _upsert_template_from_comment(conn, dict(row))


def _normalize_text(text: str) -> str:
    """Strip + lowercase. Preserve emoji / punctuation / internal whitespace."""
    return text.strip().lower()


def _hash_text(text: str) -> str:
    """sha1 hex digest of normalized text — used as UNIQUE key for dedup."""
    return hashlib.sha1(_normalize_text(text).encode("utf-8")).hexdigest()


def _get_video_platform(conn: sqlite3.Connection, video_id: int) -> str | None:
    row = conn.execute("SELECT platform FROM videos WHERE id=?", (video_id,)).fetchone()
    return row[0] if row else None


def _upsert_template_from_comment(conn: sqlite3.Connection, comment: dict) -> None:
    """Insert or update a template from a video_comments row.

    `comment` must have keys: id, video_id, text.
    On conflict (same text_hash) bumps use_count + last_used_at.
    Caller is responsible for ensuring the transaction context.
    """
    text_hash = _hash_text(comment["text"])
    platform = _get_video_platform(conn, comment["video_id"])
    conn.execute(
        """
        INSERT INTO comment_templates
          (text, text_hash, source_platform, source_comment_id,
           use_count, first_seen_at, last_used_at)
        VALUES(?, ?, ?, ?, 1,
               strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(text_hash) DO UPDATE SET
          use_count = use_count + 1,
          last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (comment["text"], text_hash, platform, comment["id"]),
    )


def get_conn() -> sqlite3.Connection:
    """Thin alias — mining shares monitor's connection pool."""
    return monitor_storage.get_conn()


# ── Job CRUD ──────────────────────────────────────────────────────────
def create_job(
    keyword: str,
    platforms: list[str],
    target_per_platform: int,
    brand_keywords: list[str] | None = None,
    filters: dict[str, Any] | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, status, progress_json, brand_keywords_json, filters_json)
        VALUES(?, ?, ?, 'pending', ?, ?, ?)
        RETURNING id
        """,
        (
            keyword,
            json.dumps(platforms, ensure_ascii=False),
            target_per_platform,
            json.dumps({p: {"got": 0, "target": target_per_platform, "phase": "queued"} for p in platforms}, ensure_ascii=False),
            json.dumps(brand_keywords or [], ensure_ascii=False),
            json.dumps(filters or {}, ensure_ascii=False),
        ),
    )
    return int(cur.fetchone()[0])


def mark_started(job_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE mining_jobs SET status='running', started_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (job_id,),
    )


def update_platform_progress(
    job_id: int, platform: str, *, got: int, target: int, phase: str, note: str = "",
    featured_skipped: int = 0,
) -> None:
    conn = get_conn()
    row = conn.execute("SELECT progress_json FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return
    progress: dict[str, Any] = json.loads(row["progress_json"]) if row["progress_json"] else {}
    progress[platform] = {"got": got, "target": target, "phase": phase, "note": note}
    if featured_skipped > 0:
        # 因「评论区开启精选后可见」被跳过的视频数。只在 >0 时写 —— 前端完成通知
        # 读它报数；结构化字段，免得去解析 note 里的中文。
        progress[platform]["featured_skipped"] = int(featured_skipped)
    conn.execute(
        "UPDATE mining_jobs SET progress_json=? WHERE id=?",
        (json.dumps(progress, ensure_ascii=False), job_id),
    )


def finalize_job(job_id: int) -> dict[str, Any]:
    """Compute the overall job status from per-platform phases.

    If the job was already marked ``cancelled`` (by user) or ``interrupted``
    (by sidecar startup sweep), preserve that status — only stamp finished_at
    and return. Otherwise aggregate per-platform phases into one of
    done / partial_done / failed.
    """
    conn = get_conn()
    row = conn.execute("SELECT status, progress_json FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return {}
    progress: dict[str, Any] = json.loads(row["progress_json"]) if row["progress_json"] else {}

    existing_status = row["status"]
    if existing_status in {"cancelled", "interrupted"}:
        # Preserve the user-initiated / startup-recovery state. Just stamp finished_at.
        conn.execute(
            "UPDATE mining_jobs SET finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND finished_at IS NULL",
            (job_id,),
        )
        return {"status": existing_status, "successes": 0, "failures": 0, "progress": progress}

    phases = [p["phase"] for p in progress.values()]
    successes = sum(1 for ph in phases if ph == "done")
    failures = len(phases) - successes
    if successes == len(phases) and len(phases) > 0:
        status = "done"
    elif successes == 0:
        status = "failed"
    else:
        status = "partial_done"
    conn.execute(
        "UPDATE mining_jobs SET status=?, finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (status, job_id),
    )
    return {"status": status, "successes": successes, "failures": failures, "progress": progress}


def cancel_job_if_running(job_id: int) -> bool:
    """Flip status to cancelled only if still running/pending. Caller wakes the runner separately."""
    conn = get_conn()
    cur = conn.execute(
        """
        UPDATE mining_jobs SET status='cancelled', finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=? AND status IN ('pending', 'running')
        """,
        (job_id,),
    )
    return cur.rowcount > 0


def delete_job(job_id: int) -> dict[str, int]:
    """Hard-delete a mining job + clean up orphan videos.

    Three steps inside one transaction:

      1. Find videos that are sourced **only** by this job (orphans-to-be).
         A video with multiple job links survives because other jobs still
         "own" it.
      2. ``DELETE FROM mining_jobs WHERE id=?`` — FK cascades clear out
         ``video_source_keywords`` rows for this job.
      3. Hard-delete the orphan videos. FK cascade on ``video_comments``
         takes their comment drafts with them.

    Returns ``{"orphan_videos": N}`` so the caller can log + ship the
    count back to the UI as observability.

    Caller MUST cancel the job runner first if the job is currently
    running — this function only touches DB state; killing the executor
    Future is the route layer's job. Doing both atomically is overkill
    given how rare delete-while-running is (UI requires confirm + the job
    is on the left panel where status pill shows "抓取中").
    """
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT DISTINCT vsk.video_id FROM video_source_keywords vsk
        WHERE vsk.job_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM video_source_keywords vsk2
              WHERE vsk2.video_id = vsk.video_id AND vsk2.job_id != ?
          )
        """,
        (job_id, job_id),
    ).fetchall()
    orphan_ids = [r[0] for r in rows]
    conn.execute("DELETE FROM mining_jobs WHERE id=?", (job_id,))
    if orphan_ids:
        placeholders = ",".join("?" * len(orphan_ids))
        conn.execute(
            f"DELETE FROM videos WHERE id IN ({placeholders})",
            orphan_ids,
        )
    conn.commit()
    return {"orphan_videos": len(orphan_ids)}


def mark_interrupted_jobs() -> int:
    """At sidecar startup, flip orphaned status=running rows to interrupted."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE mining_jobs SET status='interrupted', finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE status='running'"
    )
    return cur.rowcount


def get_job(job_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job_dict(row) if row else None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_conn()
    # 在 mining_jobs SELECT 里挂两个相关子查询，给每个 job 算出：
    #   _video_count     —— 该 job 关联的、**未被删除（excluded=0）** 的视频数
    #                       （COUNT DISTINCT 因为同一视频可能命中多个关键词）
    #   _commented_count —— 同上但 only videos.already_commented=1
    # 前端 TaskListItem 用 (commented_count >= video_count) 判定「已完成」/
    # 「进行中」（用户要求"全部已评论=已完成，否则=进行中"），跟纯
    # mining_jobs.status（抓取层面的成功/失败）解耦。
    # ⚠ 必须过滤 v.excluded=0：用户抓取后会删（软删 excluded=1）一批视频，
    #   两个计数都要按「当前实际剩余」算，否则分母虚高 → 永远 commented<video
    #   → chip 卡在「进行中」、同步守卫误判未评论完。与 list_videos 的
    #   `v.excluded=0` 口径保持一致。
    # idx_vsk_job 索引覆盖；少量 jobs 时性能可忽略。
    rows = conn.execute(
        """
        SELECT mj.*,
               (SELECT COUNT(DISTINCT v.id)
                FROM videos v
                JOIN video_source_keywords vsk ON vsk.video_id = v.id
                WHERE vsk.job_id = mj.id AND v.excluded = 0) AS _video_count,
               (SELECT COUNT(DISTINCT v.id)
                FROM videos v
                JOIN video_source_keywords vsk2 ON vsk2.video_id = v.id
                WHERE vsk2.job_id = mj.id AND v.already_commented = 1
                      AND v.excluded = 0) AS _commented_count
        FROM mining_jobs mj
        ORDER BY mj.created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_job_dict(r) for r in rows]


def _row_to_job_dict(row) -> dict[str, Any]:
    # video_count / commented_count 仅 list_jobs() SQL 注入了；get_job()
    # 的简单 SELECT * 没这两列。用 row.keys() 做存在性检查避免 KeyError，
    # 调用方拿到 0 表示"未知 / 未聚合"。
    keys = row.keys()
    video_count = int(row["_video_count"] or 0) if "_video_count" in keys else 0
    commented_count = int(row["_commented_count"] or 0) if "_commented_count" in keys else 0
    # brand_keywords_json is v8-only; tolerate v7-era rows in mixed-version
    # test setups by reading through a try/except like ai_summary in _row_to_video_dict.
    try:
        brand_keywords = json.loads(row["brand_keywords_json"]) if row["brand_keywords_json"] else []
    except (IndexError, KeyError):
        brand_keywords = []
    # filters_json is v13-only; same tolerant pattern.
    try:
        filters = json.loads(row["filters_json"]) if row["filters_json"] else {}
    except (IndexError, KeyError):
        filters = {}
    return {
        "id": row["id"],
        "keyword": row["keyword"],
        "platforms": json.loads(row["platforms_json"]),
        "target_per_platform": row["target_per_platform"],
        "status": row["status"],
        "progress": json.loads(row["progress_json"]) if row["progress_json"] else {},
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        # 用户重构 TaskListItem 状态语义所需的两个汇总值：
        # 全部已评论 → 已完成；有未评论 → 进行中；抓取层失败 → 失败
        "video_count": video_count,
        "commented_count": commented_count,
        "brand_keywords": brand_keywords,
        "filters": filters,
    }


# ── Video upsert ──────────────────────────────────────────────────────
def upsert_video_and_link(card, job_id: int) -> int:
    """Insert (or skip duplicate) a video row, run the already_commented
    check on first insert, and always add the source-keyword link.

    Returns the videos.id (existing or freshly inserted).

    Why a single function and not two: the call site (``runner.on_card``)
    needs both writes to happen atomically with respect to the rest of
    the pipeline — if we split, a crash between them could leave a
    video row without its keyword link, which would make the dedup-on-
    rerun behavior silently wrong.
    """
    conn = get_conn()
    # Step 1: try insert; ON CONFLICT keep existing row but return id.
    cur = conn.execute(
        """
        INSERT INTO videos(platform, platform_video_id, url, title, author_name, author_id,
                           cover_url, duration_sec, play_count, like_count, published_at, raw_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(platform, platform_video_id) DO NOTHING
        RETURNING id
        """,
        (
            card.platform, card.platform_video_id, card.url, card.title,
            card.author_name, card.author_id, card.cover_url,
            card.duration_sec, card.play_count, card.like_count, card.published_at,
            json.dumps(card.raw, ensure_ascii=False, default=str),
        ),
    )
    row = cur.fetchone()
    is_new = row is not None
    if is_new:
        video_id = int(row[0])
        # Run reverse-lookup ONLY on first insert. Cheap (≤ 1 sqlite query
        # per platform per card) and ensures the already_commented flag
        # is in place before the UI ever sees the row.
        _check_already_commented(conn, video_id, card.platform, card.platform_video_id)
    else:
        # Existing row — fetch its id.
        idrow = conn.execute(
            "SELECT id FROM videos WHERE platform=? AND platform_video_id=?",
            (card.platform, card.platform_video_id),
        ).fetchone()
        video_id = int(idrow["id"])
    # Step 2: link this hit to the keyword + job. Composite PK swallows
    # the "same video, same keyword, same job" case (only happens on
    # retries — rank stays the first rank we observed).
    keyword = _job_keyword(conn, job_id)
    conn.execute(
        """
        INSERT INTO video_source_keywords(video_id, keyword, job_id, rank_in_search)
        VALUES(?,?,?,?)
        ON CONFLICT DO NOTHING
        """,
        (video_id, keyword, job_id, card.rank_in_search),
    )
    return video_id


def _job_keyword(conn, job_id: int) -> str:
    row = conn.execute("SELECT keyword FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    return row["keyword"] if row else ""


# ── already_commented reverse lookup ──────────────────────────────────
# Each platform's *_comment task targets a video URL; we extract the
# platform_video_id from that URL using the same regex set the monitor
# adapters use. Kept in-module to avoid pulling adapter code into mining.
import re as _re

_VIDEO_ID_PATTERNS: dict[str, list[_re.Pattern[str]]] = {
    "douyin": [
        _re.compile(r"/video/(\d+)"),
        _re.compile(r"/note/(\d+)"),
        _re.compile(r"modal_id=(\d+)"),
        _re.compile(r"aweme_id=(\d+)"),
    ],
    "bilibili": [
        _re.compile(r"/video/(BV[A-Za-z0-9]+)"),
        _re.compile(r"bvid=(BV[A-Za-z0-9]+)"),
        # av-IDs can co-exist; we treat the BV form as the canonical platform_video_id.
        _re.compile(r"/video/av(\d+)"),
    ],
    "kuaishou": [
        _re.compile(r"/short-video/([0-9a-zA-Z]+)"),
        _re.compile(r"photoId=([0-9a-zA-Z]+)"),
        _re.compile(r"/profile/[^/]+/photo/([0-9a-zA-Z]+)"),
    ],
    # 小红书笔记 ID 固定 24 位十六进制；explore / discovery/item 两种长链 + note_id 参数。
    "xiaohongshu": [
        _re.compile(r"/explore/([0-9a-fA-F]{24})"),
        _re.compile(r"/discovery/item/([0-9a-fA-F]{24})"),
        _re.compile(r"/item/([0-9a-fA-F]{24})"),
        _re.compile(r"note_id=([0-9a-fA-F]{24})"),
    ],
}


def extract_platform_video_id(platform: str, url: str) -> str | None:
    """Public helper, used by adapters AND by the reverse-lookup below."""
    for pat in _VIDEO_ID_PATTERNS.get(platform, []):
        m = pat.search(url or "")
        if m:
            return m.group(1)
    return None


_PLATFORM_TO_MONITOR_TYPE = {
    "douyin": "douyin_comment",
    "bilibili": "bilibili_comment",
    "kuaishou": "kuaishou_comment",
    "xiaohongshu": "xiaohongshu_comment",
}


def _check_already_commented(conn, video_id: int, platform: str, platform_video_id: str) -> None:
    """Look at monitor_tasks rows for type=<platform>_comment; if any
    target_url resolves to the same platform_video_id, mark the new
    video row already_commented=1.

    Why scan all rows of that type instead of an index lookup: monitor
    target_urls are stored verbatim (short links, modal_id forms, etc.)
    — no normalized column to JOIN on. The rowset is small (the user's
    own comment task list, hundreds at most), so a linear scan with
    regex extraction on each row is fine. If this ever crosses 10k rows
    we can add a generated column ``platform_video_id_norm`` and an
    index; YAGNI for v1.
    """
    monitor_type = _PLATFORM_TO_MONITOR_TYPE.get(platform)
    if monitor_type is None:
        return
    rows = conn.execute(
        "SELECT id, target_url, last_check_at FROM monitor_tasks WHERE type=?",
        (monitor_type,),
    ).fetchall()
    for r in rows:
        pid = extract_platform_video_id(platform, r["target_url"])
        if pid == platform_video_id:
            conn.execute(
                """
                UPDATE videos SET already_commented=1,
                                  commented_source='monitor_task',
                                  commented_at=?
                WHERE id=?
                """,
                (r["last_check_at"], video_id),
            )
            return


# ── Video reads ───────────────────────────────────────────────────────
def list_videos(
    *,
    keyword: str | None = None,
    platform: str | None = None,
    commented: str = "0",   # "0" | "1" | "all"
    q: str | None = None,
    job_id: int | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Returns (rows, total). Each row is a dict with source_keywords aggregated."""
    conn = get_conn()
    where = ["v.excluded=0"]
    args: list[Any] = []
    if platform:
        where.append("v.platform=?")
        args.append(platform)
    if commented == "0":
        where.append("v.already_commented=0")
    elif commented == "1":
        where.append("v.already_commented=1")
    # "all" → no filter
    if keyword:
        where.append(
            "EXISTS (SELECT 1 FROM video_source_keywords vsk "
            "WHERE vsk.video_id=v.id AND vsk.keyword=?)"
        )
        args.append(keyword)
    if job_id is not None:
        where.append(
            "EXISTS (SELECT 1 FROM video_source_keywords vsk "
            "WHERE vsk.video_id=v.id AND vsk.job_id=?)"
        )
        args.append(job_id)
    if q:
        where.append("(v.title LIKE ? OR v.author_name LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%"])

    where_sql = " AND ".join(where)
    total = int(conn.execute(
        f"SELECT COUNT(*) FROM videos v WHERE {where_sql}", args,
    ).fetchone()[0])
    rows = conn.execute(
        f"""
        SELECT v.*, GROUP_CONCAT(DISTINCT vsk.keyword) AS source_keywords,
               (SELECT COUNT(*) FROM video_comments vc
                WHERE vc.video_id = v.id AND vc.review_status = 'pending')
                   AS _pending_review_count
        FROM videos v
        LEFT JOIN video_source_keywords vsk ON vsk.video_id = v.id
        WHERE {where_sql}
        GROUP BY v.id
        ORDER BY v.first_seen_at DESC
        LIMIT ? OFFSET ?
        """,
        args + [limit, offset],
    ).fetchall()
    return [_row_to_video_dict(r) for r in rows], total


def _row_to_video_dict(row) -> dict[str, Any]:
    keys_csv = row["source_keywords"] or ""
    # ai_summary is v4-only; tolerate v3 rows in mixed test setups by
    # reading via .keys() rather than direct key access (sqlite3.Row
    # raises IndexError on missing columns).
    try:
        ai_summary = row["ai_summary"]
    except (IndexError, KeyError):
        ai_summary = None
    # brand_comment_hits + exclude_reason are v8-only; same tolerant pattern.
    try:
        brand_comment_hits = row["brand_comment_hits"]
    except (IndexError, KeyError):
        brand_comment_hits = None
    try:
        exclude_reason = row["exclude_reason"]
    except (IndexError, KeyError):
        exclude_reason = None
    # top_comments_json is v13-only; same tolerant pattern.
    try:
        top_comments = json.loads(row["top_comments_json"]) if row["top_comments_json"] else None
    except (IndexError, KeyError, ValueError):
        top_comments = None
    # _pending_review_count 仅 list_videos() SQL 注入；按 keys() 判存在。
    keys = row.keys()
    pending_review_count = (
        int(row["_pending_review_count"] or 0)
        if "_pending_review_count" in keys else 0
    )
    return {
        "id": row["id"],
        "platform": row["platform"],
        "platform_video_id": row["platform_video_id"],
        "url": row["url"],
        "title": row["title"],
        "author_name": row["author_name"],
        "author_id": row["author_id"],
        "cover_url": row["cover_url"],
        "duration_sec": row["duration_sec"],
        "play_count": row["play_count"],
        "like_count": row["like_count"],
        "published_at": row["published_at"],
        "excluded": bool(row["excluded"]),
        "already_commented": bool(row["already_commented"]),
        "commented_source": row["commented_source"],
        "commented_at": row["commented_at"],
        "first_seen_at": row["first_seen_at"],
        "ai_summary": ai_summary,
        "brand_comment_hits": brand_comment_hits,
        "exclude_reason": exclude_reason,
        "top_comments": top_comments,
        "pending_review_count": pending_review_count,
        "source_keywords": [k for k in keys_csv.split(",") if k],
    }


def soft_delete_video(video_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("UPDATE videos SET excluded=1 WHERE id=?", (video_id,))
    return cur.rowcount > 0


# ── Video comments (v4) ───────────────────────────────────────────────
def _row_to_comment_dict(row) -> dict[str, Any]:
    image_ids = json.loads(row["image_ids_json"]) if row["image_ids_json"] else []

    # v14 review columns — tolerate pre-v14 rows in mixed test setups
    # (same pattern as ai_summary in _row_to_video_dict).
    def _opt(key: str):
        try:
            return row[key]
        except (IndexError, KeyError):
            return None

    return {
        "id": row["id"],
        "video_id": row["video_id"],
        "tier": row["tier"],
        "text": row["text"],
        "image_ids": image_ids,
        # Static-serve URL pattern; route layer is responsible for the
        # actual /api/mining/images/{id} handler in T5. We compute here
        # so all consumers (REST, CSV export) see the same shape.
        "image_urls": [f"/api/mining/images/{img}" for img in image_ids],
        "status": row["status"],
        "source": row["source"],
        "review_status": _opt("review_status") or "",
        "template_id": _opt("template_id"),
        "ai_flavor_score": _opt("ai_flavor_score"),
        "reviewed_at": _opt("reviewed_at"),
        "synced_at": _opt("synced_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_comment(
    video_id: int,
    tier: int,
    text: str,
    image_ids: list[str] | None = None,
    source: str = "manual",
    review_status: str = "approved",
) -> int:
    """Insert a new comment row. Raises sqlite3.IntegrityError on
    UNIQUE(video_id, tier) violation — caller (T5 route) maps to 409.

    review_status 默认 'approved'：走 composer 的评论（人工手写 / 用户点
    AI 建议后自己保存）都是用户亲手确认过的，不进审核队列。'pending'
    只由批量生成服务经 upsert_ai_comment 写入。
    """
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO video_comments(video_id, tier, text, image_ids_json, source, review_status)
        VALUES(?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            video_id,
            tier,
            text,
            json.dumps(list(image_ids or []), ensure_ascii=False),
            source,
            review_status,
        ),
    )
    return int(cur.fetchone()[0])


def list_comments(video_id: int) -> list[dict[str, Any]]:
    """Return comments for a video, ordered by tier ascending."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM video_comments WHERE video_id=? ORDER BY tier ASC",
        (video_id,),
    ).fetchall()
    return [_row_to_comment_dict(r) for r in rows]


def get_comment(comment_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM video_comments WHERE id=?", (comment_id,),
    ).fetchone()
    return _row_to_comment_dict(row) if row else None


def update_comment(
    comment_id: int,
    *,
    text: str | None = None,
    image_ids: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Partial update. Returns the post-update row, or None if no such id.

    Caller is responsible for diff-and-cleanup of removed image_ids
    (T5 routes call mining_images_service.delete_images on the removed
    set) so this layer stays storage-only and free of side effects.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM video_comments WHERE id=?", (comment_id,),
    ).fetchone()
    if row is None:
        return None
    before_status = row["status"]
    sets: list[str] = []
    args: list[Any] = []
    if text is not None:
        sets.append("text=?")
        args.append(text)
    if image_ids is not None:
        sets.append("image_ids_json=?")
        args.append(json.dumps(list(image_ids), ensure_ascii=False))
    if status is not None:
        sets.append("status=?")
        args.append(status)
    if not sets:
        return _row_to_comment_dict(row)
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    args.append(comment_id)
    conn.execute(
        f"UPDATE video_comments SET {', '.join(sets)} WHERE id=?",
        args,
    )
    new_row = conn.execute(
        "SELECT * FROM video_comments WHERE id=?", (comment_id,),
    ).fetchone()
    # T3 hook — template library auto-ingest on draft→done.
    # isolation_level=None autocommits each execute(); the upsert runs
    # immediately after the UPDATE so consistency is fine.
    if new_row and before_status != "done" and new_row["status"] == "done":
        _upsert_template_from_comment(conn, dict(new_row))
    return _row_to_comment_dict(new_row) if new_row else None


def delete_comment(comment_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM video_comments WHERE id=?", (comment_id,))
    return cur.rowcount > 0


def set_ai_summary(video_id: int, text: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE videos SET ai_summary=? WHERE id=?", (text, video_id))


def bulk_mark_commented(video_ids: list[int], value: bool) -> int:
    """Flip already_commented for a batch. Returns row count touched.

    When marking true, stamp commented_source='manual' + commented_at=now;
    when un-marking, clear both metadata columns. Empty list returns 0
    without hitting the DB.
    """
    if not video_ids:
        return 0
    conn = get_conn()
    placeholders = ",".join("?" * len(video_ids))
    if value:
        sql = (
            f"UPDATE videos SET already_commented=1, commented_source='manual', "
            f"commented_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            f"WHERE id IN ({placeholders})"
        )
    else:
        sql = (
            f"UPDATE videos SET already_commented=0, commented_source=NULL, "
            f"commented_at=NULL WHERE id IN ({placeholders})"
        )
    cur = conn.execute(sql, list(video_ids))
    return cur.rowcount


def next_tier(video_id: int) -> int:
    """Next available tier number for a video (1-based)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(tier), 0) + 1 AS next FROM video_comments WHERE video_id=?",
        (video_id,),
    ).fetchone()
    return int(row["next"]) if row else 1


# ── Template DAO (v5) ──────────────────────────────────────────────────

class TemplateDuplicateError(Exception):
    """Raised by create_template/update_template when text_hash already exists.

    Has .existing_id to allow callers to surface "go to the existing one" UX.
    """
    def __init__(self, existing_id: int):
        super().__init__(f"template already exists (id={existing_id})")
        self.existing_id = existing_id


def _row_to_template_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "text": row["text"],
        "tags": json.loads(row["tags_json"]),
        "source_platform": row["source_platform"],
        "source_comment_id": row["source_comment_id"],
        "starred": bool(row["starred"]),
        "hidden": bool(row["hidden"]),
        "use_count": row["use_count"],
        "first_seen_at": row["first_seen_at"],
        "last_used_at": row["last_used_at"],
    }


def create_template(
    *,
    text: str,
    tags: list[str] | None = None,
    source_platform: str | None = None,
) -> int:
    """Manually create a template. Raises TemplateDuplicateError on dup."""
    conn = get_conn()
    text_hash = _hash_text(text)
    existing = conn.execute(
        "SELECT id FROM comment_templates WHERE text_hash=?", (text_hash,),
    ).fetchone()
    if existing:
        raise TemplateDuplicateError(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO comment_templates
          (text, text_hash, tags_json, source_platform)
        VALUES(?, ?, ?, ?)
        RETURNING id
        """,
        (text, text_hash, json.dumps(tags or [], ensure_ascii=False), source_platform),
    )
    return int(cur.fetchone()[0])


def update_template(
    template_id: int,
    *,
    text: str | None = None,
    tags: list[str] | None = None,
    starred: bool | None = None,
    hidden: bool | None = None,
) -> dict[str, Any] | None:
    conn = get_conn()
    sets: list[str] = []
    args: list[Any] = []
    if text is not None:
        sets.append("text=?")
        args.append(text)
        sets.append("text_hash=?")
        args.append(_hash_text(text))
    if tags is not None:
        sets.append("tags_json=?")
        args.append(json.dumps(tags, ensure_ascii=False))
    if starred is not None:
        sets.append("starred=?")
        args.append(1 if starred else 0)
    if hidden is not None:
        sets.append("hidden=?")
        args.append(1 if hidden else 0)
    if not sets:
        row = conn.execute("SELECT * FROM comment_templates WHERE id=?", (template_id,)).fetchone()
        return _row_to_template_dict(row) if row else None
    args.append(template_id)
    try:
        conn.execute(
            f"UPDATE comment_templates SET {', '.join(sets)} WHERE id=?", args,
        )
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            existing = conn.execute(
                "SELECT id FROM comment_templates WHERE text_hash=? AND id!=?",
                (_hash_text(text or ""), template_id),
            ).fetchone()
            if existing:
                raise TemplateDuplicateError(existing["id"]) from e
        raise
    row = conn.execute("SELECT * FROM comment_templates WHERE id=?", (template_id,)).fetchone()
    return _row_to_template_dict(row) if row else None


def delete_template(template_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM comment_templates WHERE id=?", (template_id,))
    return cur.rowcount > 0


def list_templates(
    *,
    search: str | None = None,
    tags: list[str] | None = None,
    platform: str | None = None,    # 'manual' = NULL source_platform
    starred: bool | None = None,
    hidden: str = "0",              # "0" (default), "1", or "all"
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    conn = get_conn()
    where: list[str] = []
    args: list[Any] = []

    if search:
        # Escape SQL wildcards in user input so `%` and `_` are literal.
        # ESCAPE '\\' enables \\% and \\_ as literal markers.
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("text LIKE ? ESCAPE '\\'")
        args.append(f"%{escaped}%")
    if platform == "manual":
        where.append("source_platform IS NULL")
    elif platform:
        where.append("source_platform=?")
        args.append(platform)
    if starred is True:
        where.append("starred=1")
    if hidden == "0":
        where.append("hidden=0")
    elif hidden == "1":
        where.append("hidden=1")
    # "all" → no hidden filter
    if tags:
        for tag in tags:
            where.append(
                "EXISTS (SELECT 1 FROM json_each(tags_json) WHERE value=?)"
            )
            args.append(tag)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM comment_templates {where_sql}", args,
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT * FROM comment_templates {where_sql}
        ORDER BY starred DESC, last_used_at DESC, use_count DESC
        LIMIT ? OFFSET ?
        """,
        (*args, limit, offset),
    ).fetchall()
    return {"items": [_row_to_template_dict(r) for r in rows], "total": total}


def bump_template_use(template_id: int) -> str | None:
    """Returns the template's text after bumping use_count + last_used_at."""
    conn = get_conn()
    row = conn.execute(
        """
        UPDATE comment_templates
        SET use_count = use_count + 1,
            last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=?
        RETURNING text
        """,
        (template_id,),
    ).fetchone()
    return row[0] if row else None


def bulk_import_templates(
    *,
    texts: list[str],
    tags: list[str] | None = None,
    source_platform: str | None = None,
) -> dict[str, int]:
    """Insert N rows, deduping by text_hash both within batch and vs DB.

    Returns {"created": N, "skipped_duplicates": M}.
    Empty / whitespace-only texts count as duplicates (skipped).
    """
    conn = get_conn()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    seen_hashes: set[str] = set()
    created = 0
    skipped = 0
    for raw in texts:
        text = raw.strip()
        if not text:
            skipped += 1
            continue
        h = _hash_text(text)
        if h in seen_hashes:
            skipped += 1
            continue
        seen_hashes.add(h)
        existing = conn.execute(
            "SELECT 1 FROM comment_templates WHERE text_hash=?", (h,),
        ).fetchone()
        if existing:
            skipped += 1
            continue
        conn.execute(
            """
            INSERT INTO comment_templates
              (text, text_hash, tags_json, source_platform)
            VALUES(?, ?, ?, ?)
            """,
            (text, h, tags_json, source_platform),
        )
        created += 1
    return {"created": created, "skipped_duplicates": skipped}


def list_used_tags() -> list[str]:
    """Return all distinct tags across all templates, alphabetically."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT value FROM comment_templates, json_each(tags_json) ORDER BY value"
    ).fetchall()
    return [r[0] for r in rows]


# ── Dedup helpers (used by mining collection) ─────────────────────────
def is_video_in_videos_table(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """videos 表精确 UNIQUE 查询，O(1)。供 mining 采集时跳过已抓视频。"""
    row = conn.execute(
        "SELECT 1 FROM videos WHERE platform=? AND platform_video_id=? LIMIT 1",
        (platform, platform_video_id),
    ).fetchone()
    return row is not None


def is_video_in_monitor_tasks(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """monitor_tasks 反查：LIKE + 正则精确匹配。

    monitor_tasks 没有独立的 platform_video_id 列，所以走两步：
      1. LIKE 加速过滤（idx_monitor_tasks_target_url 索引加速）
      2. 用 extract_platform_video_id() 正则二次确认，避免 url 子串误判
    """
    task_type = _PLATFORM_TO_MONITOR_TYPE.get(platform)
    if not task_type:
        return False

    candidates = conn.execute(
        "SELECT target_url FROM monitor_tasks WHERE type=? AND target_url LIKE ?",
        (task_type, f"%{platform_video_id}%"),
    ).fetchall()

    for (target_url,) in candidates:
        extracted = extract_platform_video_id(platform, target_url)
        if extracted == platform_video_id:
            return True
    return False


def is_video_tracked_anywhere(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """采集时用：videos OR monitor_tasks 任一存在即跳过。"""
    return (
        is_video_in_videos_table(conn, platform, platform_video_id)
        or is_video_in_monitor_tasks(conn, platform, platform_video_id)
    )


# V6 migration: composite index on monitor_tasks for dedup lookup performance.
_DDL_V6_MINING: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_monitor_tasks_target_url "
    "ON monitor_tasks(type, target_url)",
]


def apply_v6_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v5 → v6.

    Idempotent: CREATE INDEX IF NOT EXISTS handles re-runs.
    """
    for stmt in _DDL_V6_MINING:
        conn.execute(stmt)


# ── Schema v8 additions ─────────────────────────────────────────────────
# Brand pre-filter: track how many brand-seeded comments a video has
# (brand_comment_hits) and why it was excluded (exclude_reason).
# mining_jobs gains brand_keywords_json to store the seed keywords used
# for the brand detection pass.


def apply_v8_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v7 → v8.

    Adds brand pre-filter columns:
      - videos.brand_comment_hits INTEGER
      - videos.exclude_reason TEXT
      - mining_jobs.brand_keywords_json TEXT NOT NULL DEFAULT '[]'

    Each ALTER is guarded by PRAGMA table_info because SQLite has no
    ADD COLUMN IF NOT EXISTS — mirrors apply_v4_migration's pattern.
    """
    # Guard videos columns.
    videos_cols = set()
    for row in conn.execute("PRAGMA table_info(videos)").fetchall():
        try:
            videos_cols.add(row[1])
        except (IndexError, TypeError):
            videos_cols.add(row["name"])
    if "brand_comment_hits" not in videos_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN brand_comment_hits INTEGER")
    if "exclude_reason" not in videos_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN exclude_reason TEXT")

    # Guard mining_jobs column.
    jobs_cols = set()
    for row in conn.execute("PRAGMA table_info(mining_jobs)").fetchall():
        try:
            jobs_cols.add(row[1])
        except (IndexError, TypeError):
            jobs_cols.add(row["name"])
    if "brand_keywords_json" not in jobs_cols:
        conn.execute(
            "ALTER TABLE mining_jobs ADD COLUMN brand_keywords_json TEXT NOT NULL DEFAULT '[]'"
        )


# ── Schema v13 additions ────────────────────────────────────────────────
# 评论工作流 P1：搜索筛选参数 + 预筛热评快照。
#   - mining_jobs.filters_json：按平台分组的筛选条件（SearchFilters dump）。
#   - videos.top_comments_json：品牌预筛抓到的前 N 条评论快照
#     [{text, likes, author}...]。两个用途：① AI 生成环节当评论区语料，
#     免二次抓取（抖音走 TikHub 计费，省一次是一次）；② 被排除的视频
#     在 UI 可见命中了哪条评论。


def apply_v13_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v12 → v13.

    PRAGMA-guarded ALTERs（同 v8 写法）—— _migrate 每次启动都会重跑全部
    迁移函数，只能用幂等语句。
    """
    jobs_cols = set()
    for row in conn.execute("PRAGMA table_info(mining_jobs)").fetchall():
        try:
            jobs_cols.add(row[1])
        except (IndexError, TypeError):
            jobs_cols.add(row["name"])
    if "filters_json" not in jobs_cols:
        conn.execute(
            "ALTER TABLE mining_jobs ADD COLUMN filters_json TEXT NOT NULL DEFAULT '{}'"
        )

    videos_cols = set()
    for row in conn.execute("PRAGMA table_info(videos)").fetchall():
        try:
            videos_cols.add(row[1])
        except (IndexError, TypeError):
            videos_cols.add(row["name"])
    if "top_comments_json" not in videos_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN top_comments_json TEXT")


# ── Schema v14 additions ────────────────────────────────────────────────
# 评论工作流 P2：审核状态机。挂在 video_comments 上的五个新列：
#   review_status   '' | pending | approved | synced | executed
#                   ''=旧数据/人工评论（不进审核队列）；pending 仅由批量
#                   AI 生成写入；approved=人审通过；synced/executed 留给 P3。
#   template_id     生成时用的模板（软引用，不加 FK——模板删了留痕即可）
#   ai_flavor_score 确定性 AI 味评分（scoring/ai_flavor 各信号 points 之和）
#   reviewed_at / synced_at 审计时间戳
# 不重载现有 status（draft/assigned/done）——它挂着「→done 自动入模板库」
# 的 DAO 钩子，语义是「兼职执行进度」，与「内容审核」正交。


def apply_v14_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v13 → v14.

    PRAGMA-guarded ALTERs（同 v8/v13 写法），幂等。
    """
    cols = set()
    for row in conn.execute("PRAGMA table_info(video_comments)").fetchall():
        try:
            cols.add(row[1])
        except (IndexError, TypeError):
            cols.add(row["name"])
    if "review_status" not in cols:
        conn.execute(
            "ALTER TABLE video_comments ADD COLUMN review_status TEXT NOT NULL DEFAULT ''"
        )
    if "template_id" not in cols:
        conn.execute("ALTER TABLE video_comments ADD COLUMN template_id INTEGER")
    if "ai_flavor_score" not in cols:
        conn.execute("ALTER TABLE video_comments ADD COLUMN ai_flavor_score REAL")
    if "reviewed_at" not in cols:
        conn.execute("ALTER TABLE video_comments ADD COLUMN reviewed_at TEXT")
    if "synced_at" not in cols:
        conn.execute("ALTER TABLE video_comments ADD COLUMN synced_at TEXT")


# ── Review state machine (v14) ─────────────────────────────────────────


class TierOccupiedError(Exception):
    """upsert_ai_comment 撞上不可覆盖的楼层（人工写的 / 已通过 / 已执行）。"""

    def __init__(self, video_id: int, tier: int):
        super().__init__(f"tier {tier} of video {video_id} is occupied")
        self.video_id = video_id
        self.tier = tier


def upsert_ai_comment(
    video_id: int,
    tier: int,
    text: str,
    *,
    template_id: int | None = None,
    ai_flavor_score: float | None = None,
) -> int:
    """写入一条 AI 生成的评论草稿（review_status='pending'）。

    同楼层已有内容时的覆盖规则：仅当现有行是「AI 生成 + 未通过 +
    status=draft」才覆盖（重新生成场景）；人工写的、已通过/已同步的、
    兼职已执行的一律抛 TierOccupiedError，调用方按 skipped 记录。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM video_comments WHERE video_id=? AND tier=?",
        (video_id, tier),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            """
            INSERT INTO video_comments(video_id, tier, text, source, review_status,
                                       template_id, ai_flavor_score)
            VALUES(?, ?, ?, 'ai_suggested', 'pending', ?, ?)
            RETURNING id
            """,
            (video_id, tier, text, template_id, ai_flavor_score),
        )
        return int(cur.fetchone()[0])
    overwritable = (
        row["source"] == "ai_suggested"
        and (row["review_status"] or "") in ("", "pending")
        and row["status"] == "draft"
    )
    if not overwritable:
        raise TierOccupiedError(video_id, tier)
    conn.execute(
        """
        UPDATE video_comments
        SET text=?, template_id=?, ai_flavor_score=?, review_status='pending',
            reviewed_at=NULL,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=?
        """,
        (text, template_id, ai_flavor_score, row["id"]),
    )
    return int(row["id"])


def approve_comment(comment_id: int) -> dict[str, Any] | None:
    """单条通过：pending → approved（幂等：非 pending 不动，返回现状）。"""
    conn = get_conn()
    conn.execute(
        """
        UPDATE video_comments
        SET review_status='approved',
            reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=? AND review_status='pending'
        """,
        (comment_id,),
    )
    return get_comment(comment_id)


def approve_pending_for_videos(video_ids: list[int]) -> int:
    """批量通过：这些视频下所有 pending 评论 → approved。返回改动行数。"""
    if not video_ids:
        return 0
    conn = get_conn()
    placeholders = ",".join("?" * len(video_ids))
    cur = conn.execute(
        f"""
        UPDATE video_comments
        SET review_status='approved',
            reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE review_status='pending' AND video_id IN ({placeholders})
        """,
        list(video_ids),
    )
    return cur.rowcount


def get_template(template_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM comment_templates WHERE id=?", (template_id,),
    ).fetchone()
    return _row_to_template_dict(row) if row else None


# ── Schema v15 additions ────────────────────────────────────────────────
# 评论工作流 P3：腾讯文档同步对账表。一批 = 一次「同步已通过」动作，
# 记录写进了表格的哪个行区间（0-based，含边界），重试防双写按
# 表格「链接」列回读比对，此表用于人工排查 + 审计。
_DDL_V15_SYNC: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS sync_batches (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id          TEXT NOT NULL,
        sheet_id        TEXT NOT NULL DEFAULT '',
        row_start       INTEGER NOT NULL,
        row_end         INTEGER NOT NULL,
        video_ids_json  TEXT NOT NULL DEFAULT '[]',
        synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sync_batches_time ON sync_batches(synced_at DESC)",
]


def apply_v15_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v14 → v15. Idempotent."""
    for stmt in _DDL_V15_SYNC:
        conn.execute(stmt)


# ── 腾讯文档同步 DAO（v15）────────────────────────────────────────────


def list_approved_for_sync(video_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """待同步集合：excluded=0 且含 ≥1 条 review_status='approved' 评论的视频。

    返回 [{id, platform, url, title, comments: [{id, tier, text, image_ids}...]}]，
    comments 只含 approved 的、按 tier 升序。video_ids 传入时限定范围。
    """
    conn = get_conn()
    where = ["v.excluded=0", "c.review_status='approved'"]
    args: list[Any] = []
    if video_ids:
        placeholders = ",".join("?" * len(video_ids))
        where.append(f"v.id IN ({placeholders})")
        args.extend(video_ids)
    rows = conn.execute(
        f"""
        SELECT v.id AS video_id, v.platform, v.url, v.title,
               c.id AS comment_id, c.tier, c.text, c.image_ids_json
        FROM videos v
        JOIN video_comments c ON c.video_id = v.id
        WHERE {' AND '.join(where)}
        ORDER BY v.id ASC, c.tier ASC
        """,
        args,
    ).fetchall()
    out: list[dict[str, Any]] = []
    by_vid: dict[int, dict[str, Any]] = {}
    for r in rows:
        vid = r["video_id"]
        if vid not in by_vid:
            by_vid[vid] = {
                "id": vid,
                "platform": r["platform"],
                "url": r["url"],
                "title": r["title"] or "",
                "comments": [],
            }
            out.append(by_vid[vid])
        by_vid[vid]["comments"].append({
            "id": r["comment_id"],
            "tier": r["tier"],
            "text": r["text"] or "",
            "image_ids": json.loads(r["image_ids_json"] or "[]"),
        })
    return out


def create_sync_batch(
    doc_id: str, sheet_id: str, row_start: int, row_end: int, video_ids: list[int],
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO sync_batches(doc_id, sheet_id, row_start, row_end, video_ids_json)
        VALUES(?,?,?,?,?)
        RETURNING id
        """,
        (doc_id, sheet_id, row_start, row_end,
         json.dumps(list(video_ids), ensure_ascii=False)),
    )
    return int(cur.fetchone()[0])


def mark_comments_synced(comment_ids: list[int]) -> int:
    """approved → synced（幂等：只动 approved 行）。返回改动行数。"""
    if not comment_ids:
        return 0
    conn = get_conn()
    placeholders = ",".join("?" * len(comment_ids))
    cur = conn.execute(
        f"""
        UPDATE video_comments
        SET review_status='synced',
            synced_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE review_status='approved' AND id IN ({placeholders})
        """,
        list(comment_ids),
    )
    return cur.rowcount


# ── Brand pre-filter setters ──────────────────────────────────────────


def mark_brand_excluded(video_id: int, hits: int) -> bool:
    """Mark a video as excluded by brand detection.

    Sets excluded=1, exclude_reason='brand_seeded', brand_comment_hits=hits.
    Returns True if the row existed and was updated.
    """
    conn = get_conn()
    cur = conn.execute(
        "UPDATE videos SET excluded=1, exclude_reason='brand_seeded', brand_comment_hits=? WHERE id=?",
        (int(hits), video_id),
    )
    return cur.rowcount > 0


def mark_featured_excluded(video_id: int) -> bool:
    """Mark a video as excluded because its comment area is curated-only.

    评论区开启了「精选后可见」（B 站「评论被up主精选后，对所有人可见」）：引流评论
    发了也没人看得见。Sets excluded=1, exclude_reason='featured_comments'；行留在
    videos 表里，后续任务靠全局去重直接跳过，不会反复抓到、反复探测。
    Returns True if the row existed and was updated.
    """
    conn = get_conn()
    cur = conn.execute(
        "UPDATE videos SET excluded=1, exclude_reason='featured_comments' WHERE id=?",
        (video_id,),
    )
    return cur.rowcount > 0


def set_brand_hits(video_id: int, hits: int) -> bool:
    """Record brand comment hit count without excluding the video.

    Used when hits < threshold — we record the count for visibility but
    do not flip excluded.  Returns True if the row existed.
    """
    conn = get_conn()
    cur = conn.execute(
        "UPDATE videos SET brand_comment_hits=? WHERE id=?",
        (int(hits), video_id),
    )
    return cur.rowcount > 0


def set_top_comments(video_id: int, comments: list[dict[str, Any]]) -> bool:
    """Persist the prefilter's scraped hot-comment snapshot (v13).

    每条只留 text / likes / author 三个字段，text 截 500 字符 —— 快照是
    「生成语料 + 命中证据」，不是全量存档；防单条超长评论把 videos 行撑爆。
    """
    slim = [
        {
            "text": str(c.get("text") or "")[:500],
            "likes": c.get("likes"),
            "author": str(c.get("author") or "")[:80],
        }
        for c in comments
    ]
    conn = get_conn()
    cur = conn.execute(
        "UPDATE videos SET top_comments_json=? WHERE id=?",
        (json.dumps(slim, ensure_ascii=False), video_id),
    )
    return cur.rowcount > 0


def videos_for_prefilter(job_id: int, platform: str) -> list[dict[str, Any]]:
    """Return [{id, url}, ...] for not-excluded videos in this job+platform.

    Used by the runner's brand pre-filter pass to enumerate which videos
    to check for brand-seeded comments.  Only videos with excluded=0 are
    returned so already-excluded rows are not re-processed.
    """
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT DISTINCT v.id, v.url
        FROM videos v
        JOIN video_source_keywords vsk ON vsk.video_id = v.id
        WHERE vsk.job_id = ? AND v.platform = ? AND v.excluded = 0
        ORDER BY v.first_seen_at ASC
        """,
        (job_id, platform),
    ).fetchall()
    return [{"id": r["id"], "url": r["url"]} for r in rows]
