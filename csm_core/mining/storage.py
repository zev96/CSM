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

    Idempotent: CREATE TABLE / CREATE INDEX use IF NOT EXISTS.
    Historical backfill of existing done comments is in T3.
    """
    for stmt in _DDL_V5_TEMPLATES:
        conn.execute(stmt)


def get_conn() -> sqlite3.Connection:
    """Thin alias — mining shares monitor's connection pool."""
    return monitor_storage.get_conn()


# ── Job CRUD ──────────────────────────────────────────────────────────
def create_job(keyword: str, platforms: list[str], target_per_platform: int) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, status, progress_json)
        VALUES(?, ?, ?, 'pending', ?)
        RETURNING id
        """,
        (
            keyword,
            json.dumps(platforms, ensure_ascii=False),
            target_per_platform,
            json.dumps({p: {"got": 0, "target": target_per_platform, "phase": "queued"} for p in platforms}, ensure_ascii=False),
        ),
    )
    return int(cur.fetchone()[0])


def mark_started(job_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE mining_jobs SET status='running', started_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (job_id,),
    )


def update_platform_progress(job_id: int, platform: str, *, got: int, target: int, phase: str, note: str = "") -> None:
    conn = get_conn()
    row = conn.execute("SELECT progress_json FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return
    progress: dict[str, Any] = json.loads(row["progress_json"]) if row["progress_json"] else {}
    progress[platform] = {"got": got, "target": target, "phase": phase, "note": note}
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
    rows = conn.execute(
        "SELECT * FROM mining_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_job_dict(r) for r in rows]


def _row_to_job_dict(row) -> dict[str, Any]:
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
        SELECT v.*, GROUP_CONCAT(DISTINCT vsk.keyword) AS source_keywords
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
        "source_keywords": [k for k in keys_csv.split(",") if k],
    }


def soft_delete_video(video_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("UPDATE videos SET excluded=1 WHERE id=?", (video_id,))
    return cur.rowcount > 0


# ── Video comments (v4) ───────────────────────────────────────────────
def _row_to_comment_dict(row) -> dict[str, Any]:
    image_ids = json.loads(row["image_ids_json"]) if row["image_ids_json"] else []
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
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_comment(
    video_id: int,
    tier: int,
    text: str,
    image_ids: list[str] | None = None,
    source: str = "manual",
) -> int:
    """Insert a new comment row. Raises sqlite3.IntegrityError on
    UNIQUE(video_id, tier) violation — caller (T5 route) maps to 409."""
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO video_comments(video_id, tier, text, image_ids_json, source)
        VALUES(?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            video_id,
            tier,
            text,
            json.dumps(list(image_ids or []), ensure_ascii=False),
            source,
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
