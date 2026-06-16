# 小红书图文笔记编辑器 · P0 地基 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 CSM 应用里落地小红书编辑器的地基——独立路由 `/xhs`、纯文本编辑器内核、草稿持久化（sidecar SQLite CRUD + 去抖自动保存）、复制到剪贴板、随编辑实时联动的手机预览（占位图），9 面板骨架（P0 占位，P1 填充）。

**Architecture:** 完全沿用现有惯例。后端新增独立 `csm_core/xhs/storage.py`（自有 `xhs.db`，懒初始化，机制仿 `csm_core/monitor/storage.py`）+ `csm_sidecar/routes/xhs.py`（草稿 CRUD，仿 mining 评论路由）。前端新增 `useXhs` Pinia store（options 风格，仿 `stores/article.ts`）+ 三栏视图 `XhsEditorView.vue` + 子组件（PanelRail / NoteEditor / PhonePreview）+ 纯逻辑工具（`utils/xhsText.ts`、`composables/useCursorInsert.ts`）。

**Tech Stack:** 后端 Python + FastAPI + stdlib sqlite3 + pytest。前端 Vue 3.5 `<script setup lang="ts">` + Pinia + Vue Router 4 + axios（`useSidecar().client`）+ Tailwind 3 + vitest(jsdom)。

---

## 设计依据

本计划实现设计稿 [2026-06-16-xiaohongshu-editor-design.md](../specs/2026-06-16-xiaohongshu-editor-design.md) 的 **P0 阶段**（见该稿 §1「P0 — 地基」与 §7）。P1–P4 各出独立计划。

**P0 范围（in scope）**
- 路由 `/xhs`（name `xhs`）+ 左侧导航「小红书」入口
- `useXhs` store：当前草稿 + 草稿列表 + 面板状态 + 预览 tab
- 三栏骨架：左素材面板（9 标签，P0 占位）/ 中编辑区 / 右手机预览
- 纯文本编辑器内核：标题 input + 正文 textarea + 话题 chips；`insertAtCursor(text)` 光标插入并复位
- 字数计数（标题软上限 20、正文软上限 1000，超限只提示不拦截）
- 草稿持久化：`xhs_drafts` 表 + `/api/xhs/drafts` CRUD + 去抖自动保存
- 复制到剪贴板：标题 / 正文 / 全文
- 右侧预览（笔记页 / 发现页两 tab）实时联动（P0 用占位图）

**P0 明确不做**：图片上传（P2）、素材面板内容与排版主题（P1/P3）、AI（P3）、自定义素材（P4）、预览转 PNG、真发布。

---

## 前置：测试运行环境（执行者必读）

`csm_core`（仓库根）与 `csm_sidecar`（`sidecar/`）是 **editable 安装在主仓 `D:\CSM`** 的包。在本 worktree 里跑 pytest，默认会导入**主仓**代码而非本 worktree 的改动。运行后端测试前，先用 `PYTHONPATH` 覆盖到本 worktree（PowerShell）：

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
```

后端测试命令（在仓库根执行，已设上面的 PYTHONPATH）：

```powershell
python -m pytest sidecar/tests/test_xhs_storage.py -v
```

前端命令（在 `frontend/` 下）：单测 `npx vitest run <spec 路径>`；类型检查 `npx vue-tsc -b`；完整构建门禁 `npm run build`（= `vue-tsc -b && vite build`）。

> ⚠ 已知坑（来自项目记忆）：直接跑 `npx vue-tsc -b` 可能 emit 出 `vite.config.js` / `*.d.ts` 等构建产物并触发 vite 重启。类型检查后若 `git status` 出现这些被改/新增的产物文件，用 `git checkout -- frontend/vite.config.js` 等还原；新增的 `.d.ts` 直接删。`npm run build` 同理，构建产物在 `frontend/dist/`（已被 .gitignore，无需处理）。

每个任务最后一步是 commit。提交信息用中文（项目约定）。

---

## 文件结构（P0 落地清单）

**后端新增**
- `csm_core/xhs/__init__.py` —— 空包标记
- `csm_core/xhs/storage.py` —— 独立 `xhs.db`：连接管理 + 懒初始化 + schema + `xhs_drafts` CRUD
- `sidecar/csm_sidecar/routes/xhs.py` —— 草稿 CRUD 路由
- `sidecar/tests/test_xhs_storage.py` —— storage 单元测试
- `sidecar/tests/test_xhs_routes.py` —— 路由测试

**后端改动**
- `sidecar/csm_sidecar/main.py` —— 注册 xhs router
- `sidecar/tests/conftest.py` —— 新增 `xhs_db` fixture
- `sidecar/csm-sidecar.spec` —— hiddenimports 补 3 条

**前端新增**
- `frontend/src/utils/xhsText.ts` —— 纯函数：`buildFullText` / `countChars`
- `frontend/src/utils/__tests__/xhsText.spec.ts`
- `frontend/src/composables/useCursorInsert.ts` —— `spliceAtSelection`（纯） + `useCursorInsert`（组合式）
- `frontend/src/composables/__tests__/useCursorInsert.spec.ts`
- `frontend/src/stores/xhs.ts` —— `useXhs` store
- `frontend/src/stores/__tests__/xhs.spec.ts`
- `frontend/src/components/xhs/PhonePreview.vue`
- `frontend/src/components/xhs/NoteEditor.vue`
- `frontend/src/components/xhs/PanelRail.vue`
- `frontend/src/views/XhsEditorView.vue`

**前端改动**
- `frontend/src/components/ui/Icon.vue` —— 新增 `notebook` 图标
- `frontend/src/router/index.ts` —— 加 `/xhs` 路由
- `frontend/src/components/LeftNav.vue` —— `NAV_TOP` 加「小红书」项

---

## Task 1: xhs 存储模块——连接管理 + schema + 懒初始化

**Files:**
- Create: `csm_core/xhs/__init__.py`
- Create: `csm_core/xhs/storage.py`
- Test: `sidecar/tests/test_xhs_storage.py`

设计要点：独立 `xhs.db`（不搭车 monitor.db）。连接机制 1:1 仿 `csm_core/monitor/storage.py`（`threading.local` 每线程连接、WAL、idempotent `init_db`、schema_meta 版本），但加 `_ensure_initialized()` 懒初始化，使路由无需显式 wiring（生产首个请求自动建库；测试 fixture 先 `init_db(tmp)`）。

- [ ] **Step 1: 建空包标记**

Create `csm_core/xhs/__init__.py`（空文件，0 字节即可；写一行 docstring 更清晰）：

```python
"""Xiaohongshu (小红书) image-text note editor — storage + helpers."""
```

- [ ] **Step 2: 写失败测试（init 建表 + schema 版本）**

Create `sidecar/tests/test_xhs_storage.py`：

```python
"""Direct unit tests for csm_core/xhs/storage.py（独立 xhs.db）。"""
from __future__ import annotations

from csm_core.xhs import storage as xs


def test_init_creates_schema(xhs_db):
    conn = xs.get_conn()
    # schema_meta 记录版本
    row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    assert row is not None
    assert int(row[0]) == xs._SCHEMA_VERSION
    # xhs_drafts 表存在且列齐
    cols = {r[1] for r in conn.execute("PRAGMA table_info(xhs_drafts)").fetchall()}
    assert cols == {
        "id", "title", "body", "topics_json", "image_ids_json",
        "cover_index", "theme_id", "created_at", "updated_at",
    }


def test_init_is_idempotent(xhs_db):
    # 同路径再 init 不抛
    xs.init_db(xhs_db)
    # 不同路径再 init 应拒绝
    import pytest
    with pytest.raises(RuntimeError):
        xs.init_db(xhs_db.parent / "other.db")
```

> 该测试依赖 Task 3 才加入 conftest 的 `xhs_db` fixture。**先把 fixture 加上**再跑：把下面这段加进 `sidecar/tests/conftest.py`（Task 3 还会复用，提前加无副作用）：

```python
@pytest.fixture
def xhs_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test 独立 xhs.db。重置 storage 模块全局（解除 re-init 守卫）。"""
    from csm_core.xhs import storage as xhs_storage
    db_file = tmp_path / "xhs.db"
    monkeypatch.setattr(xhs_storage, "_db_path", None, raising=True)
    monkeypatch.setattr(xhs_storage, "_initialized", False, raising=True)
    monkeypatch.setattr(xhs_storage, "_local", threading.local(), raising=True)
    xhs_storage.init_db(db_file)
    return db_file
```

`conftest.py` 顶部已 `import threading`、`from pathlib import Path`、`import pytest`，无需再加 import（已存在，见现有 `monitor_db` fixture）。

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest sidecar/tests/test_xhs_storage.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'csm_core.xhs.storage'`（storage 还没写）。

- [ ] **Step 4: 写 storage 模块的连接 + schema 部分**

Create `csm_core/xhs/storage.py`：

```python
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
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest sidecar/tests/test_xhs_storage.py -v`
Expected: PASS（`test_init_creates_schema`、`test_init_is_idempotent` 两条绿）。

- [ ] **Step 6: Commit**

```powershell
git add csm_core/xhs/__init__.py csm_core/xhs/storage.py sidecar/tests/test_xhs_storage.py sidecar/tests/conftest.py
git commit -m "feat(xhs): 小红书草稿存储模块——连接管理与 schema (P0 T1)"
```

---

## Task 2: xhs_drafts CRUD

**Files:**
- Modify: `csm_core/xhs/storage.py`（追加 CRUD 函数）
- Test: `sidecar/tests/test_xhs_storage.py`（追加 CRUD 测试）

CRUD 写法仿 mining storage 的 `create_comment` / `get_comment` / `update_comment` / `delete_comment`（JSON 列、`RETURNING`/`fetchone`、partial update 用 sets/args 拼、`updated_at` 用 `strftime` 自动刷新）。

- [ ] **Step 1: 写失败测试（CRUD 往返）**

在 `sidecar/tests/test_xhs_storage.py` 末尾追加：

```python
def test_create_and_get_roundtrip(xhs_db):
    did = xs.create_draft(
        title="标题",
        body="正文\n第二行",
        topics=["考证", "干货"],
        image_ids=["a", "b"],
        cover_index=1,
        theme_id="warm_yellow",
    )
    assert isinstance(did, str) and len(did) == 32  # uuid4 hex
    d = xs.get_draft(did)
    assert d is not None
    assert d["id"] == did
    assert d["title"] == "标题"
    assert d["body"] == "正文\n第二行"
    assert d["topics"] == ["考证", "干货"]
    assert d["image_ids"] == ["a", "b"]
    assert d["cover_index"] == 1
    assert d["theme_id"] == "warm_yellow"
    assert d["created_at"] and d["updated_at"]


def test_create_defaults(xhs_db):
    did = xs.create_draft()
    d = xs.get_draft(did)
    assert d["title"] == ""
    assert d["body"] == ""
    assert d["topics"] == []
    assert d["image_ids"] == []
    assert d["cover_index"] == 0
    assert d["theme_id"] is None


def test_get_missing_returns_none(xhs_db):
    assert xs.get_draft("nope") is None


def test_update_partial_and_bumps_updated_at(xhs_db):
    did = xs.create_draft(title="old", body="b")
    before = xs.get_draft(did)["updated_at"]
    updated = xs.update_draft(did, title="new", topics=["x"])
    assert updated is not None
    assert updated["title"] == "new"
    assert updated["body"] == "b"          # 未传 → 保持
    assert updated["topics"] == ["x"]
    # updated_at 单调不回退（strftime 毫秒精度；>= 足够稳，避免同毫秒 flake）
    assert updated["updated_at"] >= before


def test_update_missing_returns_none(xhs_db):
    assert xs.update_draft("nope", title="x") is None


def test_update_noop_when_no_fields(xhs_db):
    did = xs.create_draft(title="keep")
    updated = xs.update_draft(did)
    assert updated["title"] == "keep"


def test_list_orders_by_updated_at_desc(xhs_db):
    d1 = xs.create_draft(title="first")
    d2 = xs.create_draft(title="second")
    # 触碰 d1 让它 updated_at 变新 → 应排到最前
    xs.update_draft(d1, body="touched")
    ids = [d["id"] for d in xs.list_drafts()]
    assert ids[0] == d1
    assert set(ids) == {d1, d2}


def test_delete(xhs_db):
    did = xs.create_draft(title="x")
    assert xs.delete_draft(did) is True
    assert xs.get_draft(did) is None
    assert xs.delete_draft(did) is False  # 已不存在
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest sidecar/tests/test_xhs_storage.py -v`
Expected: FAIL —— `AttributeError: module 'csm_core.xhs.storage' has no attribute 'create_draft'`。

- [ ] **Step 3: 实现 CRUD**

在 `csm_core/xhs/storage.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest sidecar/tests/test_xhs_storage.py -v`
Expected: PASS（全部 storage 测试绿）。

- [ ] **Step 5: Commit**

```powershell
git add csm_core/xhs/storage.py sidecar/tests/test_xhs_storage.py
git commit -m "feat(xhs): xhs_drafts CRUD (P0 T2)"
```

---

## Task 3: 草稿 CRUD 路由 + 注册 + 打包 hiddenimports

**Files:**
- Create: `sidecar/csm_sidecar/routes/xhs.py`
- Modify: `sidecar/csm_sidecar/main.py`（import + include_router）
- Modify: `sidecar/csm-sidecar.spec`（hiddenimports 补 3 条）
- Modify: `sidecar/tests/conftest.py`（`xhs_db` fixture —— 若 Task 1 已加则跳过）
- Test: `sidecar/tests/test_xhs_routes.py`

路由层仿 mining 评论路由：`APIRouter(tags=[...], dependencies=[RequireToken])`、Pydantic 请求模型、`HTTPException` 404、DELETE 返回 204。

- [ ] **Step 1: 写失败测试（路由 CRUD）**

Create `sidecar/tests/test_xhs_routes.py`：

```python
"""Routes for xhs draft CRUD (P0 T3)。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_create_then_get(client: TestClient, xhs_db: Path):
    r = client.post("/api/xhs/drafts", json={"title": "T", "body": "B", "topics": ["x"]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["title"] == "T"
    assert d["body"] == "B"
    assert d["topics"] == ["x"]
    assert d["id"]

    g = client.get(f"/api/xhs/drafts/{d['id']}")
    assert g.status_code == 200
    assert g.json()["id"] == d["id"]


def test_create_empty_ok(client: TestClient, xhs_db: Path):
    # 空草稿也允许（前端只在有内容时才建，但 API 不强制）
    r = client.post("/api/xhs/drafts", json={})
    assert r.status_code == 201
    assert r.json()["title"] == ""


def test_list(client: TestClient, xhs_db: Path):
    client.post("/api/xhs/drafts", json={"title": "a"})
    client.post("/api/xhs/drafts", json={"title": "b"})
    r = client.get("/api/xhs/drafts")
    assert r.status_code == 200
    drafts = r.json()["drafts"]
    assert len(drafts) == 2
    assert {d["title"] for d in drafts} == {"a", "b"}


def test_patch_partial(client: TestClient, xhs_db: Path):
    cid = client.post("/api/xhs/drafts", json={"title": "old", "body": "keep"}).json()["id"]
    r = client.patch(f"/api/xhs/drafts/{cid}", json={"title": "new"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "new"
    assert body["body"] == "keep"


def test_patch_missing_404(client: TestClient, xhs_db: Path):
    r = client.patch("/api/xhs/drafts/deadbeef", json={"title": "x"})
    assert r.status_code == 404


def test_get_missing_404(client: TestClient, xhs_db: Path):
    r = client.get("/api/xhs/drafts/deadbeef")
    assert r.status_code == 404


def test_delete(client: TestClient, xhs_db: Path):
    cid = client.post("/api/xhs/drafts", json={"title": "x"}).json()["id"]
    r = client.delete(f"/api/xhs/drafts/{cid}")
    assert r.status_code == 204
    assert client.get(f"/api/xhs/drafts/{cid}").status_code == 404


def test_delete_missing_404(client: TestClient, xhs_db: Path):
    assert client.delete("/api/xhs/drafts/deadbeef").status_code == 404
```

> 若 Task 1 未加 `xhs_db` fixture，现在把它加进 `sidecar/tests/conftest.py`（内容见 Task 1 Step 2）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest sidecar/tests/test_xhs_routes.py -v`
Expected: FAIL —— 所有路由 404（`/api/xhs/drafts` 还未注册）。

- [ ] **Step 3: 实现路由文件**

Create `sidecar/csm_sidecar/routes/xhs.py`：

```python
"""小红书图文笔记编辑器路由 —— 草稿 CRUD（P0）。

图片上传/serve（P2）、AI 生成/润色（P3）、ai_prompts（P4）后续追加到本文件。
持久化走独立 ``csm_core.xhs.storage``（自有 xhs.db），与 mining/monitor 解耦。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from csm_core.xhs import storage as xhs_storage

from ..auth import RequireToken

logger = logging.getLogger(__name__)

router = APIRouter(tags=["xhs"], dependencies=[RequireToken])


class DraftCreate(BaseModel):
    title: str = ""
    body: str = ""
    topics: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)
    cover_index: int = 0
    theme_id: str | None = None


class DraftPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    topics: list[str] | None = None
    image_ids: list[str] | None = None
    cover_index: int | None = None
    theme_id: str | None = None


@router.get("/api/xhs/drafts")
def list_drafts() -> dict[str, Any]:
    return {"drafts": xhs_storage.list_drafts()}


@router.post("/api/xhs/drafts", status_code=201)
def create_draft(body: DraftCreate) -> dict[str, Any]:
    draft_id = xhs_storage.create_draft(
        title=body.title,
        body=body.body,
        topics=body.topics,
        image_ids=body.image_ids,
        cover_index=body.cover_index,
        theme_id=body.theme_id,
    )
    return xhs_storage.get_draft(draft_id) or {}


@router.get("/api/xhs/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    d = xhs_storage.get_draft(draft_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    return d


@router.patch("/api/xhs/drafts/{draft_id}")
def patch_draft(draft_id: str, body: DraftPatch) -> dict[str, Any]:
    updated = xhs_storage.update_draft(
        draft_id,
        title=body.title,
        body=body.body,
        topics=body.topics,
        image_ids=body.image_ids,
        cover_index=body.cover_index,
        theme_id=body.theme_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    return updated


@router.delete("/api/xhs/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: str) -> None:
    if not xhs_storage.delete_draft(draft_id):
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
```

- [ ] **Step 4: 注册 router 到 main.py**

在 `sidecar/csm_sidecar/main.py` 的 import 区（与其它 `from .routes import ...` 同段，按字母序放在 `vault` 之后即可）加：

```python
from .routes import vault as vault_routes
from .routes import xhs as xhs_routes
```

在 `app.include_router(...)` 段末尾（`assembler_routes` 之后）加：

```python
app.include_router(assembler_routes.router)
app.include_router(xhs_routes.router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest sidecar/tests/test_xhs_routes.py -v`
Expected: PASS（8 条路由测试全绿）。

- [ ] **Step 6: 补 PyInstaller hiddenimports**

`sidecar/csm-sidecar.spec` 用的是**显式 hiddenimports 清单**（非 `collect_submodules` 扫描）。xhs 模块虽是静态 import 能被 modulegraph 抓到，但按 house-style 显式登记，零风险消除边角遗漏。

在 spec 的 `hiddenimports = [...]` 列表里：
- `"csm_core.monitor",` 这一段之前（紧跟 `"csm_core.keyword.extractor",` 之后的某处，与其它 `csm_core.*` 子包同段）加：

```python
    "csm_core.xhs",
    "csm_core.xhs.storage",
```

- 在 `"csm_sidecar.routes.vault",` 之后加：

```python
    "csm_sidecar.routes.vault",
    "csm_sidecar.routes.xhs",
```

（无 .graphql / 数据文件；现有 `collect_data_files("csm_core"/"csm_sidecar", include_py_files=False)` 已兜底将来任何数据文件，本任务不需改那两行。）

- [ ] **Step 7: 跑全量后端测试确认无回归**

Run: `python -m pytest sidecar/tests/test_xhs_storage.py sidecar/tests/test_xhs_routes.py -v`
Expected: PASS（storage + routes 全绿）。

> 可选：`python -m pytest sidecar/tests/test_health.py -v` 确认 app 仍能正常起（lifespan 注册新 router 没炸）。

- [ ] **Step 8: Commit**

```powershell
git add sidecar/csm_sidecar/routes/xhs.py sidecar/csm_sidecar/main.py sidecar/csm-sidecar.spec sidecar/tests/test_xhs_routes.py sidecar/tests/conftest.py
git commit -m "feat(xhs): 草稿 CRUD 路由 + 注册 + 打包登记 (P0 T3)"
```

---

## Task 4: 纯文本工具——buildFullText / countChars

**Files:**
- Create: `frontend/src/utils/xhsText.ts`
- Test: `frontend/src/utils/__tests__/xhsText.spec.ts`

纯函数（无 DOM、无依赖），先做 TDD。`countChars` 用码点计数（emoji 计 1），`buildFullText` 组装「标题 + 空行 + 正文 + 空行 + #话题」。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/utils/__tests__/xhsText.spec.ts`：

```typescript
import { describe, it, expect } from "vitest";
import { buildFullText, countChars } from "@/utils/xhsText";

describe("countChars", () => {
  it("ASCII 按字符数", () => {
    expect(countChars("hello")).toBe(5);
  });
  it("中文按字数", () => {
    expect(countChars("小红书")).toBe(3);
  });
  it("单个 emoji 计 1（码点）", () => {
    expect(countChars("💛")).toBe(1);
    expect(countChars("a💛b")).toBe(3);
  });
  it("空串为 0", () => {
    expect(countChars("")).toBe(0);
  });
});

describe("buildFullText", () => {
  it("标题 + 正文 + 话题用空行拼接，话题加 #", () => {
    expect(buildFullText("标题", "正文内容", ["考证", "干货"])).toBe(
      "标题\n\n正文内容\n\n#考证 #干货",
    );
  });
  it("正文保留内部换行，不被 trim", () => {
    expect(buildFullText("T", "第一行\n第二行", [])).toBe("T\n\n第一行\n第二行");
  });
  it("无标题时跳过标题段", () => {
    expect(buildFullText("", "正文", ["x"])).toBe("正文\n\n#x");
  });
  it("无话题时跳过话题段", () => {
    expect(buildFullText("T", "B", [])).toBe("T\n\nB");
  });
  it("话题去掉空白项，并去掉用户误带的前导 #", () => {
    expect(buildFullText("", "", ["  ", "#已带", "正常"])).toBe("#已带 #正常");
  });
  it("全空返回空串", () => {
    expect(buildFullText("", "", [])).toBe("");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/utils/__tests__/xhsText.spec.ts`
Expected: FAIL —— 无法解析 `@/utils/xhsText`（文件不存在）。

- [ ] **Step 3: 实现工具**

Create `frontend/src/utils/xhsText.ts`：

```typescript
/**
 * 小红书纯文本工具 —— 编辑器内核的字数与「一键复制」组装逻辑。
 *
 * 纯函数、无 DOM 依赖，便于单测。所有「点素材插入」相关的光标逻辑在
 * composables/useCursorInsert.ts。
 */

/**
 * 按 Unicode 码点计数（emoji 计 1）。与小红书官方计数口径可能有个位数
 * 差异（ZWJ 组合 emoji 会被算成多个码点），作为软提示可接受 —— 见设计
 * 稿 §8「emoji 计数口径」。
 */
export function countChars(s: string): number {
  return [...s].length;
}

/**
 * 组装「复制全文」：标题 + 空行 + 正文 + 空行 + `#话题` 串。
 *
 * - 标题用 trim 后判空（首尾空白不该单独成段）；
 * - 正文**不 trim**（保留 emoji 排版的首尾换行/缩进），仅用 trim 判空；
 * - 话题逐个 trim、去掉用户误带的前导 `#`、丢弃空项，再以空格连接。
 */
export function buildFullText(title: string, body: string, topics: string[]): string {
  const parts: string[] = [];
  if (title.trim()) parts.push(title.trim());
  if (body.trim()) parts.push(body);
  const tags = topics
    .map((t) => t.replace(/^#+/, "").trim())
    .filter((t) => t.length > 0)
    .map((t) => `#${t}`);
  if (tags.length) parts.push(tags.join(" "));
  return parts.join("\n\n");
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend; npx vitest run src/utils/__tests__/xhsText.spec.ts`
Expected: PASS（countChars + buildFullText 全绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/utils/xhsText.ts frontend/src/utils/__tests__/xhsText.spec.ts
git commit -m "feat(xhs): 纯文本工具 buildFullText/countChars (P0 T4)"
```

---

## Task 5: 光标插入内核——spliceAtSelection / useCursorInsert

**Files:**
- Create: `frontend/src/composables/useCursorInsert.ts`
- Test: `frontend/src/composables/__tests__/useCursorInsert.spec.ts`

`spliceAtSelection` 是纯字符串变换（重点单测）；`useCursorInsert` 把它接到 textarea（取 selection → 替换 → 回调更新模型 → nextTick 复位光标 + 重新 focus）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/composables/__tests__/useCursorInsert.spec.ts`：

```typescript
import { describe, it, expect, vi } from "vitest";
import { ref, nextTick } from "vue";
import { spliceAtSelection, useCursorInsert } from "@/composables/useCursorInsert";

describe("spliceAtSelection（纯）", () => {
  it("在中间插入", () => {
    expect(spliceAtSelection("abcd", 2, 2, "XY")).toEqual({ value: "abXYcd", caret: 4 });
  });
  it("末尾追加（无选区）", () => {
    expect(spliceAtSelection("abc", 3, 3, "!")).toEqual({ value: "abc!", caret: 4 });
  });
  it("替换选区", () => {
    expect(spliceAtSelection("abcd", 1, 3, "X")).toEqual({ value: "aXd", caret: 2 });
  });
  it("越界 start/end 被夹紧", () => {
    expect(spliceAtSelection("ab", 99, 99, "Z")).toEqual({ value: "abZ", caret: 3 });
    expect(spliceAtSelection("ab", -5, -5, "Z")).toEqual({ value: "Zab", caret: 1 });
  });
  it("start>end 时按 max(start) 退化为插入点", () => {
    expect(spliceAtSelection("abcd", 3, 1, "X")).toEqual({ value: "abcXd", caret: 4 });
  });
});

describe("useCursorInsert（接 textarea）", () => {
  it("在光标处插入并通过回调更新模型，nextTick 复位光标", async () => {
    const el = document.createElement("textarea");
    el.value = "abcd";
    document.body.appendChild(el);
    el.focus();
    el.setSelectionRange(2, 2);

    const taRef = ref<HTMLTextAreaElement | null>(el);
    const onUpdate = vi.fn((v: string) => {
      el.value = v; // 模拟模型回写到 DOM（真实里由 Vue :value 绑定完成）
    });
    const { insert } = useCursorInsert(taRef, onUpdate);

    insert("XY");
    expect(onUpdate).toHaveBeenCalledWith("abXYcd");
    await nextTick();
    expect(el.selectionStart).toBe(4);
    expect(el.selectionEnd).toBe(4);

    el.remove();
  });

  it("textarea ref 为空时回退到末尾追加", () => {
    const taRef = ref<HTMLTextAreaElement | null>(null);
    let captured = "";
    const { insert } = useCursorInsert(taRef, (v) => { captured = v; });
    // ref 为空 → current="" → 末尾插入
    insert("hi");
    expect(captured).toBe("hi");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/composables/__tests__/useCursorInsert.spec.ts`
Expected: FAIL —— 无法解析 `@/composables/useCursorInsert`。

- [ ] **Step 3: 实现 composable**

Create `frontend/src/composables/useCursorInsert.ts`：

```typescript
/**
 * textarea 光标插入内核 —— 设计稿 §4.2。所有「点素材插入」（emoji / 装饰
 * / 文案 / 主题符号，P1 起）都走 useCursorInsert().insert(text) 这一个入口。
 */
import { type Ref, nextTick } from "vue";

/**
 * 纯字符串变换：把 [start, end) 区间替换为 insert，返回新串与插入后光标位。
 * start/end 会被夹紧到 [0, value.length]；start>end 时取 max 退化为插入点。
 */
export function spliceAtSelection(
  value: string,
  start: number,
  end: number,
  insert: string,
): { value: string; caret: number } {
  const len = value.length;
  const s = Math.max(0, Math.min(start, len));
  const e = Math.max(s, Math.min(end, len));
  const next = value.slice(0, s) + insert + value.slice(e);
  return { value: next, caret: s + insert.length };
}

/**
 * 把 textarea ref 接上光标插入。
 *
 * @param textareaRef 目标 textarea 的模板 ref
 * @param onUpdate    收到新串后回调（调用方据此更新 v-model / store）
 *
 * insert(text)：取当前选区 → spliceAtSelection → onUpdate(newValue) →
 * nextTick 后把光标移到插入串末尾并重新 focus（等 Vue 把新值 patch 进 DOM）。
 */
export function useCursorInsert(
  textareaRef: Ref<HTMLTextAreaElement | null>,
  onUpdate: (value: string) => void,
) {
  function insert(text: string): void {
    const el = textareaRef.value;
    const current = el ? el.value : "";
    const start = el ? el.selectionStart ?? current.length : current.length;
    const end = el ? el.selectionEnd ?? current.length : current.length;
    const { value, caret } = spliceAtSelection(current, start, end, text);
    onUpdate(value);
    void nextTick(() => {
      const after = textareaRef.value;
      if (!after) return;
      after.focus();
      after.setSelectionRange(caret, caret);
    });
  }
  return { insert };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend; npx vitest run src/composables/__tests__/useCursorInsert.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/composables/useCursorInsert.ts frontend/src/composables/__tests__/useCursorInsert.spec.ts
git commit -m "feat(xhs): 光标插入内核 spliceAtSelection/useCursorInsert (P0 T5)"
```

---

## Task 6: useXhs Pinia store

**Files:**
- Create: `frontend/src/stores/xhs.ts`
- Test: `frontend/src/stores/__tests__/xhs.spec.ts`

options 风格 store（仿 `stores/article.ts`）。承载：当前草稿字段、草稿列表、面板/预览 tab 状态、去抖自动保存（首次有内容才 POST 建草稿、之后 PATCH）、复制、光标插入入口（注册式，供 P1 面板调用）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/stores/__tests__/xhs.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();
const deleteMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: { get: getMock, post: postMock, patch: patchMock, delete: deleteMock },
    sseURL: (p: string) => p,
  }),
}));

import { useXhs } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  deleteMock.mockReset();
  // 全程用 fake timers：scheduleSave 的模块级 _saveTimer 不会在用例间
  // 乱触发；afterEach 清掉所有挂起定时器，杜绝跨用例污染。
  vi.useFakeTimers();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("useXhs — getters", () => {
  it("fullText 组装标题/正文/话题", () => {
    const x = useXhs();
    x.$patch({ title: "T", body: "B", topics: ["a"] });
    expect(x.fullText).toBe("T\n\nB\n\n#a");
  });
  it("字数与超限标志", () => {
    const x = useXhs();
    x.$patch({ title: "x".repeat(21) });
    expect(x.titleCount).toBe(21);
    expect(x.titleOver).toBe(true);
    expect(x.bodyOver).toBe(false);
  });
  it("isEmpty 看标题与正文是否都空白", () => {
    const x = useXhs();
    expect(x.isEmpty).toBe(true);
    x.$patch({ body: "  " });
    expect(x.isEmpty).toBe(true);
    x.$patch({ body: "字" });
    expect(x.isEmpty).toBe(false);
  });
});

describe("useXhs — 自动保存 _ensureCreated", () => {
  it("空草稿 saveNow 不发请求", async () => {
    const x = useXhs();
    await x.saveNow();
    expect(postMock).not.toHaveBeenCalled();
    expect(patchMock).not.toHaveBeenCalled();
  });

  it("首次有内容 → POST 建草稿一次；再 saveNow → 只 PATCH", async () => {
    postMock.mockResolvedValue({ data: { id: "d1", title: "T", body: "", topics: [], image_ids: [], cover_index: 0, theme_id: null } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.$patch({ title: "T" });

    await x.saveNow();
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(x.draftId).toBe("d1");
    expect(patchMock).toHaveBeenCalledTimes(1); // 建完立即 PATCH 一次落盘当前态
    expect(patchMock).toHaveBeenCalledWith("/api/xhs/drafts/d1", expect.objectContaining({ title: "T" }));

    await x.saveNow();
    expect(postMock).toHaveBeenCalledTimes(1); // 不再建第二次
    expect(patchMock).toHaveBeenCalledTimes(2);
  });

  it("scheduleSave 去抖：800ms 后触发一次 saveNow", async () => {
    // fake timers 已在 beforeEach 全局开启
    postMock.mockResolvedValue({ data: { id: "d1" } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.setTitle("a");
    x.setTitle("ab");
    x.setTitle("abc"); // 连续输入只应触发一次
    expect(postMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(800);
    expect(postMock).toHaveBeenCalledTimes(1);
  });
});

describe("useXhs — 话题", () => {
  it("addTopic 去前导 # + 去重 + 丢空", () => {
    const x = useXhs();
    x.addTopic("#考证");
    x.addTopic("考证"); // 重复
    x.addTopic("   ");  // 空
    x.addTopic("干货");
    expect(x.topics).toEqual(["考证", "干货"]);
  });
  it("removeTopic 按下标删除", () => {
    const x = useXhs();
    x.$patch({ topics: ["a", "b", "c"] });
    x.removeTopic(1);
    expect(x.topics).toEqual(["a", "c"]);
  });
});

describe("useXhs — 光标插入入口", () => {
  it("注册 inserter 后 insertAtCursor 委托给它", () => {
    const x = useXhs();
    const fn = vi.fn();
    x.registerInserter(fn);
    x.insertAtCursor("💛");
    expect(fn).toHaveBeenCalledWith("💛");
  });
  it("未注册 inserter 时回退为追加到正文末尾", () => {
    const x = useXhs();
    x.$patch({ body: "abc" });
    x.insertAtCursor("!");
    expect(x.body).toBe("abc!");
  });
});

describe("useXhs — 复制", () => {
  it("copy('full') 写入剪贴板全文", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const x = useXhs();
    x.$patch({ title: "T", body: "B", topics: ["a"] });
    await x.copy("full");
    expect(writeText).toHaveBeenCalledWith("T\n\nB\n\n#a");
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: FAIL —— 无法解析 `@/stores/xhs`。

- [ ] **Step 3: 实现 store**

Create `frontend/src/stores/xhs.ts`：

```typescript
/**
 * 小红书图文笔记编辑器 store（设计稿 §4）。
 *
 * 承载当前草稿（title/body/topics/images/cover/theme）、草稿列表、面板与
 * 预览 tab 状态。去抖自动保存：内容变化 → scheduleSave(800ms) → 首次有内容
 * 时 POST 建草稿拿 id，之后 PATCH。复制走 navigator.clipboard。
 *
 * 光标插入采用「注册式」：NoteEditor 挂载时 registerInserter(insert)，P1 的
 * 素材面板调 insertAtCursor(text) 即把内容插到正文光标处（跨组件解耦）。
 */
import { defineStore } from "pinia";

import { useSidecar } from "./sidecar";
import { useToast } from "@/composables/useToast";
import { buildFullText, countChars } from "@/utils/xhsText";

export interface XhsDraft {
  id: string;
  title: string;
  body: string;
  topics: string[];
  image_ids: string[];
  cover_index: number;
  theme_id: string | null;
  created_at: string;
  updated_at: string;
}

export type XhsPanel =
  | "template" | "theme" | "emoji" | "title" | "copy"
  | "topic" | "decoration" | "image" | "ai";

export type XhsPreviewTab = "note" | "discover";

export const TITLE_SOFT_LIMIT = 20;
export const BODY_SOFT_LIMIT = 1000;

interface XhsState {
  draftId: string | null;
  title: string;
  body: string;
  topics: string[];
  imageIds: string[];
  coverIndex: number;
  themeId: string | null;
  activePanel: XhsPanel;
  previewTab: XhsPreviewTab;
  drafts: XhsDraft[];
  saving: boolean;
}

// 去抖定时器与「正文插入器」放模块级：它们不该进 Pinia 响应式 state
// （一个是 timer handle，一个是 DOM 操作回调，都不需要触发渲染）。
let _saveTimer: ReturnType<typeof setTimeout> | null = null;
let _inserter: ((text: string) => void) | null = null;

export const useXhs = defineStore("xhs", {
  state: (): XhsState => ({
    draftId: null,
    title: "",
    body: "",
    topics: [],
    imageIds: [],
    coverIndex: 0,
    themeId: null,
    activePanel: "template",
    previewTab: "note",
    drafts: [],
    saving: false,
  }),
  getters: {
    fullText: (s): string => buildFullText(s.title, s.body, s.topics),
    titleCount: (s): number => countChars(s.title),
    bodyCount: (s): number => countChars(s.body),
    titleOver: (s): boolean => countChars(s.title) > TITLE_SOFT_LIMIT,
    bodyOver: (s): boolean => countChars(s.body) > BODY_SOFT_LIMIT,
    isEmpty: (s): boolean => s.title.trim() === "" && s.body.trim() === "",
  },
  actions: {
    async loadDrafts(): Promise<void> {
      const sidecar = useSidecar();
      try {
        const r = await sidecar.client.get("/api/xhs/drafts");
        this.drafts = r.data.drafts ?? [];
      } catch {
        this.drafts = [];
      }
    },
    async loadDraft(id: string): Promise<void> {
      const sidecar = useSidecar();
      const r = await sidecar.client.get(`/api/xhs/drafts/${id}`);
      this._apply(r.data as XhsDraft);
    },
    _apply(d: XhsDraft): void {
      this.draftId = d.id;
      this.title = d.title ?? "";
      this.body = d.body ?? "";
      this.topics = [...(d.topics ?? [])];
      this.imageIds = [...(d.image_ids ?? [])];
      this.coverIndex = d.cover_index ?? 0;
      this.themeId = d.theme_id ?? null;
    },
    newDraft(): void {
      if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
      this.draftId = null;
      this.title = "";
      this.body = "";
      this.topics = [];
      this.imageIds = [];
      this.coverIndex = 0;
      this.themeId = null;
    },
    _payload() {
      return {
        title: this.title,
        body: this.body,
        topics: this.topics,
        image_ids: this.imageIds,
        cover_index: this.coverIndex,
        theme_id: this.themeId,
      };
    },
    /** 首次有内容时建草稿拿 id；空草稿不建（避免堆积）。返回 draftId 或 null。 */
    async _ensureCreated(): Promise<string | null> {
      if (this.draftId) return this.draftId;
      if (this.isEmpty) return null;
      const sidecar = useSidecar();
      const r = await sidecar.client.post("/api/xhs/drafts", this._payload());
      this.draftId = r.data.id;
      return this.draftId;
    },
    scheduleSave(): void {
      if (_saveTimer) clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => { void this.saveNow(); }, 800);
    },
    async saveNow(): Promise<void> {
      if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
      const id = await this._ensureCreated();
      if (!id) return;
      const sidecar = useSidecar();
      this.saving = true;
      try {
        await sidecar.client.patch(`/api/xhs/drafts/${id}`, this._payload());
      } catch {
        /* 自动保存失败静默；下次编辑会再次触发。手动「立即保存」可由 UI 暴露。 */
      } finally {
        this.saving = false;
      }
    },
    setTitle(v: string): void {
      this.title = v;
      this.scheduleSave();
    },
    setBody(v: string): void {
      this.body = v;
      this.scheduleSave();
    },
    addTopic(tag: string): void {
      const t = tag.replace(/^#+/, "").trim();
      if (!t || this.topics.includes(t)) return;
      this.topics.push(t);
      this.scheduleSave();
    },
    removeTopic(i: number): void {
      this.topics.splice(i, 1);
      this.scheduleSave();
    },
    setActivePanel(p: XhsPanel): void {
      this.activePanel = p;
    },
    setPreviewTab(t: XhsPreviewTab): void {
      this.previewTab = t;
    },
    /** NoteEditor 挂载时注册正文光标插入器；卸载时传 null 注销。 */
    registerInserter(fn: ((text: string) => void) | null): void {
      _inserter = fn;
    },
    /** P1 素材面板插入入口：有注册器走光标插入，否则回退追加到正文末尾。 */
    insertAtCursor(text: string): void {
      if (_inserter) {
        _inserter(text);
      } else {
        this.setBody(this.body + text);
      }
    },
    async copy(kind: "title" | "body" | "full"): Promise<void> {
      const text = kind === "title" ? this.title : kind === "body" ? this.body : this.fullText;
      const toast = useToast();
      try {
        await navigator.clipboard.writeText(text);
        toast.success("已复制");
      } catch {
        toast.error("复制失败，请检查剪贴板权限");
      }
    },
    async deleteDraft(id: string): Promise<void> {
      const sidecar = useSidecar();
      await sidecar.client.delete(`/api/xhs/drafts/${id}`);
      if (this.draftId === id) this.newDraft();
      await this.loadDrafts();
    },
  },
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend; npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: PASS（getters / 自动保存 / 话题 / 插入 / 复制 全绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/stores/xhs.ts frontend/src/stores/__tests__/xhs.spec.ts
git commit -m "feat(xhs): useXhs store——草稿/自动保存/复制/光标插入 (P0 T6)"
```

---

## Task 7: 导航接线——notebook 图标 + 路由 + LeftNav 入口

**Files:**
- Modify: `frontend/src/components/ui/Icon.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/LeftNav.vue`

视图组件 Task 8–11 才建；本任务先把路由指向一个**临时占位**，确保接线可独立验证、且不依赖尚未存在的视图。Task 11 再把占位换成真视图。

- [ ] **Step 1: 加 notebook 图标**

在 `frontend/src/components/ui/Icon.vue` 的 `PATHS` 对象里（任意位置，建议放在 `doc:` 附近）加一条 —— 小红书/笔记本图标（书脊 + 翻页线）：

```typescript
  notebook:
    '<path d="M4 4a2 2 0 0 1 2-2h12a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2z"/><path d="M9 2v20"/><path d="M13 7h3"/><path d="M13 11h3"/>',
```

- [ ] **Step 2: 加 /xhs 路由（先指占位）**

在 `frontend/src/router/index.ts` 的 `routes` 数组里，`templates` 路由之后加（注意：组件先用一个内联占位，Task 11 改为 `XhsEditorView.vue`）：

```typescript
    {
      path: "/xhs",
      name: "xhs",
      // P0 T11 会换成 () => import("@/views/XhsEditorView.vue")
      component: () => import("@/views/XhsEditorView.vue"),
      meta: { label: "小红书" },
    },
```

> 说明：这里直接写最终的 `XhsEditorView.vue` 引用。因为是路由懒加载（动态 import 只在导航到 `/xhs` 时才解析），在 Task 11 创建该文件前，只要不点进「小红书」页，`npm run build` 仍可能因找不到 chunk 报错。**为避免 Task 7 阶段构建失败**：本步先创建一个最小占位视图 `frontend/src/views/XhsEditorView.vue`（Task 11 会整文件替换）：

```vue
<script setup lang="ts">
// P0 T7 占位 —— Task 11 替换为三栏编辑器。
</script>

<template>
  <div class="flex h-full items-center justify-center" :style="{ color: 'var(--ink-2)' }">
    小红书编辑器（搭建中）
  </div>
</template>
```

- [ ] **Step 3: LeftNav 加入口**

在 `frontend/src/components/LeftNav.vue` 的 `NAV_TOP` 数组末尾（`templates` 之后）加一项：

```typescript
const NAV_TOP = [
  { key: "home", icon: "home", label: "工作台" },
  { key: "article", icon: "edit", label: "创作区" },
  { key: "monitor", icon: "radar", label: "监测中心" },
  { key: "data-center", icon: "fileText", label: "数据中心" },
  { key: "mining", icon: "search", label: "引流" },
  { key: "templates", icon: "library", label: "模板库" },
  { key: "xhs", icon: "notebook", label: "小红书" },
] as const;
```

- [ ] **Step 4: 类型检查 + 构建**

Run: `cd frontend; npm run build`
Expected: 构建成功，零类型错误。（构建产物落在 `frontend/dist/`，已 gitignore。若 `git status` 出现 `vite.config.js`/`*.d.ts` 等被 emit 的产物，按「前置」一节还原。）

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/ui/Icon.vue frontend/src/router/index.ts frontend/src/components/LeftNav.vue frontend/src/views/XhsEditorView.vue
git commit -m "feat(xhs): 导航接线——notebook 图标/路由/LeftNav 入口 + 占位视图 (P0 T7)"
```

---

## Task 8: PhonePreview.vue（手机预览）

**Files:**
- Create: `frontend/src/components/xhs/PhonePreview.vue`

纯展示组件，读 `useXhs` 实时渲染。两 tab：笔记页（封面占位 + 标题 + 正文 pre-wrap + 蓝色 #话题 + 假互动栏）/ 发现页（瀑布流卡片：封面 + 两行标题 + 头像昵称 + 假点赞）。P0 封面用占位。emoji 依赖系统 Segoe UI Emoji 彩色字形。

- [ ] **Step 1: 创建组件**

Create `frontend/src/components/xhs/PhonePreview.vue`：

```vue
<script setup lang="ts">
/**
 * 手机预览（设计稿 §4.3）—— 纯 computed 渲染，不做 DOM 转图（导出=复制文案）。
 * 笔记页 / 发现页两 tab。P0 封面用占位块；真实图在 P2 接。
 */
import { computed } from "vue";
import { useXhs } from "@/stores/xhs";
import { useConfig } from "@/stores/config";

const xhs = useXhs();
const cfg = useConfig();

const nickname = computed<string>(() => (cfg.data?.user_name as string) || "我的小红书");
const avatarLetter = computed<string>(() => (nickname.value || "我").slice(0, 1).toUpperCase());

// 正文按行渲染（white-space: pre-wrap 保留换行与缩进 + emoji）。
const displayTitle = computed(() => xhs.title || "添加标题更吸睛～");
const displayBody = computed(() => xhs.body || "正文还没写哦，左侧素材点一点，右侧实时预览～");
const tags = computed(() => xhs.topics.filter((t) => t.trim()));
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <!-- tab 切换 -->
    <div class="flex items-center justify-center" :style="{ gap: '6px' }">
      <button
        v-for="t in (['note', 'discover'] as const)"
        :key="t"
        type="button"
        :style="{
          fontSize: '12px',
          padding: '4px 12px',
          borderRadius: '999px',
          border: '1px solid var(--line-2)',
          cursor: 'pointer',
          background: xhs.previewTab === t ? 'var(--primary)' : 'transparent',
          color: xhs.previewTab === t ? '#fff' : 'var(--ink-2)',
        }"
        @click="xhs.setPreviewTab(t)"
      >
        {{ t === 'note' ? '笔记页' : '发现页' }}
      </button>
    </div>

    <!-- 手机外框 -->
    <div
      class="min-h-0 flex-1 overflow-y-auto"
      :style="{
        margin: '0 auto',
        width: '300px',
        maxWidth: '100%',
        borderRadius: '28px',
        border: '8px solid var(--dark)',
        background: '#fff',
        boxShadow: '0 12px 30px -10px rgba(var(--shadow-rgb),0.25)',
      }"
    >
      <!-- ── 笔记页 ── -->
      <div v-if="xhs.previewTab === 'note'" :style="{ paddingBottom: '12px' }">
        <!-- 封面（P0 占位） -->
        <div
          :style="{
            width: '100%',
            aspectRatio: '3 / 4',
            background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--primary)',
            fontSize: '13px',
            borderRadius: '20px 20px 0 0',
          }"
        >
          封面图（P2 上传）
        </div>
        <div :style="{ padding: '12px 14px' }">
          <!-- 作者条 -->
          <div class="flex items-center" :style="{ gap: '8px', marginBottom: '8px' }">
            <div
              :style="{
                width: '28px', height: '28px', borderRadius: '999px',
                background: 'var(--dark)', color: 'var(--primary)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '12px', fontWeight: 700,
              }"
            >{{ avatarLetter }}</div>
            <span :style="{ fontSize: '13px', color: 'var(--ink)', flex: 1 }">{{ nickname }}</span>
            <span :style="{ fontSize: '12px', color: '#fff', background: '#ff2e4d', padding: '3px 12px', borderRadius: '999px' }">关注</span>
          </div>
          <!-- 标题 -->
          <div
            :style="{
              fontSize: '16px', fontWeight: 700, lineHeight: 1.4, marginBottom: '6px',
              color: xhs.title ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }"
          >{{ displayTitle }}</div>
          <!-- 正文 -->
          <div
            :style="{
              fontSize: '14px', lineHeight: 1.7,
              color: xhs.body ? 'var(--ink)' : '#bbb',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }"
          >{{ displayBody }}</div>
          <!-- 话题 -->
          <div v-if="tags.length" :style="{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px 8px' }">
            <span v-for="(t, i) in tags" :key="i" :style="{ fontSize: '14px', color: '#3a6fb0' }">#{{ t }}</span>
          </div>
          <!-- 假互动栏 -->
          <div class="flex items-center" :style="{ gap: '16px', marginTop: '12px', color: 'var(--ink-2)', fontSize: '12px' }">
            <span>♡ 1.2k</span><span>☆ 328</span><span>💬 56</span>
          </div>
        </div>
      </div>

      <!-- ── 发现页 ── -->
      <div v-else :style="{ padding: '12px' }">
        <div
          :style="{
            borderRadius: '12px', overflow: 'hidden', width: '60%',
            border: '1px solid var(--line-2)',
          }"
        >
          <div
            :style="{
              width: '100%', aspectRatio: '3 / 4',
              background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--primary)', fontSize: '11px',
            }"
          >封面</div>
          <div :style="{ padding: '8px' }">
            <div
              :style="{
                fontSize: '12px', lineHeight: 1.4, fontWeight: 600,
                color: xhs.title ? 'var(--ink)' : '#bbb',
                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }"
            >{{ displayTitle }}</div>
            <div class="flex items-center" :style="{ gap: '6px', marginTop: '6px' }">
              <div
                :style="{
                  width: '16px', height: '16px', borderRadius: '999px',
                  background: 'var(--dark)', color: 'var(--primary)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '9px', fontWeight: 700,
                }"
              >{{ avatarLetter }}</div>
              <span :style="{ fontSize: '11px', color: 'var(--ink-2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ nickname }}</span>
              <span :style="{ fontSize: '11px', color: 'var(--ink-2)' }">♡ 1.2k</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend; npx vue-tsc -b`
Expected: 零类型错误。（若 emit 产物，按「前置」还原。）

- [ ] **Step 3: Commit**

```powershell
git add frontend/src/components/xhs/PhonePreview.vue
git commit -m "feat(xhs): 手机预览组件 PhonePreview (P0 T8)"
```

---

## Task 9: NoteEditor.vue（中栏编辑器）

**Files:**
- Create: `frontend/src/components/xhs/NoteEditor.vue`

标题 input（计数 + 超限红字）、正文 textarea（计数 + 接 `useCursorInsert` + 向 store 注册插入器）、话题 chips（输入 Enter 添加、× 删除）、复制按钮（标题/正文/全文）。工具条留一条占位（P1 填排版主题/emoji 快捷）。

- [ ] **Step 1: 创建组件**

Create `frontend/src/components/xhs/NoteEditor.vue`：

```vue
<script setup lang="ts">
/**
 * 中栏纯文本编辑器（设计稿 §4.1 中栏 / §4.2 内核）。
 * 标题 input + 正文 textarea + 话题 chips + 复制按钮。正文接 useCursorInsert
 * 并向 store 注册插入器，P1 素材面板即可往光标处插入。
 */
import { ref, onMounted, onUnmounted } from "vue";
import Icon from "@/components/ui/Icon.vue";
import { useXhs, TITLE_SOFT_LIMIT, BODY_SOFT_LIMIT } from "@/stores/xhs";
import { useCursorInsert } from "@/composables/useCursorInsert";

const xhs = useXhs();

const bodyRef = ref<HTMLTextAreaElement | null>(null);
const { insert } = useCursorInsert(bodyRef, (v) => xhs.setBody(v));

onMounted(() => xhs.registerInserter(insert));
onUnmounted(() => xhs.registerInserter(null));

// 话题输入
const topicInput = ref("");
function commitTopic() {
  const v = topicInput.value;
  if (!v.trim()) return;
  // 支持一次输入多个（空格 / 逗号分隔）
  for (const piece of v.split(/[\s,，]+/)) xhs.addTopic(piece);
  topicInput.value = "";
}

const labelStyle = {
  fontSize: "12px",
  color: "var(--ink-2)",
  marginBottom: "4px",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
} as const;

const inputBaseStyle = {
  width: "100%",
  border: "1px solid var(--line-2)",
  borderRadius: "10px",
  padding: "10px 12px",
  background: "#fff",
  color: "var(--ink)",
  fontSize: "14px",
  outline: "none",
  boxSizing: "border-box",
} as const;
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '14px' }">
    <!-- 工具条（P0 占位；P1 放排版主题快捷符号 + emoji 快捷） -->
    <div
      class="flex items-center"
      :style="{
        gap: '8px', padding: '8px 10px', borderRadius: '10px',
        background: 'rgba(var(--ink-rgb),0.03)', color: 'var(--ink-2)', fontSize: '12px',
      }"
    >
      <Icon name="wand" :size="14" />
      <span>排版工具栏将在 P1 上线（一键插入小标题符号 / 分割线 / emoji）</span>
    </div>

    <!-- 标题 -->
    <div>
      <div :style="labelStyle">
        <span>标题</span>
        <span :style="{ color: xhs.titleOver ? 'var(--red)' : 'var(--ink-2)' }">
          {{ xhs.titleCount }}/{{ TITLE_SOFT_LIMIT }}
        </span>
      </div>
      <input
        :value="xhs.title"
        type="text"
        placeholder="好标题决定打开率，建议 ≤ 20 字"
        :style="inputBaseStyle"
        @input="xhs.setTitle(($event.target as HTMLInputElement).value)"
      />
    </div>

    <!-- 正文 -->
    <div class="flex min-h-0 flex-1 flex-col">
      <div :style="labelStyle">
        <span>正文</span>
        <span :style="{ color: xhs.bodyOver ? 'var(--red)' : 'var(--ink-2)' }">
          {{ xhs.bodyCount }}/{{ BODY_SOFT_LIMIT }}
        </span>
      </div>
      <textarea
        ref="bodyRef"
        :value="xhs.body"
        placeholder="写下你的图文笔记正文～ 换行、emoji、#话题 都支持"
        :style="{ ...inputBaseStyle, flex: 1, minHeight: '160px', resize: 'none', lineHeight: 1.7, fontFamily: 'inherit' }"
        @input="xhs.setBody(($event.target as HTMLTextAreaElement).value)"
      />
    </div>

    <!-- 话题 -->
    <div>
      <div :style="labelStyle"><span>话题</span></div>
      <div class="flex flex-wrap items-center" :style="{ gap: '6px' }">
        <span
          v-for="(t, i) in xhs.topics"
          :key="i"
          class="flex items-center"
          :style="{
            gap: '4px', fontSize: '13px', color: '#3a6fb0',
            background: 'rgba(58,111,176,0.08)', borderRadius: '999px', padding: '3px 10px',
          }"
        >
          #{{ t }}
          <button
            type="button"
            :style="{ cursor: 'pointer', color: '#3a6fb0', display: 'flex', alignItems: 'center' }"
            title="移除"
            @click="xhs.removeTopic(i)"
          ><Icon name="x" :size="12" /></button>
        </span>
        <input
          v-model="topicInput"
          type="text"
          placeholder="加话题，回车确认"
          :style="{ flex: 1, minWidth: '120px', border: 'none', outline: 'none', background: 'transparent', fontSize: '13px', color: 'var(--ink)' }"
          @keydown.enter.prevent="commitTopic"
          @blur="commitTopic"
        />
      </div>
    </div>

    <!-- 复制按钮 -->
    <div class="flex items-center" :style="{ gap: '8px', borderTop: '1px solid var(--line-2)', paddingTop: '12px' }">
      <button type="button" class="xhs-copy-btn" @click="xhs.copy('title')">
        <Icon name="copy" :size="13" /> 复制标题
      </button>
      <button type="button" class="xhs-copy-btn" @click="xhs.copy('body')">
        <Icon name="copy" :size="13" /> 复制正文
      </button>
      <button
        type="button"
        class="xhs-copy-btn"
        :style="{ background: 'var(--primary)', color: '#fff', borderColor: 'var(--primary)' }"
        @click="xhs.copy('full')"
      >
        <Icon name="copy" :size="13" /> 复制全文
      </button>
      <span :style="{ marginLeft: 'auto', fontSize: '12px', color: 'var(--ink-2)' }">
        {{ xhs.saving ? '保存中…' : (xhs.draftId ? '已保存' : '未保存') }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.xhs-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid var(--line-2);
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-copy-btn:hover {
  filter: brightness(0.97);
}
</style>
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend; npx vue-tsc -b`
Expected: 零类型错误。

- [ ] **Step 3: Commit**

```powershell
git add frontend/src/components/xhs/NoteEditor.vue
git commit -m "feat(xhs): 中栏纯文本编辑器 NoteEditor (P0 T9)"
```

---

## Task 10: PanelRail.vue（左栏 9 面板骨架）

**Files:**
- Create: `frontend/src/components/xhs/PanelRail.vue`

左栏 = 窄图标 tab 列（9 项）+ 当前面板内容区。P0 面板内容全是占位（说明该面板将在哪个阶段上线），点击 tab 切 `store.activePanel`。

- [ ] **Step 1: 创建组件**

Create `frontend/src/components/xhs/PanelRail.vue`：

```vue
<script setup lang="ts">
/**
 * 左栏素材面板骨架（设计稿 §4.1 左 / §5 九面板）。
 * P0：9 个 tab 切换 + 占位内容。P1 起逐个面板填真实素材（JSON 驱动）。
 */
import Icon from "@/components/ui/Icon.vue";
import { useXhs, type XhsPanel } from "@/stores/xhs";

const xhs = useXhs();

interface PanelDef {
  key: XhsPanel;
  icon: string;
  label: string;
  /** 占位说明：该面板将在哪个阶段上线。 */
  stage: string;
}

// icon 全部复用 Icon.vue 现有图标，避免新增 9 个 SVG。
const PANELS: PanelDef[] = [
  { key: "template", icon: "library", label: "模版", stage: "P1" },
  { key: "theme", icon: "sliders", label: "主题", stage: "P1" },
  { key: "emoji", icon: "heart", label: "表情", stage: "P1" },
  { key: "title", icon: "edit", label: "标题", stage: "P1" },
  { key: "copy", icon: "doc", label: "文案", stage: "P1" },
  { key: "topic", icon: "tag", label: "话题", stage: "P1" },
  { key: "decoration", icon: "skills", label: "装饰", stage: "P1" },
  { key: "image", icon: "image", label: "图片", stage: "P2" },
  { key: "ai", icon: "spark", label: "AI", stage: "P3" },
];

function activeDef(): PanelDef {
  return PANELS.find((p) => p.key === xhs.activePanel) ?? PANELS[0];
}
</script>

<template>
  <div class="flex h-full" :style="{ gap: '0' }">
    <!-- 图标 tab 列 -->
    <div
      class="flex flex-col items-center"
      :style="{ width: '64px', gap: '4px', padding: '4px', borderRight: '1px solid var(--line-2)' }"
    >
      <button
        v-for="p in PANELS"
        :key="p.key"
        type="button"
        class="flex flex-col items-center justify-center"
        :title="p.label"
        :style="{
          width: '56px', padding: '8px 0', borderRadius: '10px', cursor: 'pointer',
          gap: '3px',
          background: xhs.activePanel === p.key ? 'rgba(var(--ink-rgb),0.06)' : 'transparent',
          color: xhs.activePanel === p.key ? 'var(--primary)' : 'var(--ink-2)',
        }"
        @click="xhs.setActivePanel(p.key)"
      >
        <Icon :name="p.icon" :size="18" />
        <span :style="{ fontSize: '11px' }">{{ p.label }}</span>
      </button>
    </div>

    <!-- 面板内容区（P0 占位） -->
    <div class="min-h-0 flex-1 overflow-y-auto" :style="{ padding: '16px' }">
      <div :style="{ fontSize: '14px', fontWeight: 600, color: 'var(--ink)', marginBottom: '10px' }">
        {{ activeDef().label }}
      </div>
      <div
        class="flex flex-col items-center justify-center"
        :style="{
          gap: '10px', textAlign: 'center', color: 'var(--ink-2)', fontSize: '13px',
          border: '1px dashed var(--line-2)', borderRadius: '12px', padding: '28px 16px',
        }"
      >
        <Icon :name="activeDef().icon" :size="26" />
        <div>「{{ activeDef().label }}」面板将在 {{ activeDef().stage }} 上线</div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend; npx vue-tsc -b`
Expected: 零类型错误。

- [ ] **Step 3: Commit**

```powershell
git add frontend/src/components/xhs/PanelRail.vue
git commit -m "feat(xhs): 左栏九面板骨架 PanelRail (P0 T10)"
```

---

## Task 11: XhsEditorView.vue（三栏视图 + 草稿管理）

**Files:**
- Modify: `frontend/src/views/XhsEditorView.vue`（整文件替换 Task 7 的占位）

顶部条：标题 + 草稿下拉（列表/切换/删除）+「新建」+ 保存状态。下方三栏：PanelRail | NoteEditor | PhonePreview。挂载时 `loadDrafts()`。

- [ ] **Step 1: 整文件替换占位视图**

把 `frontend/src/views/XhsEditorView.vue` 全文替换为：

```vue
<script setup lang="ts">
/**
 * 小红书图文笔记编辑器主视图（设计稿 §4.1 三栏）。
 *   ┌ 顶部：标题 · 草稿下拉 · 新建 · 保存状态
 *   ├ 左 PanelRail（素材，P0 占位） │ 中 NoteEditor │ 右 PhonePreview
 * 挂载即拉草稿列表；新建从空白开始（首次有内容时 store 自动建草稿）。
 */
import { onMounted, ref } from "vue";
import Icon from "@/components/ui/Icon.vue";
import PanelRail from "@/components/xhs/PanelRail.vue";
import NoteEditor from "@/components/xhs/NoteEditor.vue";
import PhonePreview from "@/components/xhs/PhonePreview.vue";
import { useXhs } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

const xhs = useXhs();
const draftMenuOpen = ref(false);

onMounted(() => {
  void xhs.loadDrafts();
});

async function openDraft(id: string) {
  draftMenuOpen.value = false;
  if (id === xhs.draftId) return;
  // 切换前先把当前未落盘的改动 flush 一次
  await xhs.saveNow();
  await xhs.loadDraft(id);
}

async function newDraft() {
  draftMenuOpen.value = false;
  await xhs.saveNow();
  xhs.newDraft();
}

async function removeDraft(id: string, ev: Event) {
  ev.stopPropagation();
  // confirmDialog 签名：confirmDialog(message, { title?, okLabel?, cancelLabel?, kind? })
  const ok = await confirmDialog("删除后无法恢复，确认删除这篇草稿吗？", {
    title: "删除草稿",
    okLabel: "删除",
    kind: "danger",
  });
  if (!ok) return;
  await xhs.deleteDraft(id);
}

function draftLabel(d: { title: string; updated_at: string }): string {
  return d.title.trim() || "（无标题）";
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '14px' }">
    <!-- 顶部条 -->
    <div class="flex items-center" :style="{ gap: '12px' }">
      <div :style="{ fontSize: '18px', fontWeight: 700, color: 'var(--ink)' }">小红书 · 图文笔记</div>

      <!-- 草稿下拉 -->
      <div class="relative" :style="{ marginLeft: 'auto' }">
        <button
          type="button"
          class="flex items-center"
          :style="{
            gap: '6px', fontSize: '13px', padding: '7px 12px', borderRadius: '8px',
            border: '1px solid var(--line-2)', background: '#fff', color: 'var(--ink)', cursor: 'pointer',
          }"
          @click="draftMenuOpen = !draftMenuOpen"
        >
          <Icon name="doc" :size="14" />
          我的草稿（{{ xhs.drafts.length }}）
          <Icon name="arrowDown" :size="13" />
        </button>
        <div
          v-if="draftMenuOpen"
          class="absolute"
          :style="{
            top: 'calc(100% + 6px)', right: '0', width: '260px', maxHeight: '320px', overflowY: 'auto',
            background: '#fff', border: '1px solid var(--line-2)', borderRadius: '12px',
            boxShadow: '0 12px 30px -10px rgba(var(--shadow-rgb),0.25)', zIndex: 40, padding: '6px',
          }"
        >
          <div v-if="!xhs.drafts.length" :style="{ padding: '16px', textAlign: 'center', color: 'var(--ink-2)', fontSize: '13px' }">
            还没有草稿，开始写第一篇吧～
          </div>
          <button
            v-for="d in xhs.drafts"
            :key="d.id"
            type="button"
            class="flex w-full items-center"
            :style="{
              gap: '8px', padding: '8px 10px', borderRadius: '8px', cursor: 'pointer', textAlign: 'left',
              background: d.id === xhs.draftId ? 'rgba(var(--ink-rgb),0.06)' : 'transparent',
            }"
            @click="openDraft(d.id)"
          >
            <span :style="{ flex: 1, fontSize: '13px', color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">
              {{ draftLabel(d) }}
            </span>
            <button
              type="button"
              :style="{ cursor: 'pointer', color: 'var(--ink-2)', display: 'flex', padding: '2px' }"
              title="删除"
              @click="removeDraft(d.id, $event)"
            ><Icon name="trash" :size="14" /></button>
          </button>
        </div>
      </div>

      <button
        type="button"
        class="flex items-center"
        :style="{
          gap: '6px', fontSize: '13px', padding: '7px 14px', borderRadius: '8px',
          background: 'var(--primary)', color: '#fff', cursor: 'pointer',
        }"
        @click="newDraft"
      >
        <Icon name="plus" :size="14" /> 新建
      </button>
    </div>

    <!-- 三栏 -->
    <div class="flex min-h-0 flex-1" :style="{ gap: '14px' }">
      <!-- 左：素材面板 -->
      <div
        :style="{
          width: '320px', flexShrink: 0, background: 'var(--bg-inner)',
          border: '1px solid var(--line-2)', borderRadius: '16px', overflow: 'hidden',
        }"
      >
        <PanelRail />
      </div>
      <!-- 中：编辑器 -->
      <div
        class="min-w-0 flex-1"
        :style="{ background: 'var(--bg-inner)', border: '1px solid var(--line-2)', borderRadius: '16px', padding: '16px', overflow: 'hidden' }"
      >
        <NoteEditor />
      </div>
      <!-- 右：手机预览 -->
      <div
        :style="{
          width: '340px', flexShrink: 0, background: 'var(--bg-inner)',
          border: '1px solid var(--line-2)', borderRadius: '16px', padding: '16px', overflow: 'hidden',
        }"
      >
        <PhonePreview />
      </div>
    </div>
  </div>
</template>
```

> `confirmDialog` 已按 `frontend/src/composables/useConfirm.ts` 的真实签名调用（`confirmDialog(message, { title?, okLabel?, cancelLabel?, kind? })`，导出为具名函数，`kind: "danger" | "info"`），无需再核对。

- [ ] **Step 2: 类型检查 + 构建**

Run: `cd frontend; npm run build`
Expected: 构建成功，零类型错误。

- [ ] **Step 3: Commit**

```powershell
git add frontend/src/views/XhsEditorView.vue
git commit -m "feat(xhs): 三栏主视图 XhsEditorView + 草稿管理 (P0 T11)"
```

---

## Task 12: 全量验证 + 手动验收

**Files:** 无（仅验证与收尾）

- [ ] **Step 1: 后端全量测试**

Run（已设前置 PYTHONPATH）:
```powershell
python -m pytest sidecar/tests/test_xhs_storage.py sidecar/tests/test_xhs_routes.py -v
```
Expected: 全绿。

- [ ] **Step 2: 后端无回归抽查**

Run: `python -m pytest sidecar/tests/test_health.py sidecar/tests/test_mining_comments_routes.py -v`
Expected: 全绿（确认新增 router/fixture 没破坏既有用例与 app 启动）。

- [ ] **Step 3: 前端单测全绿**

Run:
```powershell
cd frontend; npx vitest run src/utils/__tests__/xhsText.spec.ts src/composables/__tests__/useCursorInsert.spec.ts src/stores/__tests__/xhs.spec.ts
```
Expected: 三个 spec 全绿。

- [ ] **Step 4: 前端类型检查 + 构建门禁**

Run: `cd frontend; npm run build`
Expected: `vue-tsc -b` 零错零警告 + `vite build` 成功。若产生 emit 产物（vite.config.js / *.d.ts），按「前置」还原；`dist/` 不管。

- [ ] **Step 5: 手动验收（真实 app）**

> 启动方式见项目记忆「fresh 环境 tauri dev」：worktree 冷启动用 junction binaries + `CARGO_TARGET_DIR`=主仓 target + `npx tauri dev --no-watch`。**dev 服务由用户双击 .bat 启动**（agent 起的会被 sandbox 回收）。本步是给执行者/用户的验收清单，逐条勾：

  1. 左侧导航出现「小红书」图标（notebook），点击进入 `/xhs`，三栏正常渲染。
  2. 在标题输入「测试标题」、正文输入多行带 emoji 文本 → 右侧「笔记页」预览**实时**更新（标题/正文/换行/emoji 正常显示）。
  3. 话题输入框输入「考证 干货」回车 → 出现两个蓝色 #chip；× 可删；重复添加不重复。
  4. 切到右侧「发现页」tab → 瀑布流卡片显示标题两行截断 + 昵称。
  5. 字数：标题超 20 字 / 正文超 1000 字时计数变红（不拦截输入）。
  6. 点「复制全文」→ toast「已复制」→ 在记事本粘贴，得到 `标题\n\n正文\n\n#考证 #干货` 格式。
  7. 停顿约 1 秒（去抖 800ms）后，标题旁状态变「已保存」。
  8. 点「新建」→ 清空；点「我的草稿」下拉 → 列表里有刚才那篇，点击可载回内容。
  9. 刷新页面（或重进 `/xhs`）→「我的草稿」里草稿仍在，载入内容完整 → **持久化验证通过**。
  10. 草稿下拉里点删除 → 确认弹窗 → 删除后列表移除。

- [ ] **Step 6: 收尾 commit（如手动验收阶段有微调）**

```powershell
git add -A
git commit -m "chore(xhs): P0 手动验收微调"
```

> 若无微调则跳过。P0 完成后按项目约定走 PR 流程（push 分支 + gh pr create），不在本计划内。

---

## 自检（Self-Review）

**1. 设计稿 P0 覆盖核对**
- 路由 `/xhs` + 导航入口 → Task 7 ✅
- `useXhs`（当前草稿 + 列表 + 面板状态 + 预览 tab）→ Task 6 ✅
- 三栏骨架（9 标签 / 编辑区 / 预览）→ Task 10（左）+ Task 9（中）+ Task 8（右）+ Task 11（组装）✅
- 纯文本内核 + `insertAtCursor` 光标插入复位 → Task 5（内核）+ Task 6（store 入口）+ Task 9（接 textarea）✅
- 字数计数（标题 20 / 正文 1000，超限提示不拦截）→ Task 4（countChars）+ Task 6（getters）+ Task 9（红字）✅
- 草稿持久化（`xhs_drafts` + CRUD + 去抖自动保存）→ Task 1/2（表+CRUD）+ Task 3（路由）+ Task 6（autosave）✅
- 复制到剪贴板（标题/正文/全文）→ Task 4（buildFullText）+ Task 6（copy）+ Task 9（按钮）✅
- 预览两 tab 实时联动（占位图）→ Task 8 ✅
- 验收门禁（vue-tsc+build 零错 / sidecar 测试全过 / 不联网可完成）→ Task 12 ✅

**2. 占位符扫描**：各任务代码均为完整可执行内容，无 TODO/TBD/「类似上文」。唯一显式留给执行者核对的是 Task 11 的 `confirmDialog` 签名（已给出核对步骤与退化方案），不属占位。

**3. 类型/命名一致性核对**
- storage：`create_draft/get_draft/list_drafts/update_draft/delete_draft/_row_to_dict/init_db/get_conn/default_db_path/_ensure_initialized/_SCHEMA_VERSION/_DDL_V1/_db_path/_initialized/_local/_init_lock` —— Task 1/2 定义，Task 3 路由调用一致 ✅
- 路由请求模型字段（snake_case：`image_ids/cover_index/theme_id`）与 store `_payload()` 输出键一致 ✅
- store：`useXhs` 导出 + `TITLE_SOFT_LIMIT/BODY_SOFT_LIMIT` 常量 → Task 9 `import { useXhs, TITLE_SOFT_LIMIT, BODY_SOFT_LIMIT }` 一致；`XhsPanel` 类型 → Task 10 import 一致；getters/actions 名（fullText/titleCount/bodyCount/titleOver/bodyOver/isEmpty/loadDrafts/loadDraft/newDraft/saveNow/setTitle/setBody/addTopic/removeTopic/setActivePanel/setPreviewTab/registerInserter/insertAtCursor/copy/deleteDraft）在 Task 8/9/10/11 调用处全部对得上 ✅
- `spliceAtSelection/useCursorInsert`（Task 5）→ Task 9 `useCursorInsert(bodyRef, ...)` 用法一致 ✅
- `buildFullText/countChars`（Task 4）→ store getters import 一致 ✅
- Icon 名：Task 7 新增 `notebook`；Task 8/9/10/11 用到的 `wand/copy/x/plus/doc/arrowDown/trash/library/sliders/heart/edit/tag/skills/image/spark` 均为 Icon.vue 现有图标（已核对 PATHS 表）✅
