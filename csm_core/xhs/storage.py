"""sqlite3 storage for the 小红书 note editor —— standalone xhs.db.

为什么独立 db：小红书编辑器 schema 极小（P0 仅 drafts 一张表）、无调度器、
与 monitor/mining 完全无关联查询，所以自己拥有 ``<config_dir>/xhs.db``，
不搭车 monitor.db。

连接生命周期 / 机制照搬 ``csm_core/monitor/storage.py``（threading.local
每线程连接 + WAL + idempotent init_db + schema_meta 版本）。区别：加
``_ensure_initialized()`` 懒初始化 —— 路由无需在 lifespan 显式 wiring，
生产首个请求自动在默认路径建库；测试通过 ``init_db(tmp)`` 先占位覆盖。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from csm_core.config import default_config_dir

_SCHEMA_VERSION = 2

# ── Schema ──────────────────────────────────────────────────────────────────
_DDL_V1 = [
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS xhs_drafts (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        topics_json TEXT NOT NULL DEFAULT '[]',
        image_ids_json TEXT NOT NULL DEFAULT '[]',
        cover_index INTEGER NOT NULL DEFAULT 0,
        theme_id TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS xhs_custom_assets (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_xhs_assets_kind ON xhs_custom_assets(kind, created_at DESC)",
]


# ── Connection management ───────────────────────────────────────────────────
_local = threading.local()
_db_path: Path | None = None
_init_lock = threading.Lock()
_initialized = False


def default_db_path() -> Path:
    """``<config_dir>/xhs.db`` —— 与 settings.json / monitor.db 同目录。"""
    return default_config_dir() / "xhs.db"


def init_db(db_path: Path) -> None:
    """配置 storage 使用给定 db 路径。Idempotent；换路径视为编程错误并拒绝。"""
    global _db_path, _initialized
    db_path = Path(db_path)
    with _init_lock:
        if _initialized:
            if _db_path != db_path:
                raise RuntimeError(
                    f"xhs storage already initialized at {_db_path}, refusing to re-init at {db_path}"
                )
            return
        _db_path = db_path
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        # 一次性连接跑迁移，确保 schema 就绪后再有线程取自己的连接。
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
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
        (str(_SCHEMA_VERSION),),
    )


def _ensure_initialized() -> None:
    """生产路径：首次取连接时若未初始化，则在默认路径建库。

    双重检查锁定：这里的 ``if not _initialized`` 是无锁快速路径（GIL 保证
    bool 读原子）。权威判断在 ``init_db`` 内部的 ``with _init_lock`` 段里
    重做 —— 即便两个线程同时通过这里的检查、同时调 init_db，锁会串行化，
    第一个建库、第二个命中 idempotent 直接返回，无重复建库、无竞态。

    ⚠ 不要把 ``with _init_lock`` 挪到这里再调 init_db —— _init_lock 是
    非可重入 threading.Lock，init_db 内部会再次 acquire 同一把锁，造成死锁。

    测试通过 fixture 先 ``init_db(tmp)`` 占位，``_initialized`` 已 True，
    这里成为 no-op，于是测试永不会写到真实 ``%LOCALAPPDATA%`` 目录。
    """
    if not _initialized:
        init_db(default_db_path())


def get_conn() -> sqlite3.Connection:
    """返回当前线程的连接（按需创建）。每连接预置 WAL + Row factory。"""
    _ensure_initialized()
    assert _db_path is not None  # _ensure_initialized 保证
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(_db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


# ── Draft CRUD ──────────────────────────────────────────────────────────────
def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "topics": json.loads(row["topics_json"]) if row["topics_json"] else [],
        "image_ids": json.loads(row["image_ids_json"]) if row["image_ids_json"] else [],
        "cover_index": row["cover_index"],
        "theme_id": row["theme_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_draft(
    *,
    title: str = "",
    body: str = "",
    topics: list[str] | None = None,
    image_ids: list[str] | None = None,
    cover_index: int = 0,
    theme_id: str | None = None,
) -> str:
    """插入一条草稿，返回新生成的 uuid4 hex id。"""
    conn = get_conn()
    draft_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO xhs_drafts(id, title, body, topics_json, image_ids_json, cover_index, theme_id)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id,
            title,
            body,
            json.dumps(list(topics or []), ensure_ascii=False),
            json.dumps(list(image_ids or []), ensure_ascii=False),
            cover_index,
            theme_id,
        ),
    )
    return draft_id


def get_draft(draft_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM xhs_drafts WHERE id=?", (draft_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_drafts() -> list[dict[str, Any]]:
    """最近编辑的排最前。"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM xhs_drafts ORDER BY updated_at DESC, id DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def update_draft(
    draft_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    topics: list[str] | None = None,
    image_ids: list[str] | None = None,
    cover_index: int | None = None,
    theme_id: str | None = None,
) -> dict[str, Any] | None:
    """部分更新。返回更新后的行，或 None（无此 id）。

    约定：``None`` = 该字段「未提供」，保持原值。P0 不需要「把 theme 清回
    NULL」这种语义（主题切换在 P3），所以 theme_id 也按 ``is not None`` 处理；
    将来 P3 需要清空时再引入 sentinel。
    """
    conn = get_conn()
    row = conn.execute("SELECT * FROM xhs_drafts WHERE id=?", (draft_id,)).fetchone()
    if row is None:
        return None
    sets: list[str] = []
    args: list[Any] = []
    if title is not None:
        sets.append("title=?")
        args.append(title)
    if body is not None:
        sets.append("body=?")
        args.append(body)
    if topics is not None:
        sets.append("topics_json=?")
        args.append(json.dumps(list(topics), ensure_ascii=False))
    if image_ids is not None:
        sets.append("image_ids_json=?")
        args.append(json.dumps(list(image_ids), ensure_ascii=False))
    if cover_index is not None:
        sets.append("cover_index=?")
        args.append(cover_index)
    if theme_id is not None:
        sets.append("theme_id=?")
        args.append(theme_id)
    if not sets:
        return _row_to_dict(row)
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    args.append(draft_id)
    conn.execute(f"UPDATE xhs_drafts SET {', '.join(sets)} WHERE id=?", args)
    new_row = conn.execute("SELECT * FROM xhs_drafts WHERE id=?", (draft_id,)).fetchone()
    return _row_to_dict(new_row) if new_row else None


def delete_draft(draft_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM xhs_drafts WHERE id=?", (draft_id,))
    return cur.rowcount > 0


# ── Custom Assets CRUD ──────────────────────────────────────────────────────
def _row_to_asset_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "payload": json.loads(row["payload_json"]),
        "created_at": row["created_at"],
    }


def create_custom_asset(*, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """新建一条自定义素材。kind ∈ {template,copy,topic_group}（校验在路由层）。"""
    asset_id = uuid.uuid4().hex
    conn = get_conn()
    conn.execute(
        "INSERT INTO xhs_custom_assets(id, kind, payload_json) VALUES(?, ?, ?)",
        (asset_id, kind, json.dumps(payload, ensure_ascii=False)),
    )
    row = conn.execute(
        "SELECT * FROM xhs_custom_assets WHERE id = ?", (asset_id,)
    ).fetchone()
    return _row_to_asset_dict(row)


def list_custom_assets(kind: str | None = None) -> list[dict[str, Any]]:
    """列自定义素材，按 created_at DESC, rowid DESC（后建的在前）。kind 给定则只列该类。"""
    conn = get_conn()
    if kind is None:
        rows = conn.execute(
            "SELECT * FROM xhs_custom_assets ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM xhs_custom_assets WHERE kind = ? ORDER BY created_at DESC, rowid DESC",
            (kind,),
        ).fetchall()
    return [_row_to_asset_dict(r) for r in rows]


def delete_custom_asset(asset_id: str) -> bool:
    """删一条，返回是否真的删到。"""
    conn = get_conn()
    cur = conn.execute("DELETE FROM xhs_custom_assets WHERE id = ?", (asset_id,))
    return cur.rowcount > 0
