# 引流评论模板库 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 CSM mining 模块加一个跨视频复用历史评论的"模板库"，含三个使用入口（CommentComposer 上方 chips 行 + 右侧抽屉 + 设置页独立管理 section）。

**Architecture:** 后端新建独立 `comment_templates` 表（SQLite schema v5），通过 `update_comment` DAO 钩子在评论 `status: draft → done` 时自动 UPSERT 入库。提供 7 个 REST 端点。前端 Pinia store 独立、4 个新 Vue 组件 + Icon 新增 3 个 SVG path。

**Tech Stack:** Python 3.11 + FastAPI + sqlite3 + pytest（后端）；Vue 3 + TypeScript + Pinia + Vite + 项目自研 feather-icons 风格 `<Icon name="..."/>`（前端）。

**Spec:** [docs/superpowers/specs/2026-05-19-comment-template-library-design.md](../specs/2026-05-19-comment-template-library-design.md)

---

## 批次拆分

| 批 | 任务 | 依赖 | 说明 |
|---|---|---|---|
| 批 1 | T1 → T2 → T3 → T4 | 无 | 后端 DAO 层（同文件改，串行）|
| 批 2 | T5、T6、T7 | 批 1 | 后端 API（不同路由，可并行）|
| 批 3 | T8、T9 | 无（独立前端）| Icon 新增 + Pinia store |
| 批 4 | T10 → T11 → T12 → T13 → T14 | 批 2 + 批 3 | 前端 UI（共享 store，建议串行）|

总计 **14 个任务**。

---

## T1 — Schema v5 建表 + 迁移注册

**Files:**
- Modify: `csm_core/mining/storage.py:94-138`（在 `_DDL_V4_MINING` / `apply_v4_migration` 后追加 v5 块）
- Modify: `csm_core/monitor/storage.py:27`（`_SCHEMA_VERSION` 4 → 5）+ `:129-145`（`_migrate` 末尾追加 `apply_v5_migration`）
- Test: `csm_core/mining/test_templates.py`（新建）

- [ ] **Step 1: 写第一个测试 —— v5 升级后表存在 + 重跑幂等**

```python
# csm_core/mining/test_templates.py
import sqlite3
import pytest
from csm_core.monitor import storage as monitor_storage
from csm_core.mining import storage as mining_storage


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    monitor_storage.init_db(str(db))
    return monitor_storage.get_conn()


def test_v5_creates_templates_table(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(comment_templates)").fetchall()}
    assert {
        "id", "text", "text_hash", "tags_json", "source_platform",
        "source_comment_id", "starred", "hidden", "use_count",
        "first_seen_at", "last_used_at",
    } <= cols


def test_v5_migration_idempotent(conn):
    # Re-run apply_v5_migration on already-migrated DB — should not raise.
    mining_storage.apply_v5_migration(conn)
    mining_storage.apply_v5_migration(conn)
    # Table still has zero rows
    assert conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0] == 0


def test_v5_indexes_exist(conn):
    idx = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='comment_templates'"
    ).fetchall()}
    assert "idx_templates_starred_last" in idx
    assert "idx_templates_hidden" in idx
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 3 个测试全 FAIL（`PRAGMA table_info(comment_templates)` 返回空 → assert 失败）

- [ ] **Step 3: 在 `csm_core/mining/storage.py` 加 v5 DDL + migration 函数**

在文件 `apply_v4_migration` 函数（约第 138 行结束）之后追加：

```python
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
```

- [ ] **Step 4: 修改 `csm_core/monitor/storage.py` 注册 v5**

改两处：

```python
# Line 27 — bump version
_SCHEMA_VERSION = 5
```

```python
# In _migrate() function (around line 141, after apply_v4_migration line):
mining_storage.apply_v4_migration(conn)
# v5: comment template library — see csm_core/mining/storage.py
mining_storage.apply_v5_migration(conn)
```

- [ ] **Step 5: 跑测试验证全过**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 3 PASS

- [ ] **Step 6: 跑现有 monitor / mining 测试，确保未破坏**

```bash
cd D:/CSM && python -m pytest csm_core/monitor csm_core/mining -v
```
Expected: 全部 PASS（无回归）

- [ ] **Step 7: Commit**

```bash
git add csm_core/mining/storage.py csm_core/mining/test_templates.py csm_core/monitor/storage.py
git commit -m "feat(mining/templates): T1 schema v5 — comment_templates table + migration"
```

---

## T2 — 文本归一化 + upsert_template_from_comment DAO

**Files:**
- Modify: `csm_core/mining/storage.py`（在 v5 DDL 后追加 helper + DAO）
- Test: `csm_core/mining/test_templates.py`

- [ ] **Step 1: 写测试 —— 归一化 + 首次插入 + 同 hash 第二次 UPSERT**

在 `test_templates.py` 末尾追加：

```python
import json
from csm_core.mining.storage import (
    _normalize_text, _hash_text, _upsert_template_from_comment,
)


def test_normalize_strips_and_lowers():
    assert _normalize_text("  Hello World  ") == "hello world"
    assert _normalize_text("很赞！") == "很赞！"  # 中文 + 标点保留
    assert _normalize_text("test\n") == "test"


def test_hash_is_deterministic():
    assert _hash_text("hello") == _hash_text("HELLO")
    assert _hash_text("hello") == _hash_text("  hello  ")
    assert _hash_text("hello") != _hash_text("hello!")


def test_upsert_inserts_new_template(conn):
    # Create a video + comment so source_comment_id is valid
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','vid1','http://x')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '吸力够大', 'done')")
    comment_row = dict(conn.execute(
        "SELECT id, video_id, text FROM video_comments WHERE id=1"
    ).fetchone())

    _upsert_template_from_comment(conn, comment_row)

    row = conn.execute("SELECT text, text_hash, source_platform, source_comment_id, use_count FROM comment_templates").fetchone()
    assert row["text"] == "吸力够大"
    assert row["text_hash"] == _hash_text("吸力够大")
    assert row["source_platform"] == "kuaishou"
    assert row["source_comment_id"] == 1
    assert row["use_count"] == 1


def test_upsert_second_time_bumps_use_count(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','vid1','http://x')")
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','vid2','http://y')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '吸力够大', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(2, 1, '吸力够大', 'done')")
    c1 = dict(conn.execute("SELECT id, video_id, text FROM video_comments WHERE id=1").fetchone())
    c2 = dict(conn.execute("SELECT id, video_id, text FROM video_comments WHERE id=2").fetchone())

    _upsert_template_from_comment(conn, c1)
    _upsert_template_from_comment(conn, c2)

    rows = conn.execute("SELECT COUNT(*), MAX(use_count), MIN(source_comment_id) FROM comment_templates").fetchone()
    assert rows[0] == 1                  # only 1 row (dedup)
    assert rows[1] == 2                  # use_count bumped
    assert rows[2] == 1                  # source_comment_id stays at first
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 4 个新测试 FAIL（`_normalize_text` / `_hash_text` / `_upsert_template_from_comment` 不存在）

- [ ] **Step 3: 在 `csm_core/mining/storage.py` 加归一化工具 + UPSERT DAO**

在 `apply_v5_migration` 函数后追加：

```python
import hashlib  # already imported? check top of file; if not, add to imports


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
```

如果 `hashlib` 尚未在文件顶部导入，在第 18 行附近 `import json` 旁追加 `import hashlib`。

- [ ] **Step 4: 跑测试验证全过**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 7 PASS（含 T1 的 3 个 + T2 的 4 个）

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/storage.py csm_core/mining/test_templates.py
git commit -m "feat(mining/templates): T2 text normalization + upsert DAO"
```

---

## T3 — 历史回填 + 挂 update_comment 钩子

**Files:**
- Modify: `csm_core/mining/storage.py`：① `apply_v5_migration` 内部加回填；② `update_comment` 函数加 `draft → done` 钩子
- Test: `csm_core/mining/test_templates.py`

- [ ] **Step 1: 写测试 —— 历史回填 + 钩子触发**

追加到 `test_templates.py`：

```python
def test_backfill_inserts_existing_done_comments(tmp_path):
    """Fresh DB → manually seed v4 state → upgrade v5 → assert backfill ran."""
    db = tmp_path / "back.db"
    # Use a fresh init that runs all migrations (v1 → v5)
    monitor_storage._db_path = None  # reset module state for clean test
    monitor_storage._initialized = False
    monitor_storage.init_db(str(db))
    conn = monitor_storage.get_conn()
    # Seed 3 done comments + 1 draft (draft should NOT be backfilled)
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('kuaishou','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'A', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 2, 'B', 'done')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 3, 'C', 'draft')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 4, 'A', 'done')")  # dup of 'A'

    # Simulate v5 backfill (call it directly)
    mining_storage._backfill_v5_templates(conn)

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 2  # 'A' + 'B' (C is draft, second 'A' deduped)
    uc = conn.execute("SELECT use_count FROM comment_templates WHERE text='A'").fetchone()[0]
    assert uc == 2  # 'A' got hit twice


def test_update_comment_draft_to_done_triggers_upsert(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, '新评论', 'draft')")

    n_before = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_before == 0

    mining_storage.update_comment(1, status="done")

    n_after = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n_after == 1
    row = conn.execute("SELECT text, source_platform FROM comment_templates").fetchone()
    assert row["text"] == "新评论"
    assert row["source_platform"] == "douyin"


def test_update_comment_status_unchanged_no_trigger(conn):
    conn.execute("INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','v1','http://1')")
    conn.execute("INSERT INTO video_comments(video_id, tier, text, status) VALUES(1, 1, 'X', 'done')")

    mining_storage.update_comment(1, text="X")  # status not changed

    n = conn.execute("SELECT COUNT(*) FROM comment_templates").fetchone()[0]
    assert n == 0  # no trigger — only draft→done triggers
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 3 个新测试 FAIL

- [ ] **Step 3: 在 `apply_v5_migration` 里追加回填调用**

修改 `apply_v5_migration`：

```python
def apply_v5_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v4 → v5.

    Idempotent: CREATE TABLE / CREATE INDEX use IF NOT EXISTS;
    backfill uses UPSERT so re-runs are safe.
    """
    for stmt in _DDL_V5_TEMPLATES:
        conn.execute(stmt)
    _backfill_v5_templates(conn)


def _backfill_v5_templates(conn: sqlite3.Connection) -> None:
    """Scan all existing done comments and upsert them as templates.

    Runs in chronological order so first_seen_at matches the earliest
    occurrence. Safe to re-run (ON CONFLICT bumps use_count).
    """
    rows = conn.execute(
        "SELECT id, video_id, text FROM video_comments "
        "WHERE status='done' ORDER BY created_at ASC"
    ).fetchall()
    for row in rows:
        _upsert_template_from_comment(conn, dict(row))
```

- [ ] **Step 4: 修改 `update_comment` 函数挂钩子**

[storage.py:580](csm_core/mining/storage.py:580) `update_comment` 函数，在 `_row_to_comment_dict(new_row)` return 之前判断状态翻转：

```python
def update_comment(
    comment_id: int,
    *,
    text: str | None = None,
    image_ids: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM video_comments WHERE id=?", (comment_id,),
    ).fetchone()
    if row is None:
        return None
    before_status = row["status"]                                  # ← NEW
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
    # ── NEW: T3 hook — template library auto-ingest on draft→done ────
    if new_row and before_status != "done" and new_row["status"] == "done":
        _upsert_template_from_comment(conn, dict(new_row))
    return _row_to_comment_dict(new_row) if new_row else None
```

- [ ] **Step 5: 跑测试验证全过**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 10 PASS（含 T1 3 + T2 4 + T3 3）

- [ ] **Step 6: Commit**

```bash
git add csm_core/mining/storage.py csm_core/mining/test_templates.py
git commit -m "feat(mining/templates): T3 backfill + update_comment auto-ingest hook"
```

---

## T4 — Template CRUD DAO + bulk_import + bump_use + list_used_tags

**Files:**
- Modify: `csm_core/mining/storage.py`（在 T2 helper 后追加 7 个公开 DAO）
- Test: `csm_core/mining/test_templates.py`

- [ ] **Step 1: 写测试 —— 7 个 DAO 函数**

追加到 `test_templates.py`：

```python
def test_create_template_manual(conn):
    tid = mining_storage.create_template(
        text="手动新建一条", tags=["种草", "测试"], source_platform=None,
    )
    row = conn.execute("SELECT * FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["text"] == "手动新建一条"
    assert json.loads(row["tags_json"]) == ["种草", "测试"]
    assert row["source_platform"] is None
    assert row["use_count"] == 0


def test_create_template_duplicate_raises(conn):
    mining_storage.create_template(text="重复条目")
    with pytest.raises(mining_storage.TemplateDuplicateError) as exc:
        mining_storage.create_template(text="重复条目")
    assert exc.value.existing_id > 0


def test_update_template_partial(conn):
    tid = mining_storage.create_template(text="原文本", tags=["a"])
    mining_storage.update_template(tid, text="新文本", starred=True)
    row = conn.execute("SELECT text, starred, hidden FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["text"] == "新文本"
    assert row["starred"] == 1
    assert row["hidden"] == 0


def test_delete_template(conn):
    tid = mining_storage.create_template(text="删我")
    assert mining_storage.delete_template(tid) is True
    assert mining_storage.delete_template(tid) is False  # already gone


def test_list_templates_filters_and_orders(conn):
    a = mining_storage.create_template(text="A 种草", tags=["种草"])
    b = mining_storage.create_template(text="B 对比", tags=["对比"])
    c = mining_storage.create_template(text="C 种草对比", tags=["种草", "对比"])
    mining_storage.update_template(b, starred=True)

    res = mining_storage.list_templates(limit=10, offset=0)
    assert res["total"] == 3
    # starred first
    assert res["items"][0]["id"] == b

    res = mining_storage.list_templates(tags=["种草", "对比"])
    assert {r["id"] for r in res["items"]} == {c}  # 取交集

    res = mining_storage.list_templates(search="种草")
    assert {r["id"] for r in res["items"]} == {a, c}


def test_bump_use(conn):
    tid = mining_storage.create_template(text="复用我")
    text = mining_storage.bump_template_use(tid)
    assert text == "复用我"
    row = conn.execute("SELECT use_count FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["use_count"] == 1
    mining_storage.bump_template_use(tid)
    row = conn.execute("SELECT use_count FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row["use_count"] == 2


def test_bulk_import_with_dedup(conn):
    mining_storage.create_template(text="已存在 1")
    res = mining_storage.bulk_import_templates(
        texts=["新条目 1", "新条目 2", "已存在 1", "新条目 1"],
        tags=["导入"],
        source_platform="manual",
    )
    assert res["created"] == 2  # "新条目 1" / "新条目 2"
    assert res["skipped_duplicates"] == 2  # "已存在 1" (db) + "新条目 1" (dupe in batch)


def test_list_used_tags(conn):
    mining_storage.create_template(text="x", tags=["a", "b"])
    mining_storage.create_template(text="y", tags=["b", "c"])
    tags = mining_storage.list_used_tags()
    assert tags == ["a", "b", "c"]  # dedup + sorted
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 8 个新测试 FAIL

- [ ] **Step 3: 在 `csm_core/mining/storage.py` 末尾追加 DAO 函数**

```python
# ── Template DAO (v5) ──────────────────────────────────────────────────

class TemplateDuplicateError(Exception):
    """Raised by create_template when text_hash already exists. Has .existing_id."""
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
                (_hash_text(text), template_id),
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
        where.append("text LIKE ?")
        args.append(f"%{search}%")
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
    # "all" → no filter
    if tags:
        # 取交集：对每个 tag 校验存在性
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
```

- [ ] **Step 4: 跑测试验证全过**

```bash
cd D:/CSM && python -m pytest csm_core/mining/test_templates.py -v
```
Expected: 18 PASS（T1 3 + T2 4 + T3 3 + T4 8）

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/storage.py csm_core/mining/test_templates.py
git commit -m "feat(mining/templates): T4 template CRUD + bulk_import + bump_use DAOs"
```

---

## T5 — REST API: GET /templates + GET /templates/tags

**Files:**
- Modify: `sidecar/csm_sidecar/routes/mining.py`（末尾追加路由 + pydantic schema）
- Test: `sidecar/csm_sidecar/tests/test_templates_api.py`（新建）

- [ ] **Step 1: 写测试 —— list + tags 端点**

```python
# sidecar/csm_sidecar/tests/test_templates_api.py
import pytest
from fastapi.testclient import TestClient
from csm_core.mining import storage as mining_storage
from sidecar.csm_sidecar.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    from csm_core.monitor import storage as monitor_storage
    db = tmp_path / "api.db"
    monitor_storage._db_path = None
    monitor_storage._initialized = False
    monitor_storage.init_db(str(db))
    monkeypatch.setenv("CSM_SIDECAR_TOKEN", "test-token")
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer test-token"
    return c


def test_list_templates_empty(client):
    r = client.get("/api/mining/templates")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


def test_list_templates_with_filters(client):
    mining_storage.create_template(text="A 种草", tags=["种草"])
    mining_storage.create_template(text="B 对比", tags=["对比"])
    mining_storage.update_template(
        mining_storage.create_template(text="C 都有", tags=["种草", "对比"]),
        starred=True,
    )

    # No filter — 3 items, starred first
    r = client.get("/api/mining/templates")
    body = r.json()
    assert body["total"] == 3
    assert body["items"][0]["text"] == "C 都有"

    # Tag filter — intersection
    r = client.get("/api/mining/templates?tags=种草,对比")
    assert {it["text"] for it in r.json()["items"]} == {"C 都有"}

    # Search
    r = client.get("/api/mining/templates?search=对比")
    assert {it["text"] for it in r.json()["items"]} == {"B 对比", "C 都有"}


def test_list_used_tags(client):
    mining_storage.create_template(text="x", tags=["a", "b"])
    mining_storage.create_template(text="y", tags=["b", "c"])
    r = client.get("/api/mining/templates/tags")
    assert r.json() == {"tags": ["a", "b", "c"]}
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM && python -m pytest sidecar/csm_sidecar/tests/test_templates_api.py -v
```
Expected: 3 FAIL（404 路由不存在）

- [ ] **Step 3: 在 `routes/mining.py` 末尾追加 list + tags 路由**

```python
# ── Comment templates (v5) ─────────────────────────────────────────────


class TemplateListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


@router.get("/api/mining/templates", response_model=TemplateListResponse)
async def list_templates(
    search: str | None = None,
    tags: str | None = Query(default=None, description="CSV of tag names, intersection"),
    platform: str | None = None,
    starred: bool | None = None,
    hidden: str = Query(default="0", pattern="^(0|1|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    return mining_storage.list_templates(
        search=search,
        tags=tag_list,
        platform=platform,
        starred=starred,
        hidden=hidden,
        limit=limit,
        offset=offset,
    )


@router.get("/api/mining/templates/tags")
async def list_template_tags() -> dict[str, list[str]]:
    return {"tags": mining_storage.list_used_tags()}
```

- [ ] **Step 4: 跑测试验证全过**

```bash
cd D:/CSM && python -m pytest sidecar/csm_sidecar/tests/test_templates_api.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/mining.py sidecar/csm_sidecar/tests/test_templates_api.py
git commit -m "feat(mining/templates): T5 API GET /templates + GET /templates/tags"
```

---

## T6 — REST API: POST/PATCH/DELETE/use

**Files:**
- Modify: `sidecar/csm_sidecar/routes/mining.py`（追加 4 路由）
- Test: `sidecar/csm_sidecar/tests/test_templates_api.py`

- [ ] **Step 1: 写测试 —— 4 个端点 happy path + 错误码**

追加到 `test_templates_api.py`：

```python
def test_create_template(client):
    r = client.post("/api/mining/templates", json={"text": "新建模板", "tags": ["种草"]})
    assert r.status_code == 201
    body = r.json()
    assert body["template"]["text"] == "新建模板"
    assert body["template"]["tags"] == ["种草"]


def test_create_template_duplicate_returns_409(client):
    r1 = client.post("/api/mining/templates", json={"text": "dup"})
    assert r1.status_code == 201
    existing_id = r1.json()["template"]["id"]
    r2 = client.post("/api/mining/templates", json={"text": "dup"})
    assert r2.status_code == 409
    assert r2.json() == {"detail": "duplicate", "existing_id": existing_id}


def test_create_template_too_long_returns_400(client):
    r = client.post("/api/mining/templates", json={"text": "x" * 2001})
    assert r.status_code == 400
    assert r.json()["detail"] == "text_too_long"


def test_create_template_too_many_tags(client):
    r = client.post("/api/mining/templates", json={"text": "ok", "tags": ["t"] * 11})
    assert r.status_code == 400
    assert r.json()["detail"] == "too_many_tags"


def test_patch_template(client):
    tid = mining_storage.create_template(text="原")
    r = client.patch(f"/api/mining/templates/{tid}", json={"starred": True, "text": "新"})
    assert r.status_code == 200
    assert r.json()["template"]["starred"] is True
    assert r.json()["template"]["text"] == "新"


def test_delete_template(client):
    tid = mining_storage.create_template(text="删")
    r = client.delete(f"/api/mining/templates/{tid}")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    r2 = client.delete(f"/api/mining/templates/{tid}")
    assert r2.status_code == 404


def test_use_bumps_count_and_returns_text(client):
    tid = mining_storage.create_template(text="复用我")
    r = client.post(f"/api/mining/templates/{tid}/use")
    assert r.status_code == 200
    assert r.json() == {"text": "复用我"}
    # Confirm DB
    from csm_core.monitor.storage import get_conn
    row = get_conn().execute("SELECT use_count FROM comment_templates WHERE id=?", (tid,)).fetchone()
    assert row[0] == 1
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM && python -m pytest sidecar/csm_sidecar/tests/test_templates_api.py -v
```
Expected: 7 FAIL（前 3 个 T5 仍 PASS）

- [ ] **Step 3: 在 `routes/mining.py` 追加 pydantic schema + 4 路由**

```python
from fastapi.responses import JSONResponse  # add to imports at top of file if not already there


class CreateTemplateBody(BaseModel):
    text: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_platform: str | None = None


class UpdateTemplateBody(BaseModel):
    text: str | None = None
    tags: list[str] | None = None
    starred: bool | None = None
    hidden: bool | None = None


_MAX_TEXT_LEN = 2000
_MAX_TAGS = 10
_MAX_TAG_LEN = 12


def _validate_template_input(text: str | None, tags: list[str] | None) -> None:
    if text is not None and len(text) > _MAX_TEXT_LEN:
        raise HTTPException(status_code=400, detail="text_too_long")
    if tags is not None:
        if len(tags) > _MAX_TAGS:
            raise HTTPException(status_code=400, detail="too_many_tags")
        for t in tags:
            if len(t) > _MAX_TAG_LEN:
                raise HTTPException(status_code=400, detail="tag_too_long")


def _fetch_template_dict(template_id: int) -> dict[str, Any] | None:
    """Fetch a single template row + convert to API dict."""
    from csm_core.monitor.storage import get_conn
    r = get_conn().execute(
        "SELECT * FROM comment_templates WHERE id=?", (template_id,),
    ).fetchone()
    return mining_storage._row_to_template_dict(r) if r else None


@router.post("/api/mining/templates", status_code=201)
async def create_template(body: CreateTemplateBody):
    _validate_template_input(body.text, body.tags)
    try:
        tid = mining_storage.create_template(
            text=body.text, tags=body.tags, source_platform=body.source_platform,
        )
    except mining_storage.TemplateDuplicateError as e:
        # Use JSONResponse (not HTTPException) so the 409 body is flat —
        # tests expect {"detail": "duplicate", "existing_id": N}, not
        # {"detail": {"detail": "duplicate", "existing_id": N}}.
        return JSONResponse(
            status_code=409,
            content={"detail": "duplicate", "existing_id": e.existing_id},
        )
    return {"template": _fetch_template_dict(tid)}


@router.patch("/api/mining/templates/{template_id}")
async def patch_template(template_id: int, body: UpdateTemplateBody):
    _validate_template_input(body.text, body.tags)
    try:
        tpl = mining_storage.update_template(
            template_id,
            text=body.text, tags=body.tags,
            starred=body.starred, hidden=body.hidden,
        )
    except mining_storage.TemplateDuplicateError as e:
        return JSONResponse(
            status_code=409,
            content={"detail": "duplicate", "existing_id": e.existing_id},
        )
    if tpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    return {"template": tpl}


@router.delete("/api/mining/templates/{template_id}")
async def delete_template(template_id: int) -> dict[str, Any]:
    ok = mining_storage.delete_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="template not found")
    return {"ok": True}


@router.post("/api/mining/templates/{template_id}/use")
async def use_template(template_id: int) -> dict[str, Any]:
    text = mining_storage.bump_template_use(template_id)
    if text is None:
        raise HTTPException(status_code=404, detail="template not found")
    return {"text": text}
```

**Note on 409 response shape**: FastAPI 的 `HTTPException(detail=dict)` 会把整个 dict 塞到 `{"detail": ...}` 里，造成双层嵌套。测试期望 flat 结构 `{"detail": "duplicate", "existing_id": N}`，所以这两处用 `JSONResponse` 直接返回。

- [ ] **Step 4: 跑测试验证全过**

```bash
cd D:/CSM && python -m pytest sidecar/csm_sidecar/tests/test_templates_api.py -v
```
Expected: 10 PASS（T5 3 + T6 7）

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/mining.py sidecar/csm_sidecar/tests/test_templates_api.py
git commit -m "feat(mining/templates): T6 API POST/PATCH/DELETE + /use endpoint"
```

---

## T7 — REST API: POST /templates/bulk-import

**Files:**
- Modify: `sidecar/csm_sidecar/routes/mining.py`
- Test: `sidecar/csm_sidecar/tests/test_templates_api.py`

- [ ] **Step 1: 写测试**

```python
def test_bulk_import(client):
    r = client.post(
        "/api/mining/templates/bulk-import",
        json={"texts": ["A", "B", "C"], "tags": ["导入"], "source_platform": "manual"},
    )
    assert r.status_code == 200
    assert r.json() == {"created": 3, "skipped_duplicates": 0}

    # 再来一次 — 全部重复
    r2 = client.post(
        "/api/mining/templates/bulk-import",
        json={"texts": ["A", "B"]},
    )
    assert r2.json() == {"created": 0, "skipped_duplicates": 2}


def test_bulk_import_too_many_returns_400(client):
    r = client.post(
        "/api/mining/templates/bulk-import",
        json={"texts": [f"item-{i}" for i in range(501)]},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "max_batch_exceeded"
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM && python -m pytest sidecar/csm_sidecar/tests/test_templates_api.py::test_bulk_import sidecar/csm_sidecar/tests/test_templates_api.py::test_bulk_import_too_many_returns_400 -v
```
Expected: 2 FAIL

- [ ] **Step 3: 加 schema + 路由**

```python
class BulkImportBody(BaseModel):
    texts: list[str] = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_platform: str | None = None


_MAX_BULK = 500


@router.post("/api/mining/templates/bulk-import")
async def bulk_import_templates(body: BulkImportBody) -> dict[str, int]:
    if len(body.texts) > _MAX_BULK:
        raise HTTPException(status_code=400, detail="max_batch_exceeded")
    _validate_template_input(text=None, tags=body.tags)
    # text-level length check on each item
    for t in body.texts:
        if len(t) > _MAX_TEXT_LEN:
            raise HTTPException(status_code=400, detail="text_too_long")
    return mining_storage.bulk_import_templates(
        texts=body.texts, tags=body.tags, source_platform=body.source_platform,
    )
```

- [ ] **Step 4: 跑全套 templates_api 测试**

```bash
cd D:/CSM && python -m pytest sidecar/csm_sidecar/tests/test_templates_api.py -v
```
Expected: 12 PASS

- [ ] **Step 5: 跑全后端测试套件确保无回归**

```bash
cd D:/CSM && python -m pytest csm_core sidecar -v
```
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add sidecar/csm_sidecar/routes/mining.py sidecar/csm_sidecar/tests/test_templates_api.py
git commit -m "feat(mining/templates): T7 API POST /templates/bulk-import"
```

---

## T8 — Icon.vue 新增 3 个 SVG path

**Files:**
- Modify: `frontend/src/components/ui/Icon.vue`（`PATHS` 字典追加 3 项）

- [ ] **Step 1: 修改 `Icon.vue`**

在 [Icon.vue:99](frontend/src/components/ui/Icon.vue:99) `image:` 行之后、`};` 之前追加：

```typescript
  // ── Comment template library (v5) additions ──────────────────────
  bookmark:
    '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  tag:
    '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>',
  upload:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
```

- [ ] **Step 2: 跑 vue-tsc 检查类型**

```bash
cd D:/CSM/frontend && pnpm vue-tsc -b
```
Expected: 零错零警告

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/Icon.vue
git commit -m "feat(ui/icon): T8 add bookmark / tag / upload SVG paths for templates"
```

---

## T9 — Pinia store: templates.ts

**Files:**
- Create: `frontend/src/stores/templates.ts`
- Create: `frontend/src/stores/__tests__/templates.test.ts`

- [ ] **Step 1: 写测试**

```typescript
// frontend/src/stores/__tests__/templates.test.ts
import { setActivePinia, createPinia } from "pinia"
import { beforeEach, describe, it, expect, vi } from "vitest"
import { useTemplatesStore } from "@/stores/templates"

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  }),
}))

import { useSidecar } from "@/stores/sidecar"

describe("templates store", () => {
  beforeEach(() => setActivePinia(createPinia()))

  it("list() loads items and total into store", async () => {
    const client = useSidecar().client as any
    client.get.mockResolvedValue({
      data: { items: [{ id: 1, text: "A", tags: [], starred: false, hidden: false, use_count: 0 }], total: 1 },
    })
    const s = useTemplatesStore()
    await s.list({ search: "A" })
    expect(s.items.length).toBe(1)
    expect(s.total).toBe(1)
    expect(client.get).toHaveBeenCalledWith(
      "/api/mining/templates",
      { params: { search: "A", limit: 50, offset: 0 } },
    )
  })

  it("useTemplate() calls /use and returns text", async () => {
    const client = useSidecar().client as any
    client.post.mockResolvedValue({ data: { text: "复用文本" } })
    const s = useTemplatesStore()
    const text = await s.useTemplate(7)
    expect(text).toBe("复用文本")
    expect(client.post).toHaveBeenCalledWith("/api/mining/templates/7/use")
  })

  it("create() throws 'duplicate' for 409 response", async () => {
    const client = useSidecar().client as any
    client.post.mockRejectedValue({ response: { status: 409, data: { detail: "duplicate", existing_id: 42 } } })
    const s = useTemplatesStore()
    await expect(s.create({ text: "dup" })).rejects.toMatchObject({ kind: "duplicate", existingId: 42 })
  })
})
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd D:/CSM/frontend && pnpm vitest run src/stores/__tests__/templates.test.ts
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `frontend/src/stores/templates.ts`**

```typescript
/**
 * Templates store — Pinia for comment template library.
 *
 * Pulls top-N chips for CommentComposer, full list for drawer + settings.
 * /use endpoint bumps use_count + last_used_at server-side so chips
 * re-rank correctly on next list().
 */
import { defineStore } from "pinia"
import { ref } from "vue"
import { useSidecar } from "@/stores/sidecar"

export interface Template {
  id: number
  text: string
  tags: string[]
  source_platform: string | null
  source_comment_id: number | null
  starred: boolean
  hidden: boolean
  use_count: number
  first_seen_at: string
  last_used_at: string
}

export interface ListTemplateParams {
  search?: string
  tags?: string[]
  platform?: string
  starred?: boolean
  hidden?: "0" | "1" | "all"
  limit?: number
  offset?: number
}

export interface CreateTemplatePayload {
  text: string
  tags?: string[]
  source_platform?: string | null
}

export interface UpdateTemplatePayload {
  text?: string
  tags?: string[]
  starred?: boolean
  hidden?: boolean
}

export class TemplateDuplicateError extends Error {
  kind = "duplicate" as const
  constructor(public existingId: number) {
    super(`template already exists (id=${existingId})`)
    this.name = "TemplateDuplicateError"
  }
}

function api() {
  return useSidecar().client
}

export const useTemplatesStore = defineStore("templates", () => {
  const items = ref<Template[]>([])
  const total = ref(0)
  const allTags = ref<string[]>([])
  const loading = ref(false)

  async function list(params: ListTemplateParams = {}): Promise<void> {
    loading.value = true
    try {
      const resp = await api().get<{ items: Template[]; total: number }>(
        "/api/mining/templates",
        {
          params: {
            search: params.search,
            tags: params.tags?.length ? params.tags.join(",") : undefined,
            platform: params.platform,
            starred: params.starred,
            hidden: params.hidden ?? "0",
            limit: params.limit ?? 50,
            offset: params.offset ?? 0,
          },
        },
      )
      items.value = resp.data.items
      total.value = resp.data.total
    } finally {
      loading.value = false
    }
  }

  async function listTopChips(limit = 5): Promise<Template[]> {
    const resp = await api().get<{ items: Template[]; total: number }>(
      "/api/mining/templates",
      { params: { limit, offset: 0, hidden: "0" } },
    )
    return resp.data.items
  }

  async function loadAllTags(): Promise<void> {
    const resp = await api().get<{ tags: string[] }>("/api/mining/templates/tags")
    allTags.value = resp.data.tags
  }

  async function useTemplate(id: number): Promise<string> {
    const resp = await api().post<{ text: string }>(`/api/mining/templates/${id}/use`)
    return resp.data.text
  }

  async function create(payload: CreateTemplatePayload): Promise<Template> {
    try {
      const resp = await api().post<{ template: Template }>("/api/mining/templates", payload)
      return resp.data.template
    } catch (err: any) {
      if (err?.response?.status === 409 && err.response.data?.detail === "duplicate") {
        throw new TemplateDuplicateError(err.response.data.existing_id)
      }
      throw err
    }
  }

  async function update(id: number, payload: UpdateTemplatePayload): Promise<Template> {
    try {
      const resp = await api().patch<{ template: Template }>(`/api/mining/templates/${id}`, payload)
      // Update local cache if id is in items
      const idx = items.value.findIndex(t => t.id === id)
      if (idx >= 0) items.value[idx] = resp.data.template
      return resp.data.template
    } catch (err: any) {
      if (err?.response?.status === 409 && err.response.data?.detail === "duplicate") {
        throw new TemplateDuplicateError(err.response.data.existing_id)
      }
      throw err
    }
  }

  async function remove(id: number): Promise<void> {
    await api().delete(`/api/mining/templates/${id}`)
    items.value = items.value.filter(t => t.id !== id)
  }

  async function bulkImport(payload: {
    texts: string[]
    tags?: string[]
    source_platform?: string | null
  }): Promise<{ created: number; skipped_duplicates: number }> {
    const resp = await api().post<{ created: number; skipped_duplicates: number }>(
      "/api/mining/templates/bulk-import",
      payload,
    )
    return resp.data
  }

  async function exportAll(): Promise<Template[]> {
    // Fetch all templates including hidden, page through 500-at-a-time.
    const all: Template[] = []
    let offset = 0
    const limit = 500
    while (true) {
      const resp = await api().get<{ items: Template[]; total: number }>(
        "/api/mining/templates",
        { params: { hidden: "all", limit, offset } },
      )
      all.push(...resp.data.items)
      if (all.length >= resp.data.total) break
      offset += limit
    }
    return all
  }

  return {
    items, total, allTags, loading,
    list, listTopChips, loadAllTags,
    useTemplate, create, update, remove,
    bulkImport, exportAll,
  }
})
```

- [ ] **Step 4: 跑测试验证全过**

```bash
cd D:/CSM/frontend && pnpm vitest run src/stores/__tests__/templates.test.ts
```
Expected: 3 PASS

- [ ] **Step 5: vue-tsc 类型检查**

```bash
cd D:/CSM/frontend && pnpm vue-tsc -b
```
Expected: 零错零警告

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/templates.ts frontend/src/stores/__tests__/templates.test.ts
git commit -m "feat(mining/templates): T9 Pinia store with list/use/CRUD/bulkImport/export"
```

---

## T10 — TemplateChipsRow.vue + 挂到 Composer + 替换/追加确认

**Files:**
- Create: `frontend/src/components/mining/TemplateChipsRow.vue`
- Modify: `frontend/src/components/mining/CommentComposer.vue`（在 textarea 上方挂 chips 行 + 替换/追加确认）

- [ ] **Step 1: 创建 `TemplateChipsRow.vue`**

```vue
<script setup lang="ts">
/**
 * Top-N starred/recent template chips above the comment textarea.
 *
 * Loads top 5 via templatesStore.listTopChips() on mount.
 * Emits "pick" with the template id; parent decides replace/append.
 */
import { onMounted, ref } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useTemplatesStore, type Template } from "@/stores/templates"

const props = defineProps<{
  /** Max chip count (excluding "更多" button). Default 5. */
  limit?: number
}>()
const emit = defineEmits<{
  (e: "pick", template: Template): void
  (e: "openDrawer"): void
}>()

const store = useTemplatesStore()
const chips = ref<Template[]>([])
const loaded = ref(false)
const total = ref(0)

onMounted(async () => {
  const items = await store.listTopChips(props.limit ?? 5)
  chips.value = items
  // We need total for "更多 (N)" badge — call list with limit 1 to grab total cheaply
  await store.list({ limit: 1, offset: 0 })
  total.value = store.total
  loaded.value = true
})

function truncate(text: string, n = 12): string {
  return text.length > n ? text.slice(0, n) + "…" : text
}
</script>

<template>
  <div v-if="loaded && (chips.length > 0 || total > 0)" class="chips-row">
    <button
      v-for="tpl in chips"
      :key="tpl.id"
      class="chip"
      :class="{ starred: tpl.starred }"
      :title="tpl.text"
      @click="emit('pick', tpl)"
    >
      <Icon v-if="tpl.starred" name="skills" :size="11" />
      <span>{{ truncate(tpl.text) }}</span>
    </button>
    <button class="chip more" @click="emit('openDrawer')">
      <Icon name="stack" :size="12" />
      <span>更多 ({{ total }})</span>
    </button>
  </div>
  <div v-else-if="loaded && total === 0" class="chips-empty">
    <Icon name="info" :size="12" />
    还没有模板。在设置里"评论模板库"添加，或者发一条评论它会自动入库。
  </div>
</template>

<style scoped>
.chips-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--card-2, #fff5dc);
  border: 1px solid var(--line, #e8d6a8);
  border-radius: 12px;
  padding: 3px 9px;
  font-size: 11px;
  color: var(--ink, #6a5520);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.chip:hover { background: var(--card-3, #ffe8a3); }
.chip.starred { border-color: var(--accent, #e0a020); }
.chip.more {
  background: transparent;
  border-style: dashed;
  color: var(--ink-3, #8a7848);
}
.chips-empty {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-4, #9c8a6a);
  margin-bottom: 8px;
  padding: 4px 8px;
}
</style>
```

- [ ] **Step 2: 在 `CommentComposer.vue` 挂载 chips 行 + 处理 pick**

读 [CommentComposer.vue:41-44](frontend/src/components/mining/CommentComposer.vue:41) 看现有 import 风格，在 `<script setup>` 顶部追加：

```typescript
import TemplateChipsRow from "@/components/mining/TemplateChipsRow.vue"
import TemplateDrawer from "@/components/mining/TemplateDrawer.vue"  // 将在 T11 创建
import { useTemplatesStore, type Template } from "@/stores/templates"

const templatesStore = useTemplatesStore()
const drawerOpen = ref(false)
const pendingPick = ref<Template | null>(null)
const showPickConfirm = ref(false)

async function handlePick(tpl: Template) {
  if (text.value.trim().length === 0) {
    // Empty — direct fill
    text.value = await templatesStore.useTemplate(tpl.id)
    await nextTick()
    textareaRef.value?.focus()
  } else {
    // Non-empty — confirm replace/append
    pendingPick.value = tpl
    showPickConfirm.value = true
  }
}

async function confirmPick(action: "replace" | "append") {
  if (!pendingPick.value) return
  const filledText = await templatesStore.useTemplate(pendingPick.value.id)
  if (action === "replace") {
    text.value = filledText
  } else {
    text.value = text.value.trim() + "\n" + filledText
  }
  showPickConfirm.value = false
  pendingPick.value = null
  await nextTick()
  textareaRef.value?.focus()
}

function cancelPick() {
  showPickConfirm.value = false
  pendingPick.value = null
}
```

注意：`textareaRef` 应该是已有的 ref（找 Composer 里现有的 textarea ref 名，可能叫 `textareaRef` / `bodyRef`）。先 grep。

```bash
grep -nE "useTemplateRef|textareaRef|bodyRef" frontend/src/components/mining/CommentComposer.vue
```

按实际名字替换。

在 `<template>` 顶部（textarea 之前）插入：

```vue
<TemplateChipsRow
  @pick="handlePick"
  @open-drawer="drawerOpen = true"
/>
```

在 `<template>` 末尾（外层 div 内）追加 confirm popover + drawer：

```vue
<div v-if="showPickConfirm" class="pick-confirm-overlay" @click.self="cancelPick">
  <div class="pick-confirm-card">
    <div class="confirm-title">输入框已有内容</div>
    <div class="confirm-preview">{{ pendingPick?.text }}</div>
    <div class="confirm-actions">
      <button @click="confirmPick('replace')">替换</button>
      <button @click="confirmPick('append')">追加</button>
      <button @click="cancelPick">取消</button>
    </div>
  </div>
</div>

<TemplateDrawer
  v-if="drawerOpen"
  @close="drawerOpen = false"
  @pick="async (tpl: Template) => { drawerOpen = false; await handlePick(tpl) }"
/>
```

CSS（在已有 `<style scoped>` 块末尾追加）：

```css
.pick-confirm-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.pick-confirm-card {
  background: var(--card, #fff);
  border-radius: 10px;
  padding: 18px 20px;
  min-width: 320px;
  max-width: 480px;
  box-shadow: 0 12px 32px rgba(0,0,0,0.18);
}
.confirm-title { font-weight: 600; margin-bottom: 8px; }
.confirm-preview {
  background: var(--card-2, #fff5dc);
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--ink, #2a2017);
  margin-bottom: 14px;
  max-height: 120px;
  overflow-y: auto;
}
.confirm-actions { display: flex; gap: 8px; justify-content: flex-end; }
.confirm-actions button {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--line, #d4c8a8);
  background: var(--card, #fff);
  cursor: pointer;
  font-size: 12px;
}
.confirm-actions button:first-child {
  background: var(--ink, #2a2017);
  color: #fff;
  border-color: var(--ink, #2a2017);
}
```

- [ ] **Step 3: 跑 vue-tsc 检查类型**

```bash
cd D:/CSM/frontend && pnpm vue-tsc -b
```
Expected: 零错（注意 `TemplateDrawer` import 会报 missing module，因为 T11 还没创建 — **暂用 stub**：先创建空文件 `TemplateDrawer.vue` 占位：

```vue
<script setup lang="ts">
defineEmits<{(e: "close"): void; (e: "pick", tpl: any): void}>()
</script>
<template><div /></template>
```

T11 会替换它。

跑 vue-tsc 再次确认零错。

- [ ] **Step 4: 手测**

```bash
cd D:/CSM/frontend && pnpm dev
```
打开 mining 页面 → 进入一个视频卡片 → 输入框上方应出现 chips 行（如库为空显示空状态文案）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/mining/TemplateChipsRow.vue frontend/src/components/mining/CommentComposer.vue frontend/src/components/mining/TemplateDrawer.vue
git commit -m "feat(mining/templates): T10 TemplateChipsRow + Composer integration + replace/append confirm"
```

---

## T11 — TemplateDrawer.vue + Ctrl+/ 快捷键

**Files:**
- Modify: `frontend/src/components/mining/TemplateDrawer.vue`（替换 T10 创建的 stub）
- Modify: `frontend/src/components/mining/CommentComposer.vue`（追加 `Ctrl + /` keydown）

- [ ] **Step 1: 实现完整的 `TemplateDrawer.vue`**

```vue
<script setup lang="ts">
/**
 * Right-side slide-out drawer for browsing the full template library.
 *
 * Features:
 *   - Search by text (debounced)
 *   - Multi-select tag filter (intersection)
 *   - List with inline actions: pick / star / hide / edit
 *   - Keyboard: ↑↓ select, Enter pick, Esc close
 *   - No hard delete + no bulk import (those live in settings)
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useTemplatesStore, type Template } from "@/stores/templates"

const emit = defineEmits<{
  (e: "close"): void
  (e: "pick", tpl: Template): void
}>()

const store = useTemplatesStore()
const search = ref("")
const selectedTags = ref<string[]>([])
const editingId = ref<number | null>(null)
const editText = ref("")
const activeIndex = ref(0)

let searchTimer: number | undefined

watch([search, selectedTags], () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refresh, 200)
})

async function refresh() {
  await store.list({
    search: search.value || undefined,
    tags: selectedTags.value.length ? selectedTags.value : undefined,
  })
  activeIndex.value = 0
}

function toggleTag(tag: string) {
  const i = selectedTags.value.indexOf(tag)
  if (i >= 0) selectedTags.value.splice(i, 1)
  else selectedTags.value.push(tag)
}

function pick(tpl: Template) {
  emit("pick", tpl)
}

async function toggleStar(tpl: Template) {
  await store.update(tpl.id, { starred: !tpl.starred })
}

async function hide(tpl: Template) {
  await store.update(tpl.id, { hidden: true })
  store.items = store.items.filter(t => t.id !== tpl.id)
}

function startEdit(tpl: Template) {
  editingId.value = tpl.id
  editText.value = tpl.text
}

async function saveEdit(tpl: Template) {
  if (editText.value.trim() && editText.value !== tpl.text) {
    await store.update(tpl.id, { text: editText.value })
  }
  editingId.value = null
}

function cancelEdit() { editingId.value = null }

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") { emit("close"); return }
  if (e.key === "ArrowDown") {
    activeIndex.value = Math.min(activeIndex.value + 1, store.items.length - 1)
    e.preventDefault()
  } else if (e.key === "ArrowUp") {
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
    e.preventDefault()
  } else if (e.key === "Enter" && !editingId.value) {
    const tpl = store.items[activeIndex.value]
    if (tpl) pick(tpl)
    e.preventDefault()
  }
}

onMounted(async () => {
  document.addEventListener("keydown", onKeydown)
  await store.loadAllTags()
  await refresh()
})
onUnmounted(() => {
  document.removeEventListener("keydown", onKeydown)
})
</script>

<template>
  <div class="drawer-overlay" @click.self="emit('close')">
    <aside class="drawer" role="dialog" aria-label="模板库">
      <header class="drawer-header">
        <div class="drawer-title">
          <Icon name="stack" :size="16" />
          <span>模板库</span>
        </div>
        <button class="drawer-close" @click="emit('close')">
          <Icon name="x" :size="14" />
        </button>
      </header>

      <div class="drawer-search">
        <Icon name="search" :size="13" class="search-icon" />
        <input v-model="search" placeholder="搜索文本或标签…" />
      </div>

      <div v-if="store.allTags.length" class="drawer-tags">
        <Icon name="tag" :size="11" />
        <button
          v-for="t in store.allTags"
          :key="t"
          class="tag-chip"
          :class="{ active: selectedTags.includes(t) }"
          @click="toggleTag(t)"
        >{{ t }}</button>
      </div>

      <div v-if="store.loading" class="drawer-loading">加载中…</div>
      <div v-else-if="store.items.length === 0" class="drawer-empty">
        没找到匹配的模板
      </div>
      <ul v-else class="drawer-list">
        <li
          v-for="(tpl, i) in store.items"
          :key="tpl.id"
          class="drawer-item"
          :class="{ active: i === activeIndex }"
        >
          <div v-if="editingId === tpl.id" class="edit-mode">
            <textarea v-model="editText" rows="3" />
            <div class="edit-actions">
              <button @click="saveEdit(tpl)">保存</button>
              <button @click="cancelEdit">取消</button>
            </div>
          </div>
          <template v-else>
            <div class="item-text">{{ tpl.text }}</div>
            <div class="item-meta">
              <span v-for="t in tpl.tags" :key="t" class="meta-tag">#{{ t }}</span>
              <span v-if="tpl.source_platform">· {{ tpl.source_platform }}</span>
              <span>· 用过 {{ tpl.use_count }} 次</span>
            </div>
            <div class="item-actions">
              <button class="primary" @click="pick(tpl)">填入</button>
              <button @click="toggleStar(tpl)" :title="tpl.starred ? '取消精选' : '标精选'">
                <Icon name="skills" :size="12" />
              </button>
              <button @click="startEdit(tpl)" title="编辑">
                <Icon name="edit" :size="12" />
              </button>
              <button @click="hide(tpl)" title="隐藏">
                <Icon name="eye" :size="12" />
              </button>
            </div>
          </template>
        </li>
      </ul>
    </aside>
  </div>
</template>

<style scoped>
.drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.15);
  z-index: 90;
}
.drawer {
  position: fixed; right: 0; top: 0; bottom: 0;
  width: 420px;
  background: var(--card, #fffaef);
  border-left: 1px solid var(--line, #d4c8a8);
  display: flex;
  flex-direction: column;
  box-shadow: -8px 0 20px rgba(0,0,0,0.08);
  animation: slide-in 180ms ease-out;
}
@keyframes slide-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; border-bottom: 1px solid var(--line, #e8dcc0);
}
.drawer-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.drawer-close { background: transparent; border: none; cursor: pointer; padding: 4px; }
.drawer-search {
  position: relative; padding: 10px 16px;
}
.drawer-search input {
  width: 100%; padding: 6px 10px 6px 28px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  background: var(--card-input, #fff); font-size: 12px;
}
.search-icon { position: absolute; left: 24px; top: 50%; transform: translateY(-50%); color: var(--ink-4, #9c8a6a); }
.drawer-tags {
  display: flex; gap: 4px; flex-wrap: wrap; align-items: center;
  padding: 0 16px 8px;
}
.tag-chip {
  background: var(--card-2, #fff5dc); border: 1px solid var(--line, #e8d6a8);
  border-radius: 10px; padding: 2px 8px; font-size: 10px; cursor: pointer;
  color: var(--ink, #6a5520);
}
.tag-chip.active { background: var(--accent, #e0a020); color: #fff; border-color: var(--accent, #e0a020); }
.drawer-list { flex: 1; overflow-y: auto; margin: 0; padding: 0; list-style: none; }
.drawer-item {
  padding: 10px 16px; border-bottom: 1px solid var(--line-light, #ece0c2);
}
.drawer-item.active { background: var(--card-hover, #fff5dc); }
.item-text {
  font-size: 12px; color: var(--ink, #2a2017);
  line-height: 1.4;
  max-height: 60px; overflow: hidden;
}
.item-meta { font-size: 10px; color: var(--ink-4, #9c8a6a); margin-top: 4px; }
.meta-tag {
  background: var(--card-2, #fff5dc); padding: 1px 5px; border-radius: 6px;
  color: var(--ink, #6a5520); margin-right: 3px;
}
.item-actions { display: flex; gap: 4px; margin-top: 6px; }
.item-actions button {
  padding: 3px 8px; font-size: 10px; border-radius: 4px;
  border: 1px solid var(--line, #ece0c2); background: var(--card-2, #faf3df);
  color: var(--ink, #6b5a3a); cursor: pointer;
}
.item-actions button.primary {
  background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017);
}
.drawer-loading, .drawer-empty {
  padding: 30px; text-align: center; color: var(--ink-4, #9c8a6a); font-size: 12px;
}
.edit-mode textarea {
  width: 100%; min-height: 60px; padding: 6px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 4px;
  font-family: inherit; font-size: 12px;
}
.edit-actions { display: flex; gap: 6px; margin-top: 6px; }
.edit-actions button {
  padding: 3px 10px; font-size: 11px; border-radius: 4px;
  border: 1px solid var(--line, #d4c8a8); background: var(--card, #fff);
  cursor: pointer;
}
.edit-actions button:first-child {
  background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017);
}
</style>
```

- [ ] **Step 2: 在 `CommentComposer.vue` 挂 `Ctrl + /` 快捷键**

找到 textarea 的 `<textarea>` 标签，给它加 `@keydown` 处理：

```vue
<textarea
  ref="textareaRef"
  v-model="text"
  ...
  @keydown="onTextareaKeydown"
/>
```

`<script setup>` 里加 handler：

```typescript
function onTextareaKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === "/") {
    drawerOpen.value = true
    e.preventDefault()
  }
}
```

- [ ] **Step 3: vue-tsc 检查 + 手测**

```bash
cd D:/CSM/frontend && pnpm vue-tsc -b
```
Expected: 零错

手测：
- 启动 dev：`pnpm dev`
- 进入 Composer，点 chips 行 "更多 →" 按钮，抽屉应从右滑出
- 在 textarea 按 `Ctrl + /`，抽屉应打开
- 抽屉里按 ↑↓ 选条目、Enter 填入、Esc 关闭

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/mining/TemplateDrawer.vue frontend/src/components/mining/CommentComposer.vue
git commit -m "feat(mining/templates): T11 TemplateDrawer with search/tags/inline-mgmt + Ctrl+/ shortcut"
```

---

## T12 — TemplateEditModal.vue（新建 / 编辑 模态）

**Files:**
- Create: `frontend/src/components/settings/TemplateEditModal.vue`

- [ ] **Step 1: 创建组件**

```vue
<script setup lang="ts">
/**
 * Modal for create/edit one template.
 * Used by TemplateLibrarySection in settings.
 *
 * Props:
 *   - mode: "create" | "edit"
 *   - template: Template | null   (required when mode === "edit")
 * Emits:
 *   - close()
 *   - saved(tpl: Template)
 *   - duplicate(existingId: number)
 */
import { onMounted, ref } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useTemplatesStore, TemplateDuplicateError, type Template } from "@/stores/templates"

const props = defineProps<{
  mode: "create" | "edit"
  template: Template | null
}>()
const emit = defineEmits<{
  (e: "close"): void
  (e: "saved", tpl: Template): void
  (e: "duplicate", existingId: number): void
}>()

const store = useTemplatesStore()
const text = ref("")
const tags = ref<string[]>([])
const tagInput = ref("")
const saving = ref(false)
const error = ref("")
const allTags = ref<string[]>([])

onMounted(async () => {
  if (props.mode === "edit" && props.template) {
    text.value = props.template.text
    tags.value = [...props.template.tags]
  }
  await store.loadAllTags()
  allTags.value = store.allTags
})

function addTag(tag: string) {
  const t = tag.trim()
  if (!t || tags.value.includes(t)) return
  if (tags.value.length >= 10) {
    error.value = "最多 10 个标签"
    return
  }
  if (t.length > 12) {
    error.value = "单标签最多 12 字"
    return
  }
  tags.value.push(t)
  tagInput.value = ""
  error.value = ""
}
function removeTag(t: string) {
  tags.value = tags.value.filter(x => x !== t)
}

async function save() {
  error.value = ""
  if (text.value.trim().length === 0) {
    error.value = "文本不能为空"
    return
  }
  if (text.value.length > 2000) {
    error.value = "文本最多 2000 字"
    return
  }
  saving.value = true
  try {
    if (props.mode === "create") {
      const tpl = await store.create({ text: text.value, tags: tags.value })
      emit("saved", tpl)
    } else if (props.template) {
      const tpl = await store.update(props.template.id, {
        text: text.value, tags: tags.value,
      })
      emit("saved", tpl)
    }
  } catch (err) {
    if (err instanceof TemplateDuplicateError) {
      emit("duplicate", err.existingId)
    } else {
      error.value = (err as Error).message || "保存失败"
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-header">
        <h3>{{ mode === "create" ? "新建模板" : "编辑模板" }}</h3>
        <button @click="emit('close')"><Icon name="x" :size="14" /></button>
      </header>

      <div class="modal-body">
        <label>
          <span>文本</span>
          <textarea v-model="text" rows="6" placeholder="评论文本…" />
          <span class="char-count">{{ text.length }} / 2000</span>
        </label>

        <label>
          <span>标签</span>
          <div class="tag-list">
            <span v-for="t in tags" :key="t" class="tag-pill">
              {{ t }}
              <button @click="removeTag(t)">×</button>
            </span>
            <input
              v-model="tagInput"
              placeholder="输入或选择…"
              @keydown.enter.prevent="addTag(tagInput)"
              @keydown.comma.prevent="addTag(tagInput)"
              :disabled="tags.length >= 10"
            />
          </div>
          <div v-if="allTags.length" class="tag-suggestions">
            <span class="muted">已有：</span>
            <button
              v-for="t in allTags.filter(t => !tags.includes(t))"
              :key="t"
              class="suggest-chip"
              @click="addTag(t)"
            >{{ t }}</button>
          </div>
        </label>

        <div v-if="error" class="error">{{ error }}</div>
      </div>

      <footer class="modal-footer">
        <button @click="emit('close')">取消</button>
        <button class="primary" :disabled="saving" @click="save">
          {{ saving ? "保存中…" : "保存" }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-card {
  background: var(--card, #fff);
  border-radius: 10px;
  width: 480px; max-width: 95vw;
  box-shadow: 0 12px 32px rgba(0,0,0,0.2);
  display: flex; flex-direction: column;
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--line, #e8dcc0);
}
.modal-header h3 { margin: 0; font-size: 14px; }
.modal-header button { background: transparent; border: none; cursor: pointer; padding: 4px; }
.modal-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.modal-body label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.modal-body label > span:first-child { font-weight: 600; color: var(--ink, #4a3f2a); }
.modal-body textarea {
  width: 100%; padding: 8px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  font-family: inherit; font-size: 12px; line-height: 1.5;
  resize: vertical; min-height: 100px;
}
.char-count { font-size: 10px; color: var(--ink-4, #9c8a6a); align-self: flex-end; }
.tag-list {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px; padding: 6px;
  background: var(--card-input, #fff);
}
.tag-pill {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--card-2, #fff5dc); padding: 2px 8px;
  border-radius: 10px; font-size: 11px; color: var(--ink, #6a5520);
}
.tag-pill button { background: transparent; border: none; cursor: pointer; color: var(--ink-4, #9c8a6a); }
.tag-list input { flex: 1; min-width: 100px; border: none; outline: none; font-size: 12px; background: transparent; }
.tag-suggestions { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-top: 4px; }
.suggest-chip {
  background: transparent; border: 1px dashed var(--line, #d4c8a8);
  padding: 1px 7px; border-radius: 8px; font-size: 10px;
  color: var(--ink-3, #8a7848); cursor: pointer;
}
.muted { font-size: 10px; color: var(--ink-4, #9c8a6a); }
.error { color: #c44; font-size: 12px; }
.modal-footer {
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 12px 18px; border-top: 1px solid var(--line, #e8dcc0);
}
.modal-footer button {
  padding: 6px 14px; border-radius: 6px;
  border: 1px solid var(--line, #d4c8a8); background: var(--card, #fff);
  font-size: 12px; cursor: pointer;
}
.modal-footer button.primary {
  background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017);
}
.modal-footer button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
```

- [ ] **Step 2: vue-tsc 类型检查**

```bash
cd D:/CSM/frontend && pnpm vue-tsc -b
```
Expected: 零错

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/settings/TemplateEditModal.vue
git commit -m "feat(mining/templates): T12 TemplateEditModal for create/edit"
```

---

## T13 — TemplateBulkImportModal.vue

**Files:**
- Create: `frontend/src/components/settings/TemplateBulkImportModal.vue`

- [ ] **Step 1: 创建组件**

```vue
<script setup lang="ts">
/**
 * Bulk import modal: paste many lines, optionally apply common tags + platform,
 * preview "新增 X / 跳过 Y 重复", confirm to import.
 */
import { computed, ref } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useTemplatesStore } from "@/stores/templates"

const emit = defineEmits<{
  (e: "close"): void
  (e: "imported", result: { created: number; skipped_duplicates: number }): void
}>()

const store = useTemplatesStore()
const rawInput = ref("")
const tagInput = ref("")
const tags = ref<string[]>([])
const platform = ref<string>("")
const importing = ref(false)
const error = ref("")

const lines = computed(() =>
  rawInput.value.split("\n").map(l => l.trim()).filter(l => l.length > 0)
)

const previewSkipped = computed(() => {
  const seen = new Set<string>()
  let skipped = 0
  for (const line of lines.value) {
    if (seen.has(line)) skipped++
    else seen.add(line)
  }
  return skipped
})

function addTag(t: string) {
  const tag = t.trim()
  if (!tag || tags.value.includes(tag) || tags.value.length >= 10 || tag.length > 12) return
  tags.value.push(tag)
  tagInput.value = ""
}

function removeTag(t: string) {
  tags.value = tags.value.filter(x => x !== t)
}

async function doImport() {
  if (lines.value.length === 0) {
    error.value = "请输入至少一行"
    return
  }
  if (lines.value.length > 500) {
    error.value = `单次最多 500 条（当前 ${lines.value.length} 条）`
    return
  }
  importing.value = true
  error.value = ""
  try {
    const result = await store.bulkImport({
      texts: lines.value,
      tags: tags.value,
      source_platform: platform.value || null,
    })
    emit("imported", result)
  } catch (err) {
    error.value = (err as Error).message || "导入失败"
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-header">
        <h3>批量导入模板</h3>
        <button @click="emit('close')"><Icon name="x" :size="14" /></button>
      </header>

      <div class="modal-body">
        <label>
          <span>每行一条评论</span>
          <textarea v-model="rawInput" rows="10" placeholder="粘贴文本，每行一条…" />
        </label>

        <label>
          <span>公共标签（应用到所有导入项）</span>
          <div class="tag-list">
            <span v-for="t in tags" :key="t" class="tag-pill">
              {{ t }} <button @click="removeTag(t)">×</button>
            </span>
            <input
              v-model="tagInput"
              placeholder="回车添加…"
              @keydown.enter.prevent="addTag(tagInput)"
            />
          </div>
        </label>

        <label>
          <span>来源平台</span>
          <select v-model="platform">
            <option value="">手动 (默认)</option>
            <option value="douyin">抖音</option>
            <option value="kuaishou">快手</option>
            <option value="bilibili">B 站</option>
          </select>
        </label>

        <div class="preview">
          <Icon name="info" :size="12" />
          <span>
            将尝试导入 <b>{{ lines.length }}</b> 条；
            其中 <b>{{ previewSkipped }}</b> 条在本批内重复，库内已有的会被跳过
          </span>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
      </div>

      <footer class="modal-footer">
        <button @click="emit('close')">取消</button>
        <button class="primary" :disabled="importing || lines.length === 0" @click="doImport">
          {{ importing ? "导入中…" : `导入 ${lines.length} 条` }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
/* Reuse styles inline matching TemplateEditModal — pasted for self-containment */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-card {
  background: var(--card, #fff);
  border-radius: 10px;
  width: 560px; max-width: 95vw;
  box-shadow: 0 12px 32px rgba(0,0,0,0.2);
  display: flex; flex-direction: column;
}
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--line, #e8dcc0); }
.modal-header h3 { margin: 0; font-size: 14px; }
.modal-header button { background: transparent; border: none; cursor: pointer; padding: 4px; }
.modal-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.modal-body label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.modal-body label > span:first-child { font-weight: 600; color: var(--ink, #4a3f2a); }
.modal-body textarea, .modal-body select {
  width: 100%; padding: 8px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  font-family: inherit; font-size: 12px;
  background: var(--card-input, #fff);
}
.tag-list {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px; padding: 6px;
  background: var(--card-input, #fff);
}
.tag-pill {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--card-2, #fff5dc); padding: 2px 8px;
  border-radius: 10px; font-size: 11px; color: var(--ink, #6a5520);
}
.tag-pill button { background: transparent; border: none; cursor: pointer; }
.tag-list input { flex: 1; min-width: 100px; border: none; outline: none; font-size: 12px; background: transparent; }
.preview { background: var(--card-2, #fff5dc); padding: 8px 10px; border-radius: 6px; font-size: 11px; color: var(--ink, #4a3f2a); display: flex; align-items: center; gap: 6px; }
.error { color: #c44; font-size: 12px; }
.modal-footer { display: flex; gap: 8px; justify-content: flex-end; padding: 12px 18px; border-top: 1px solid var(--line, #e8dcc0); }
.modal-footer button { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--line, #d4c8a8); background: var(--card, #fff); font-size: 12px; cursor: pointer; }
.modal-footer button.primary { background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017); }
.modal-footer button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
```

- [ ] **Step 2: vue-tsc 类型检查 + commit**

```bash
cd D:/CSM/frontend && pnpm vue-tsc -b
git add frontend/src/components/settings/TemplateBulkImportModal.vue
git commit -m "feat(mining/templates): T13 TemplateBulkImportModal with preview"
```

---

## T14 — TemplateLibrarySection + 挂 SettingsView + 手测

**Files:**
- Create: `frontend/src/components/settings/TemplateLibrarySection.vue`
- Modify: `frontend/src/views/SettingsView.vue:170`（SECTIONS 数组追加）+ section switch 渲染

- [ ] **Step 1: 创建 `TemplateLibrarySection.vue`**

```vue
<script setup lang="ts">
/**
 * Settings → 评论模板库 section.
 * Full CRUD + bulk import + JSON export + show-hidden toggle.
 */
import { computed, onMounted, ref, watch } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useToast } from "@/composables/useToast"
import { useTemplatesStore, type Template } from "@/stores/templates"

import TemplateEditModal from "./TemplateEditModal.vue"
import TemplateBulkImportModal from "./TemplateBulkImportModal.vue"

const store = useTemplatesStore()
const toast = useToast()

const search = ref("")
const selectedTags = ref<string[]>([])
const platform = ref<string>("")
const showHidden = ref(false)
const page = ref(0)
const pageSize = 50

const showEdit = ref(false)
const editMode = ref<"create" | "edit">("create")
const editTarget = ref<Template | null>(null)
const showBulkImport = ref(false)

let searchTimer: number | undefined

watch([search, selectedTags, platform, showHidden, page], () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refresh, 200)
})

async function refresh() {
  await store.list({
    search: search.value || undefined,
    tags: selectedTags.value.length ? selectedTags.value : undefined,
    platform: platform.value || undefined,
    hidden: showHidden.value ? "all" : "0",
    limit: pageSize,
    offset: page.value * pageSize,
  })
}

const hiddenCount = computed(() =>
  store.items.filter(t => t.hidden).length,
)

onMounted(async () => {
  await store.loadAllTags()
  await refresh()
})

function openCreate() {
  editMode.value = "create"
  editTarget.value = null
  showEdit.value = true
}
function openEdit(tpl: Template) {
  editMode.value = "edit"
  editTarget.value = tpl
  showEdit.value = true
}

async function onSaved(tpl: Template) {
  showEdit.value = false
  toast.success(editMode.value === "create" ? "已新建模板" : "已保存修改")
  await refresh()
  await store.loadAllTags()
}

function onDuplicate(existingId: number) {
  toast.error(`已存在同文本模板（id=${existingId}）`)
}

async function onImported(result: { created: number; skipped_duplicates: number }) {
  showBulkImport.value = false
  if (result.created === 0) {
    toast.info(`${result.skipped_duplicates} 条全为重复，未导入新内容`)
  } else {
    toast.success(`新增 ${result.created} 条，跳过 ${result.skipped_duplicates} 条重复`)
  }
  await refresh()
  await store.loadAllTags()
}

async function toggleStar(tpl: Template) {
  await store.update(tpl.id, { starred: !tpl.starred })
}

async function toggleHidden(tpl: Template) {
  await store.update(tpl.id, { hidden: !tpl.hidden })
  await refresh()
}

async function doDelete(tpl: Template) {
  const msg = tpl.use_count > 0
    ? `这条用过 ${tpl.use_count} 次，确定删除？删除后无法恢复。`
    : "确定删除？删除后无法恢复。"
  if (!window.confirm(msg)) return
  await store.remove(tpl.id)
  toast.success("已删除")
  await refresh()
}

async function exportJSON() {
  const all = await store.exportAll()
  const json = JSON.stringify(all, null, 2)
  const blob = new Blob([json], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "")
  a.download = `templates-export-${today}.json`
  a.click()
  URL.revokeObjectURL(url)
  toast.success(`已导出 ${all.length} 条模板`)
}

function toggleTag(tag: string) {
  const i = selectedTags.value.indexOf(tag)
  if (i >= 0) selectedTags.value.splice(i, 1)
  else selectedTags.value.push(tag)
}
</script>

<template>
  <div class="section">
    <header class="toolbar">
      <div class="search-wrap">
        <Icon name="search" :size="13" class="search-icon" />
        <input v-model="search" placeholder="搜索文本或标签…" />
      </div>
      <div class="tag-filter">
        <Icon name="tag" :size="11" />
        <button
          v-for="t in store.allTags"
          :key="t"
          class="tag-chip"
          :class="{ active: selectedTags.includes(t) }"
          @click="toggleTag(t)"
        >{{ t }}</button>
        <span v-if="!store.allTags.length" class="muted">（暂无标签）</span>
      </div>
      <select v-model="platform" class="platform-select">
        <option value="">平台：全部</option>
        <option value="douyin">抖音</option>
        <option value="kuaishou">快手</option>
        <option value="bilibili">B 站</option>
        <option value="manual">手动</option>
      </select>
      <label class="show-hidden">
        <input type="checkbox" v-model="showHidden" />
        显示隐藏
      </label>
    </header>

    <div class="actions">
      <button class="primary" @click="openCreate">
        <Icon name="plus" :size="12" /> 新建模板
      </button>
      <button @click="showBulkImport = true">
        <Icon name="upload" :size="12" /> 批量导入
      </button>
      <button @click="exportJSON">
        <Icon name="download" :size="12" /> 导出 JSON
      </button>
      <span class="count">共 {{ store.total }} 条<span v-if="hiddenCount"> · {{ hiddenCount }} 隐藏</span></span>
    </div>

    <div v-if="store.items.length === 0" class="empty">
      <Icon name="bookmark" :size="48" />
      <p>评论模板库还是空的</p>
      <p class="muted">发一条评论它就会自动入库，或者点 + 新建模板 先攒几条</p>
    </div>

    <ul v-else class="list">
      <li
        v-for="tpl in store.items"
        :key="tpl.id"
        class="row"
        :class="{ starred: tpl.starred, hidden: tpl.hidden }"
      >
        <span class="star-slot">
          <button @click="toggleStar(tpl)" :title="tpl.starred ? '取消精选' : '标精选'">
            <Icon name="skills" :size="16" />
          </button>
        </span>
        <div class="body">
          <div class="text">{{ tpl.hidden ? "[已隐藏] " : "" }}{{ tpl.text }}</div>
          <div class="meta">
            <span v-for="t in tpl.tags" :key="t" class="meta-tag">#{{ t }}</span>
            <span v-if="!tpl.tags.length" class="muted">(无标签)</span>
            <span v-if="tpl.source_platform"> · {{ tpl.source_platform }}</span>
            <span> · 用过 {{ tpl.use_count }} 次</span>
            <span> · {{ tpl.first_seen_at.slice(0, 10) }} 入库</span>
          </div>
        </div>
        <div class="ops">
          <button @click="openEdit(tpl)" title="编辑">
            <Icon name="edit" :size="12" /> 编辑
          </button>
          <button @click="toggleHidden(tpl)" :title="tpl.hidden ? '恢复' : '隐藏'">
            <Icon name="eye" :size="12" /> {{ tpl.hidden ? "恢复" : "隐藏" }}
          </button>
          <button class="danger" @click="doDelete(tpl)" title="删除">
            <Icon name="trash" :size="12" /> 删除
          </button>
        </div>
      </li>
    </ul>

    <div v-if="store.total > pageSize" class="pager">
      <button :disabled="page === 0" @click="page--">← 上一页</button>
      <span>第 {{ page * pageSize + 1 }}-{{ Math.min((page + 1) * pageSize, store.total) }} / 共 {{ store.total }}</span>
      <button :disabled="(page + 1) * pageSize >= store.total" @click="page++">下一页 →</button>
    </div>

    <TemplateEditModal
      v-if="showEdit"
      :mode="editMode"
      :template="editTarget"
      @close="showEdit = false"
      @saved="onSaved"
      @duplicate="onDuplicate"
    />
    <TemplateBulkImportModal
      v-if="showBulkImport"
      @close="showBulkImport = false"
      @imported="onImported"
    />
  </div>
</template>

<style scoped>
.section { padding: 16px 0; }
.toolbar {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  margin-bottom: 12px;
}
.search-wrap { position: relative; }
.search-wrap input {
  padding: 5px 10px 5px 28px; min-width: 200px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  background: var(--card-input, #fff); font-size: 12px;
}
.search-icon { position: absolute; left: 8px; top: 50%; transform: translateY(-50%); color: var(--ink-4, #9c8a6a); }
.tag-filter { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.tag-chip {
  background: var(--card-2, #fff5dc); border: 1px solid var(--line, #e8d6a8);
  border-radius: 10px; padding: 2px 8px; font-size: 10px; cursor: pointer;
  color: var(--ink, #6a5520);
}
.tag-chip.active { background: var(--accent, #e0a020); color: #fff; border-color: var(--accent, #e0a020); }
.platform-select {
  padding: 5px 8px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  font-size: 12px; background: var(--card-input, #fff);
}
.show-hidden { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--ink, #6b5a3a); }
.actions {
  display: flex; gap: 8px; align-items: center;
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid var(--line, #e8dcc0);
}
.actions button {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 11px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  background: var(--card, #fff); font-size: 12px; cursor: pointer;
  color: var(--ink, #4a3f2a);
}
.actions button.primary { background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017); }
.count { margin-left: auto; font-size: 11px; color: var(--ink-4, #9c8a6a); }
.empty { text-align: center; padding: 60px 20px; color: var(--ink-4, #9c8a6a); }
.empty p { margin: 6px 0; }
.list { list-style: none; padding: 0; margin: 0; }
.row {
  display: flex; gap: 12px; align-items: center;
  background: var(--card, #fff);
  border: 1px solid var(--line-light, #ece0c2); border-radius: 8px;
  padding: 11px 13px; margin-bottom: 8px;
}
.row.starred { border-color: var(--accent, #e0a020); background: var(--card-warm, #fffaee); }
.row.hidden { opacity: 0.55; }
.star-slot button { background: transparent; border: none; cursor: pointer; padding: 2px; color: var(--ink-4, #c8b888); }
.row.starred .star-slot button { color: var(--accent, #e0a020); }
.body { flex: 1; min-width: 0; }
.text { font-size: 12.5px; color: var(--ink, #2a2017); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { font-size: 10.5px; color: var(--ink-4, #9c8a6a); margin-top: 4px; }
.meta-tag {
  background: var(--card-2, #fff5dc); padding: 1px 6px;
  border-radius: 8px; color: var(--ink, #6a5520); margin-right: 4px;
}
.ops { display: flex; gap: 4px; }
.ops button {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 7px; border: 1px solid var(--line-light, #ece0c2); border-radius: 4px;
  background: var(--card-2, #faf3df); color: var(--ink, #6b5a3a);
  font-size: 10px; cursor: pointer;
}
.ops button.danger { color: #c44; border-color: #f0d0d0; background: #fff5f5; }
.pager { display: flex; gap: 16px; align-items: center; justify-content: center; padding: 14px; font-size: 11px; color: var(--ink-4, #9c8a6a); border-top: 1px dashed var(--line, #e8dcc0); margin-top: 8px; }
.pager button { padding: 4px 10px; border: 1px solid var(--line, #d4c8a8); border-radius: 4px; background: var(--card, #fff); cursor: pointer; font-size: 11px; }
.pager button:disabled { opacity: 0.4; cursor: not-allowed; }
.muted { font-size: 10px; color: var(--ink-4, #9c8a6a); }
</style>
```

- [ ] **Step 2: 在 `SettingsView.vue:170` SECTIONS 数组追加 templates 项**

读 [SettingsView.vue:170-178](frontend/src/views/SettingsView.vue:170) 已有 SECTIONS 数组，在最后一项 `about` 之前追加：

```typescript
{ k: "templates", l: "评论模板库", icon: "bookmark", sub: "查看 · 编辑 · 批量导入 · 导出" },
```

最终数组（参考）：
```typescript
const SECTIONS: SectionDef[] = [
  { k: "general", l: "通用", icon: "settings", sub: "外观 · 行为 · 通知 · 导出" },
  { k: "paths", l: "存储路径", icon: "folder", sub: "Vault · 导出 · 模板 · Skills 目录" },
  { k: "models", l: "模型", icon: "key", sub: "API Key · 模型名 · Base URL" },
  { k: "dedup", l: "历史查重", icon: "vault", sub: "历史 / vault 索引目录与重建" },
  { k: "monitor", l: "监测", icon: "radar", sub: "并发 · 浏览器 · AI · Cookie" },
  { k: "templates", l: "评论模板库", icon: "bookmark", sub: "查看 · 编辑 · 批量导入 · 导出" },
  { k: "account", l: "账号", icon: "user", sub: "登录态 · 工作空间" },
  { k: "about", l: "关于", icon: "info", sub: "版本与更新" },
]
```

- [ ] **Step 3: 在 SettingsView.vue 的 `<template>` section switch 处挂载组件**

grep 找到 SettingsView 里现有 section 渲染条件（搜索 `v-if="section ===` 或 `section.k`）：

```bash
grep -n "section ===" frontend/src/views/SettingsView.vue
```

在已有的 monitor / account 分支旁边追加一个新分支：

```vue
<TemplateLibrarySection v-if="section === 'templates'" />
```

并在 `<script setup>` 顶部 import：

```typescript
import TemplateLibrarySection from "@/components/settings/TemplateLibrarySection.vue"
```

- [ ] **Step 4: vue-tsc + build 检查**

```bash
cd D:/CSM/frontend && pnpm vue-tsc -b && pnpm build
```
Expected: 零错零警告

- [ ] **Step 5: 手测 — 跑 spec §7 完整 checklist**

```bash
cd D:/CSM/frontend && pnpm dev
# 同时另起一个 terminal 启动 sidecar
cd D:/CSM && python -m sidecar.csm_sidecar
```

按 spec [docs/superpowers/specs/2026-05-19-comment-template-library-design.md](../specs/2026-05-19-comment-template-library-design.md) §7 全部 20 项 checklist 逐一勾选。重点验证：

- DB v4 → v5 升级 sidecar 日志
- 自动入库（发一条评论 → done → chips 出现）
- 去重（同文本第二次 → use_count +1）
- chips 排序 + 截断 + hover tooltip
- 替换/追加确认弹层
- Ctrl + / 快捷键打开抽屉
- 抽屉搜索 + 标签交集 + 行内管理
- 设置页全部 5 个核心操作（新建 / 编辑 / 删除 / 批量导入 / 导出 JSON）
- 隐藏 / 显示隐藏切换
- 平台过滤
- 空状态
- 全部图标无 emoji

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/settings/TemplateLibrarySection.vue frontend/src/views/SettingsView.vue
git commit -m "feat(mining/templates): T14 TemplateLibrarySection mounted on settings + manual test pass"
```

---

## 完成检查

- [ ] 14 个 task 全部 commit
- [ ] 后端 18 个测试 + 12 个 API 测试 PASS
- [ ] 前端 3 个 store 单测 PASS + vue-tsc 零错 + build 零警
- [ ] 手测 spec §7 全部 20 项勾选
- [ ] 准备 PR：分支 push + `gh pr create` 给 spec + 这份 plan 作为依据
