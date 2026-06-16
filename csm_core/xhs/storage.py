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

_SCHEMA_VERSION = 1

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
        _local.conn = conn
    return conn
