# 小红书编辑器 P4（自定义素材 + AI prompt 设置 + 预览 chip + 打磨）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给小红书编辑器补齐「用户自定义素材库（模版/文案/话题分组）+ AI prompt 可在设置里自定义 + 预览把 `[害羞R]` 类代码渲染成占位 chip + 一组打磨（isEmpty 纳入 topics / 字数超限提示 / 有序列表按块重计数 / 草稿重命名与复制副本）」。

**Architecture:** 三轨并列、互不阻塞。
- **A 自定义素材**：新增 `xhs_custom_assets` 表（设计稿 §3.4：`id/kind/payload_json/created_at`，`kind ∈ {template,copy,topic_group}`），DAO 直挂现有 `routes/xhs.py`（无 service 层，与 draft CRUD 同构），新建 `xhsAssets.ts`（setup store，仿 `templates.ts`），三个素材面板加「我的」分组 + 录入入口。
- **B AI prompt 设置**：`AppConfig` 加 `xhs_generate_prompt`/`xhs_polish_prompt`（空串=用内置默认），`xhs_ai_service` 接 `config_service.load()`，新增 `GET/PATCH /api/xhs/ai_prompts`（仿 `mining_ai_prompts`），新建 `XhsPromptsCard.vue` 注册进设置页。
- **C 预览 chip + 打磨**：纯函数 `xhsCodes.ts` 把正文切成 文本/代码 段，`PhonePreview` 把代码段渲染成小药丸（**不是贴纸图**，§6）；`isEmpty` 纳入 topics、字数超限文字提示、有序列表按「列表块」重计数（新增光标探针）、草稿重命名 + 复制副本（后端 `duplicate` 路由 + `copy_images`）。

**Tech Stack:** Python 3.12 + FastAPI（sidecar）、SQLite（独立 `xhs.db`）、pytest；Vue 3.5 + Pinia（options + setup 两种 store）+ TypeScript + Tailwind 3、Vitest + @vue/test-utils、vue-tsc + Vite。

---

## 背景与既有模式（实现前必读）

**关键边界（来自设计稿 §1/§6，别破）：**
- `[害羞R]` 类小红书官方贴纸：**只支持文字代码插入**，预览里渲染为「代码占位 chip（小药丸，显示去掉 `[]R` 的标签文字）」，**不打包/不渲染任何官方贴纸图片**（版权 / ToS）。§6 提到的「用户自备贴纸图点亮」是扩展位、默认不附带 —— **本计划不实现图片渲染**（YAGNI）。
- 自定义素材只在本机 `xhs.db`，与起步 JSON **合并显示**，custom 标「我的」分组。不爬任何站点。
- **emoji 字体一致性（§6）= 评估项**。本计划的决定：**不打包 Twemoji/Noto**。编辑器与预览同在 WebView2，统一用 Win11 自带 Segoe UI Emoji 彩色字形，二者表现一致；无证据表明目标 Win11 平台缺字。打包字体 = +数 MB 体积 + 复杂度，不划算。若将来用户实测「豆腐块」再单独评估。**此项无代码任务，仅此决定记录在案。**
- 自定义素材 MVP = 增 / 列 / 删（编辑 = 删后重建）。不做搜索/标签/分页（mining 模板那套 search/tags/bulk-import 不照搬，YAGNI）。
- 复制副本 = 复制 标题（加「（副本）」）/正文/话题/封面下标/主题 + **复制图片文件到新草稿目录**（新 image_id）。

**既有模式（直接复用，勿重造）：**
- **存储**：`csm_core/xhs/storage.py` 用懒初始化（`_ensure_initialized()` 首次 `get_conn()` 建库）+ 单一 `_DDL_V1` 列表（全 `CREATE TABLE/INDEX IF NOT EXISTS`，幂等）+ `_SCHEMA_VERSION`。**加表 = 往 `_DDL_V1` 追加 SQL + bump 版本号**，老用户 `xhs.db` 下次启动自动补建。主键用 `uuid.uuid4().hex` 字符串（与 `xhs_drafts` 一致，**不用 AUTOINCREMENT**）。出口 `_row_to_dict` 把 `*_json` 列 `json.loads` 成数组/对象。
- **路由**：`sidecar/csm_sidecar/routes/xhs.py` 的 `router = APIRouter(tags=["xhs"], dependencies=[RequireToken])` —— 整个 router 已挂 token 鉴权，新增端点自动受保护。404 用 `raise HTTPException(status_code=404, ...)`；204 直接 `return None` 配 `status_code=204`。已注册进 `main.py`，**不改 main.py**。
- **配置**：`csm_core/config.py` 的 `AppConfig(BaseModel)`，prompt 字段默认空串=用内置默认；`config_service.patch(updates)` 深合并 + 校验 + 落盘；`config_service.load()` 读全量。`GET/PATCH /api/xhs/ai_prompts` 仿 `routes/mining.py` 的 `mining_ai_prompts` 段（约 399–453 行）。
- **AI service**：`xhs_ai_service.py` 已有 `DEFAULT_GENERATE_SYSTEM`/`DEFAULT_POLISH_SYSTEM` 常量、`generate_note(intent)`/`polish_note(text)`。P4 在取 prompt 处接 `config_service.load()`，仿 `mining_ai_service.py` 的 `_resolve_prompt` 思路（xhs 是单段 system，无 `---user---` 拆分，比 mining 更简单）。
- **前端只读素材**：`frontend/src/data/xhs/assets.ts` 导出 `TEMPLATES`/`COPY_GROUPS`/`TOPIC_GROUPS` + 类型 `XhsTemplate`/`ItemGroup`/`TopicGroup`。自定义素材**追加**到这些之外，不替换。
- **插入机制**：store `insertAtCursor(text)` → NoteEditor 注册的 `_inserter` 把文本插到光标处（`xhs.ts:258-269`）。面板点击素材即调它。
- **设置卡范式**：`frontend/src/components/settings/MiningPromptsCard.vue`（自洽，用 `useSidecar().client` 直连 `/api/<module>/ai_prompts`，三态 `draft/baseline/default` + dirty/isDefault；不走 `useConfig`）。设置页注册点：`frontend/src/views/SettingsView.vue` 的 `section === 'models'` 块末尾、`<MiningPromptsCard />` 之后。
- **管理 UI 避坑**：删除确认**必须用 `confirmDialog`（`@/composables/useConfirm`），禁用 `window.confirm`**（Tauri 2 抛 "Command not found"）。toast 用 `useToast()`。

**测试命令（house style，照 P3）：**
- 后端（工作目录 = worktree 根）：
  ```powershell
  $env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
  & "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/<file> -v
  ```
  全量：`& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests -q`
- 前端（工作目录 = `frontend/`）：
  ```powershell
  npx vitest run src/<相对路径>      # 单文件
  npx vitest run                       # 全量
  npx vue-tsc -b ; npx vite build      # 类型检查 + 构建
  ```
  ⚠️ `vue-tsc -b` 可能 emit `vite.config.js` / `*.d.ts` 产物 → 跑完 `git status` 检查，有则 `git checkout -- <产物>` 还原。
- 前端单测约定：`vi.mock("@/stores/sidecar", ...)`、`vi.mock("@/composables/useConfirm", () => ({ confirmDialog: vi.fn().mockResolvedValue(true) }))`、稳定 spy 用 `vi.hoisted`。

**Commit：** 每个 Task 一个 commit，conventional-commit 中文体，前缀 `feat(xhs):` / `fix(xhs):`，结尾带 ` (P4 T<N>)`。真实 commit 必须带全局要求的 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` 尾注（下文 commit 片段为简洁省略，执行时务必加）。

---

## 文件清单

### 新建
- `frontend/src/utils/xhsCodes.ts` —— `[xxxR]` 代码 tokenizer（纯函数）。
- `frontend/src/utils/__tests__/xhsCodes.spec.ts`
- `frontend/src/stores/xhsAssets.ts` —— 自定义素材 setup store。
- `frontend/src/stores/__tests__/xhsAssets.spec.ts`
- `frontend/src/components/settings/XhsPromptsCard.vue` —— 小红书 AI 提示词设置卡。
- `sidecar/tests/test_xhs_custom_assets.py` —— 自定义素材 DAO + 路由测试。
- `sidecar/tests/test_xhs_ai_prompts_routes.py` —— ai_prompts GET/PATCH 测试。

### 修改
- `csm_core/xhs/storage.py` —— 追加 `xhs_custom_assets` 表 + 索引到 `_DDL_V1`，bump `_SCHEMA_VERSION = 2`，加 DAO（`create_custom_asset`/`list_custom_assets`/`delete_custom_asset`/`_row_to_asset_dict`），加 `copy`/duplicate 不在此（图片在 service）。
- `csm_core/config.py` —— `AppConfig` 加 `xhs_generate_prompt`/`xhs_polish_prompt`。
- `sidecar/csm_sidecar/routes/xhs.py` —— 加自定义素材 5 端点 + `ai_prompts` GET/PATCH + `drafts/{id}/duplicate`；加 import（`config_service`）。
- `sidecar/csm_sidecar/services/xhs_ai_service.py` —— 接 `config_service` 解析自定义/默认 prompt。
- `sidecar/csm_sidecar/services/xhs_images_service.py` —— 加 `copy_images(src, dst, ids)`。
- `frontend/src/utils/xhsTheme.ts` —— 加 `nextOrderedNumber(textBeforeCursor, style)`。
- `frontend/src/stores/xhs.ts` —— `isEmpty` 纳入 topics；加 `_cursorProbe` + `registerCursorProbe`；`insertOrdered` 走探针按块计数；加 `renameDraft`/`duplicateDraft`。
- `frontend/src/components/xhs/NoteEditor.vue` —— 注册光标探针；字数超限文字提示。
- `frontend/src/components/xhs/PhonePreview.vue` —— 正文按 `tokenizeXhsCodes` 分段渲染，代码段成 chip。
- `frontend/src/components/xhs/panels/TemplatePanel.vue` —— 加「我的」分类 +「存为我的模版」。
- `frontend/src/components/xhs/panels/CopyPanel.vue` —— 加「我的」分组 +「添加自定义文案」。
- `frontend/src/components/xhs/panels/TopicPanel.vue` —— 加「我的」话题分组 +「存为话题分组」+「全部添加」。
- `frontend/src/views/SettingsView.vue` —— 注册 `XhsPromptsCard`。
- `frontend/src/views/XhsEditorView.vue` —— 草稿下拉加「重命名」(行内) +「复制副本」。
- 各被改文件对应的 `__tests__` / `test_*` 增量。

### 不动
- `sidecar/csm-sidecar.spec` —— **无新模块**（storage/routes/config 既有，已被 import 图收集；`config_service` 已收集）。确认不改。
- `sidecar/csm_sidecar/main.py`、`lifespan.py` —— 路由已注册、xhs 懒初始化不接 lifespan。
- `frontend/src/stores/config.ts`、`api/client.ts` —— prompt 卡自洽走 `/api/xhs/ai_prompts`，不经 `useConfig`。
- `frontend/src/data/xhs/*.json`、`assets.ts` —— 起步素材不变（自定义是叠加）。

---

# Track A — 自定义素材（T1–T6）

## Task 1: 后端 `xhs_custom_assets` 表 + DAO（TDD）

**Files:**
- Modify: `csm_core/xhs/storage.py`（`_SCHEMA_VERSION`、`_DDL_V1`、新增 DAO）
- Test: `sidecar/tests/test_xhs_custom_assets.py`（本任务先写 DAO 部分）

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_xhs_custom_assets.py`：

```python
"""xhs_custom_assets DAO（Task 1）+ 路由（Task 2）测试。"""
from __future__ import annotations

import pytest

from csm_core.xhs import storage


@pytest.fixture()
def db(tmp_path):
    storage.init_db(tmp_path / "xhs.db")
    yield storage
    # 每个测试独立库；init_db 重置线程连接由 storage 内部处理。


def test_create_and_list_custom_asset(db):
    asset = db.create_custom_asset(kind="copy", payload={"text": "今天也要元气满满"})
    assert asset["id"]
    assert asset["kind"] == "copy"
    assert asset["payload"] == {"text": "今天也要元气满满"}
    assert asset["created_at"]

    rows = db.list_custom_assets()
    assert len(rows) == 1
    assert rows[0]["id"] == asset["id"]


def test_list_filters_by_kind(db):
    db.create_custom_asset(kind="copy", payload={"text": "a"})
    db.create_custom_asset(kind="template", payload={"name": "n", "title": "t", "body": "b", "topics": []})
    assert len(db.list_custom_assets(kind="copy")) == 1
    assert len(db.list_custom_assets(kind="template")) == 1
    assert len(db.list_custom_assets()) == 2


def test_payload_roundtrips_complex_shape(db):
    payload = {"name": "我的话题", "tags": ["秋冬穿搭", "通勤", "显瘦"]}
    a = db.create_custom_asset(kind="topic_group", payload=payload)
    got = db.list_custom_assets(kind="topic_group")[0]
    assert got["payload"] == payload
    assert a["payload"]["tags"][0] == "秋冬穿搭"


def test_delete_custom_asset(db):
    a = db.create_custom_asset(kind="copy", payload={"text": "x"})
    assert db.delete_custom_asset(a["id"]) is True
    assert db.list_custom_assets() == []
    assert db.delete_custom_asset(a["id"]) is False  # 已不存在


def test_list_order_newest_first(db):
    a = db.create_custom_asset(kind="copy", payload={"text": "first"})
    b = db.create_custom_asset(kind="copy", payload={"text": "second"})
    rows = db.list_custom_assets(kind="copy")
    # created_at DESC, id DESC —— 后建的在前
    assert rows[0]["id"] == b["id"]
    assert rows[1]["id"] == a["id"]
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_custom_assets.py -v
```
Expected: FAIL（`AttributeError: module 'csm_core.xhs.storage' has no attribute 'create_custom_asset'`）

- [ ] **Step 3: 实现 storage**

在 `csm_core/xhs/storage.py` 顶部确保 `import json`、`import uuid` 已存在（draft CRUD 已用到，通常已 import；若缺则补）。

把 `_SCHEMA_VERSION` 从 `1` 改成 `2`：

```python
_SCHEMA_VERSION = 2
```

在 `_DDL_V1` 列表**末尾**（`xhs_drafts` 之后）追加两条 DDL：

```python
    """
    CREATE TABLE IF NOT EXISTS xhs_custom_assets (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_xhs_assets_kind ON xhs_custom_assets(kind, created_at DESC)",
```

在文件末尾（draft DAO 之后）加 DAO：

```python
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
    conn.commit()
    row = conn.execute(
        "SELECT * FROM xhs_custom_assets WHERE id = ?", (asset_id,)
    ).fetchone()
    return _row_to_asset_dict(row)


def list_custom_assets(kind: str | None = None) -> list[dict[str, Any]]:
    """列自定义素材，按 created_at DESC, id DESC（后建的在前）。kind 给定则只列该类。"""
    conn = get_conn()
    if kind is None:
        rows = conn.execute(
            "SELECT * FROM xhs_custom_assets ORDER BY created_at DESC, id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM xhs_custom_assets WHERE kind = ? ORDER BY created_at DESC, id DESC",
            (kind,),
        ).fetchall()
    return [_row_to_asset_dict(r) for r in rows]


def delete_custom_asset(asset_id: str) -> bool:
    """删一条，返回是否真的删到。"""
    conn = get_conn()
    cur = conn.execute("DELETE FROM xhs_custom_assets WHERE id = ?", (asset_id,))
    conn.commit()
    return cur.rowcount > 0
```

> 注：`Any` / `sqlite3` 已在文件顶部 import（draft DAO 用到）。若 `list_custom_assets` 的「后建在前」因同毫秒 `created_at` 撞而不稳，`ORDER BY created_at DESC, id DESC` 里 `id` 是随机 uuid 无法兜时序 —— 实测 `strftime('%f')` 含毫秒，单测两次插入间隔足够区分；若 CI 偶发，改 DDL 增 `seq INTEGER`（暂不需要）。

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_custom_assets.py -v
```
Expected: PASS（5 个 DAO 测试）

- [ ] **Step 5: Commit**

```bash
git add csm_core/xhs/storage.py sidecar/tests/test_xhs_custom_assets.py
git commit -m "feat(xhs): xhs_custom_assets 表 + DAO（增/列/删/payload JSON）(P4 T1)"
```

---

## Task 2: 后端自定义素材路由（TDD）

**Files:**
- Modify: `sidecar/csm_sidecar/routes/xhs.py`（加 `_ASSET_KINDS`、`CustomAssetCreate`、5 端点）
- Test: `sidecar/tests/test_xhs_custom_assets.py`（追加路由测试）

- [ ] **Step 1: 写失败测试**

在 `sidecar/tests/test_xhs_custom_assets.py` 顶部补 import 与 client fixture（**沿用本仓已有的 xhs 路由测试夹具风格** —— 打开 `sidecar/tests/test_xhs_ai_routes.py` 抄它构造 `TestClient` + 鉴权 token + `storage.init_db(tmp)` 的方式；下面的 fixture 是参考形态，实现时对齐既有 conftest）：

```python
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 对齐 test_xhs_ai_routes.py：init xhs db 到 tmp、构造 app、带上 RequireToken 需要的鉴权头。
    storage.init_db(tmp_path / "xhs.db")
    from csm_sidecar.main import create_app  # 若工厂名不同，按既有测试改
    app = create_app()
    c = TestClient(app)
    # RequireToken：抄 test_xhs_ai_routes.py 如何注入 token（header 或 dependency override）
    return c


def test_post_and_get_custom_assets(client):
    r = client.post("/api/xhs/custom-assets", json={"kind": "copy", "payload": {"text": "元气满满"}})
    assert r.status_code == 201
    asset = r.json()["asset"]
    assert asset["kind"] == "copy"

    r2 = client.get("/api/xhs/custom-assets", params={"kind": "copy"})
    assert r2.status_code == 200
    assert len(r2.json()["assets"]) == 1


def test_post_rejects_bad_kind(client):
    r = client.post("/api/xhs/custom-assets", json={"kind": "evil", "payload": {"text": "x"}})
    assert r.status_code == 400


def test_post_rejects_empty_payload(client):
    r = client.post("/api/xhs/custom-assets", json={"kind": "copy", "payload": {}})
    assert r.status_code == 400


def test_get_rejects_bad_kind(client):
    assert client.get("/api/xhs/custom-assets", params={"kind": "evil"}).status_code == 400


def test_delete_custom_asset_route(client):
    aid = client.post("/api/xhs/custom-assets", json={"kind": "copy", "payload": {"text": "x"}}).json()["asset"]["id"]
    assert client.delete(f"/api/xhs/custom-assets/{aid}").status_code == 204
    assert client.delete(f"/api/xhs/custom-assets/{aid}").status_code == 404
```

> 鉴权细节务必照 `test_xhs_ai_routes.py`：该文件已跑通 `RequireToken`，直接复用其 token 注入方式，避免每个请求 401。

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_custom_assets.py -v
```
Expected: FAIL（404 / 405：端点未定义）

- [ ] **Step 3: 实现路由**

在 `sidecar/csm_sidecar/routes/xhs.py`，确保顶部有 `from typing import Any` 与 `from pydantic import BaseModel, Field`（draft 模型已用）。`from ..storage`/`xhs_storage` 的引用名按文件现状（draft CRUD 调的是哪个别名就用哪个；下文用 `xhs_storage` 占位，对齐实际 import）。

加常量与模型（放在 draft 模型附近）：

```python
_ASSET_KINDS = {"template", "copy", "topic_group"}


class CustomAssetCreate(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
```

加 5 端点（放在 draft 路由之后、AI 路由之前任意处）：

```python
@router.get("/api/xhs/custom-assets")
def list_custom_assets(kind: str | None = None) -> dict[str, Any]:
    if kind is not None and kind not in _ASSET_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")
    return {"assets": xhs_storage.list_custom_assets(kind=kind)}


@router.post("/api/xhs/custom-assets", status_code=201)
def create_custom_asset(body: CustomAssetCreate) -> dict[str, Any]:
    if body.kind not in _ASSET_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")
    if not body.payload:
        raise HTTPException(status_code=400, detail="empty payload")
    asset = xhs_storage.create_custom_asset(kind=body.kind, payload=body.payload)
    return {"asset": asset}


@router.delete("/api/xhs/custom-assets/{asset_id}", status_code=204)
def delete_custom_asset(asset_id: str) -> None:
    if not xhs_storage.delete_custom_asset(asset_id):
        raise HTTPException(status_code=404, detail="not found")
    return None
```

> 只 3 个路由函数即覆盖测试的 GET/POST/DELETE（设计 §3.4 的「增/列/删」MVP）。`HTTPException` 已在文件顶部 import（draft 404 用到）。

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_custom_assets.py -v
```
Expected: PASS（5 DAO + 5 路由 = 10 个）

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/xhs.py sidecar/tests/test_xhs_custom_assets.py
git commit -m "feat(xhs): 自定义素材路由 GET/POST/DELETE /api/xhs/custom-assets (P4 T2)"
```

---

## Task 3: 前端 `xhsAssets` store（TDD）

**Files:**
- Create: `frontend/src/stores/xhsAssets.ts`
- Test: `frontend/src/stores/__tests__/xhsAssets.spec.ts`

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/stores/__tests__/xhsAssets.spec.ts`：

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const mockClient = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
};
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: mockClient }),
}));

import { useXhsAssets } from "@/stores/xhsAssets";

beforeEach(() => {
  setActivePinia(createPinia());
  mockClient.get.mockReset();
  mockClient.post.mockReset();
  mockClient.delete.mockReset();
});

describe("xhsAssets store", () => {
  it("ensureLoaded 拉全量并按 kind 分流 getter", async () => {
    mockClient.get.mockResolvedValue({
      data: {
        assets: [
          { id: "1", kind: "copy", payload: { text: "a" }, created_at: "t1" },
          { id: "2", kind: "template", payload: { name: "n", title: "t", body: "b", topics: [] }, created_at: "t2" },
          { id: "3", kind: "topic_group", payload: { name: "g", tags: ["x"] }, created_at: "t3" },
        ],
      },
    });
    const s = useXhsAssets();
    await s.ensureLoaded();
    expect(s.copies.length).toBe(1);
    expect(s.templates.length).toBe(1);
    expect(s.topicGroups.length).toBe(1);
    // 二次调用不重复请求
    await s.ensureLoaded();
    expect(mockClient.get).toHaveBeenCalledTimes(1);
  });

  it("create 把新素材推进列表", async () => {
    mockClient.get.mockResolvedValue({ data: { assets: [] } });
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "9", kind: "copy", payload: { text: "new" }, created_at: "t" } },
    });
    const s = useXhsAssets();
    await s.ensureLoaded();
    const a = await s.create("copy", { text: "new" });
    expect(a.id).toBe("9");
    expect(s.copies.length).toBe(1);
    expect(mockClient.post).toHaveBeenCalledWith("/api/xhs/custom-assets", { kind: "copy", payload: { text: "new" } });
  });

  it("remove 调 DELETE 并从列表剔除", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "1", kind: "copy", payload: { text: "a" }, created_at: "t" }] },
    });
    mockClient.delete.mockResolvedValue({});
    const s = useXhsAssets();
    await s.ensureLoaded();
    await s.remove("1");
    expect(mockClient.delete).toHaveBeenCalledWith("/api/xhs/custom-assets/1");
    expect(s.copies.length).toBe(0);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/xhsAssets.spec.ts`（工作目录 `frontend/`）
Expected: FAIL（`Cannot find module '@/stores/xhsAssets'`）

- [ ] **Step 3: 实现 store**

新建 `frontend/src/stores/xhsAssets.ts`：

```typescript
/**
 * 小红书自定义素材 store（设计稿 §3.4）。kind ∈ template|copy|topic_group，
 * 与起步 JSON 合并显示、标「我的」分组。setup-store 写法（仿 templates.ts），
 * 与承载草稿的 options-store useXhs 解耦。
 */
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { useSidecar } from "./sidecar";

export type XhsAssetKind = "template" | "copy" | "topic_group";

export interface XhsCustomAsset {
  id: string;
  kind: XhsAssetKind;
  // payload 形状随 kind 变（template:{name,title,body,topics} / copy:{text} / topic_group:{name,tags}）
  payload: Record<string, any>;
  created_at: string;
}

export const useXhsAssets = defineStore("xhsAssets", () => {
  const assets = ref<XhsCustomAsset[]>([]);
  const loaded = ref(false);

  const templates = computed(() => assets.value.filter((a) => a.kind === "template"));
  const copies = computed(() => assets.value.filter((a) => a.kind === "copy"));
  const topicGroups = computed(() => assets.value.filter((a) => a.kind === "topic_group"));

  async function reload(): Promise<void> {
    const r = await useSidecar().client.get("/api/xhs/custom-assets");
    assets.value = r.data.assets ?? [];
    loaded.value = true;
  }

  /** 首次加载（已加载则跳过）。面板挂载时调用。 */
  async function ensureLoaded(): Promise<void> {
    if (loaded.value) return;
    await reload();
  }

  async function create(kind: XhsAssetKind, payload: Record<string, any>): Promise<XhsCustomAsset> {
    const r = await useSidecar().client.post("/api/xhs/custom-assets", { kind, payload });
    const asset = r.data.asset as XhsCustomAsset;
    assets.value.unshift(asset); // 后端按 created_at DESC，新的在前
    return asset;
  }

  async function remove(id: string): Promise<void> {
    await useSidecar().client.delete(`/api/xhs/custom-assets/${id}`);
    assets.value = assets.value.filter((a) => a.id !== id);
  }

  return { assets, loaded, templates, copies, topicGroups, ensureLoaded, reload, create, remove };
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/xhsAssets.spec.ts`
Expected: PASS（3 个）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/xhsAssets.ts frontend/src/stores/__tests__/xhsAssets.spec.ts
git commit -m "feat(xhs): xhsAssets store（自定义素材增/列/删 + kind 分流）(P4 T3)"
```

---

## Task 4: 模版面板「我的」+「存为我的模版」

**Files:**
- Modify: `frontend/src/components/xhs/panels/TemplatePanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`（若不存在则新建）

> 先 `Read` 当前 `TemplatePanel.vue`。它读 `TEMPLATES` + `TEMPLATE_CATEGORIES`，点击走 `xhs.applyTemplate(...)`（非空先 `confirmDialog`）。本任务在分类条里增一个「我的」分类，选中时列出 `xhsAssets.templates`；顶部加「＋ 存为我的模版」。

- [ ] **Step 1: 写失败测试**

新建/补 `frontend/src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`（mock confirm 自动确认）：

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

const mockClient = { get: vi.fn(), post: vi.fn(), delete: vi.fn() };
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: mockClient }) }));
vi.mock("@/composables/useConfirm", () => ({ confirmDialog: vi.fn().mockResolvedValue(true) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

import TemplatePanel from "@/components/xhs/panels/TemplatePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  mockClient.get.mockResolvedValue({ data: { assets: [] } });
  mockClient.post.mockReset();
  mockClient.delete.mockReset();
});

describe("TemplatePanel 我的模版", () => {
  it("点「存为我的模版」用当前标题/正文 create(template)", async () => {
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "1", kind: "template", payload: { name: "我的标题", title: "我的标题", body: "正文", topics: [] }, created_at: "t" } },
    });
    const store = useXhs();
    store.$patch({ title: "我的标题", body: "正文" });
    const w = mount(TemplatePanel);
    await flushPromises();
    await w.find(".xhs-save-template").trigger("click");
    await flushPromises();
    expect(mockClient.post).toHaveBeenCalledTimes(1);
    const [, body] = mockClient.post.mock.calls[0];
    expect(body.kind).toBe("template");
    expect(body.payload.title).toBe("我的标题");
    w.unmount();
  });

  it("内容为空时不创建（提示先写内容）", async () => {
    const store = useXhs();
    void store;
    const w = mount(TemplatePanel);
    await flushPromises();
    await w.find(".xhs-save-template").trigger("click");
    await flushPromises();
    expect(mockClient.post).not.toHaveBeenCalled();
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`
Expected: FAIL（找不到 `.xhs-save-template`）

- [ ] **Step 3: 实现**

在 `TemplatePanel.vue` `<script setup>` 增（保留原有 import / 逻辑）：

```typescript
import { onMounted } from "vue";
import { useXhsAssets } from "@/stores/xhsAssets";
import { useToast } from "@/composables/useToast";

const assets = useXhsAssets();
const toast = useToast();
onMounted(() => { void assets.ensureLoaded(); });

const MINE = "__mine__";

function saveAsTemplate() {
  const title = xhs.title.trim();
  const body = xhs.body.trim();
  if (!title && !body) {
    toast.error("先写点标题或正文再存为模版");
    return;
  }
  void assets.create("template", {
    name: title || "我的模版",
    title: xhs.title,
    body: xhs.body,
    topics: [...xhs.topics],
  }).then(() => toast.success("已存为我的模版")).catch(() => toast.error("保存失败"));
}

async function removeMine(id: string) {
  await assets.remove(id);
}
```

把「我的」并进分类条 —— 原 `tabs`（来自 `TEMPLATE_CATEGORIES`）后追加 `{ key: MINE, name: "我的" }`；当选中分类 === `MINE` 时，列表数据源切到 `assets.templates`（把每条 `payload` 当模版用）。`<template>` 里：

1. 顶部加保存按钮：
```html
<button type="button" class="xhs-save-template" @click="saveAsTemplate">
  ＋ 存为我的模版
</button>
```
2. 列表区按当前分类：选中「我的」时渲染 `assets.templates`，每行点击 `applyTemplate({ title: a.payload.title, body: a.payload.body, topics: a.payload.topics })`（沿用原有「非空先 confirmDialog」逻辑），行尾带删除：
```html
<template v-if="grp === MINE">
  <div v-if="!assets.templates.length" class="xhs-empty">还没有自定义模版，写好一篇点「存为我的模版」</div>
  <div v-for="a in assets.templates" :key="a.id" class="xhs-mine-row">
    <button type="button" class="xhs-mine-main" @click="applyMine(a)">{{ a.payload.name || a.payload.title || '（未命名）' }}</button>
    <button type="button" class="xhs-mine-del" title="删除" @click="removeMine(a.id)">✕</button>
  </div>
</template>
```
（`applyMine` 包装：复用原模版点击的确认逻辑；若原文件把点击逻辑写成内联，抽成 `applyMine(a.payload)`。）

3. `<style scoped>` 补 `.xhs-save-template`（小主色按钮）、`.xhs-empty`（灰提示）、`.xhs-mine-row/.xhs-mine-main/.xhs-mine-del`（行 + hover 删除），配色用 `var(--primary)`/`var(--line-2)`/`var(--ink-2)`，与现有 `.xhs-row` 同语言。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`
Expected: PASS（2 个）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/xhs/panels/TemplatePanel.vue frontend/src/components/xhs/panels/__tests__/TemplatePanel.spec.ts
git commit -m "feat(xhs): 模版面板「我的」分类 +「存为我的模版」(P4 T4)"
```

---

## Task 5: 文案面板「我的」+「添加自定义文案」

**Files:**
- Modify: `frontend/src/components/xhs/panels/CopyPanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/CopyPanel.spec.ts`（新建）

> 当前 `CopyPanel.vue` 已读：`CategoryTabs` + `COPY_GROUPS` + `insertAtCursor`。本任务在分类条加「我的」，选中时列 `xhsAssets.copies`；顶部加输入框 +「添加」。

- [ ] **Step 1: 写失败测试**

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

const mockClient = { get: vi.fn(), post: vi.fn(), delete: vi.fn() };
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: mockClient }) }));

import CopyPanel from "@/components/xhs/panels/CopyPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  mockClient.get.mockResolvedValue({ data: { assets: [] } });
  mockClient.post.mockReset();
});

describe("CopyPanel 我的文案", () => {
  it("输入后点「添加」create(copy) 并清空输入", async () => {
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "1", kind: "copy", payload: { text: "自定义一句" }, created_at: "t" } },
    });
    const w = mount(CopyPanel);
    await flushPromises();
    // 切到「我的」分组
    await w.find(".xhs-copy-mine-tab").trigger("click");
    const input = w.find("input.xhs-copy-add-input");
    await input.setValue("自定义一句");
    await w.find(".xhs-copy-add-btn").trigger("click");
    await flushPromises();
    expect(mockClient.post).toHaveBeenCalledWith("/api/xhs/custom-assets", { kind: "copy", payload: { text: "自定义一句" } });
    expect((input.element as HTMLInputElement).value).toBe("");
    w.unmount();
  });

  it("点我的文案条插入正文光标处", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "1", kind: "copy", payload: { text: "插我" }, created_at: "t" }] },
    });
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(CopyPanel);
    await flushPromises();
    await w.find(".xhs-copy-mine-tab").trigger("click");
    await w.find(".xhs-mine-main").trigger("click");
    expect(spy).toHaveBeenCalledWith("插我");
    w.unmount();
  });
});
```

> 若用 `.xhs-copy-mine-tab` 不便，可让「我的」作为 `CategoryTabs` 的一个普通 tab，测试改为点该 tab 文本。实现与测试 selector 对齐即可。

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/CopyPanel.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

`CopyPanel.vue` 改为（在原结构上增「我的」）：

```vue
<script setup lang="ts">
/** 文案面板（设计稿 §5「文案」）。分组 tab + 文案片段；点击插入正文光标处。P4 增「我的」自定义文案。 */
import { ref, computed, onMounted } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { COPY_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";
import { useXhsAssets } from "@/stores/xhsAssets";

const xhs = useXhs();
const assets = useXhsAssets();
onMounted(() => { void assets.ensureLoaded(); });

const MINE = "__mine__";
const grp = ref(COPY_GROUPS[0]?.key ?? "");
const tabs = [...COPY_GROUPS.map((g) => ({ key: g.key, name: g.name })), { key: MINE, name: "我的" }];
const items = computed(() => COPY_GROUPS.find((g) => g.key === grp.value)?.items ?? []);

const addInput = ref("");
async function addCustom() {
  const text = addInput.value.trim();
  if (!text) return;
  await assets.create("copy", { text });
  addInput.value = "";
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="grp" :tabs="tabs" />

    <!-- 起步文案 -->
    <div v-if="grp !== MINE" class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
      <button v-for="(it, i) in items" :key="i" type="button" class="xhs-row" @click="xhs.insertAtCursor(it)">
        {{ it }}
      </button>
    </div>

    <!-- 我的文案 -->
    <div v-else class="min-h-0 flex-1 flex flex-col" :style="{ gap: '8px' }">
      <div class="flex items-center" :style="{ gap: '6px' }">
        <input
          v-model="addInput"
          type="text"
          class="xhs-copy-add-input"
          placeholder="添加一句自定义文案，回车或点添加"
          @keydown.enter.prevent="addCustom"
        />
        <button type="button" class="xhs-copy-add-btn xhs-copy-mine-tab" @click="addCustom">添加</button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
        <div v-if="!assets.copies.length" class="xhs-empty">还没有自定义文案～</div>
        <div v-for="a in assets.copies" :key="a.id" class="xhs-mine-row">
          <button type="button" class="xhs-mine-main" @click="xhs.insertAtCursor(a.payload.text)">{{ a.payload.text }}</button>
          <button type="button" class="xhs-mine-del" title="删除" @click="assets.remove(a.id)">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.xhs-row { text-align: left; border: 1px solid var(--line-2); border-radius: 10px; padding: 8px 12px; background: #fff; color: var(--ink); font-size: 13px; cursor: pointer; transition: border-color 0.15s; }
.xhs-row:hover { border-color: var(--primary); }
.xhs-copy-add-input { flex: 1; min-width: 0; border: 1px solid var(--line-2); border-radius: 8px; padding: 7px 10px; font-size: 13px; outline: none; color: var(--ink); background: #fff; }
.xhs-copy-add-btn { flex-shrink: 0; font-size: 13px; padding: 7px 14px; border-radius: 8px; background: var(--primary); color: #fff; cursor: pointer; }
.xhs-empty { color: var(--ink-2); font-size: 12.5px; text-align: center; padding: 16px 8px; }
.xhs-mine-row { display: flex; align-items: center; gap: 6px; }
.xhs-mine-main { flex: 1; min-width: 0; text-align: left; border: 1px solid var(--line-2); border-radius: 10px; padding: 8px 12px; background: #fff; color: var(--ink); font-size: 13px; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; transition: border-color 0.15s; }
.xhs-mine-main:hover { border-color: var(--primary); }
.xhs-mine-del { flex-shrink: 0; width: 26px; height: 26px; border-radius: 6px; color: var(--ink-2); cursor: pointer; }
.xhs-mine-del:hover { color: var(--red); background: rgba(var(--ink-rgb),0.06); }
</style>
```

> `.xhs-mine-row/.xhs-mine-main/.xhs-mine-del/.xhs-empty` 同款将在 T4/T6 复用 —— 可保持各面板局部 scoped（简单），不强行抽公共组件（YAGNI）。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/CopyPanel.spec.ts`
Expected: PASS（2 个）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/xhs/panels/CopyPanel.vue frontend/src/components/xhs/panels/__tests__/CopyPanel.spec.ts
git commit -m "feat(xhs): 文案面板「我的」分组 +「添加自定义文案」(P4 T5)"
```

---

## Task 6: 话题面板「我的」+「存为话题分组」+「全部添加」

**Files:**
- Modify: `frontend/src/components/xhs/panels/TopicPanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/TopicPanel.spec.ts`（新建或补）

> 先 `Read` `TopicPanel.vue`。它读 `TOPIC_GROUPS`，点击走 `xhs.addTopic(t)`。本任务加「我的」分组 +「存为话题分组」（把当前正文话题存成一组）+ 每组「全部添加」。

- [ ] **Step 1: 写失败测试**

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

const mockClient = { get: vi.fn(), post: vi.fn(), delete: vi.fn() };
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: mockClient }) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

import TopicPanel from "@/components/xhs/panels/TopicPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  mockClient.get.mockResolvedValue({ data: { assets: [] } });
  mockClient.post.mockReset();
});

describe("TopicPanel 我的话题分组", () => {
  it("有话题时「存为话题分组」create(topic_group)", async () => {
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "1", kind: "topic_group", payload: { name: "我的话题", tags: ["穿搭", "通勤"] }, created_at: "t" } },
    });
    const store = useXhs();
    store.$patch({ topics: ["穿搭", "通勤"] });
    const w = mount(TopicPanel);
    await flushPromises();
    await w.find(".xhs-save-topicgroup").trigger("click");
    await flushPromises();
    const [, body] = mockClient.post.mock.calls[0];
    expect(body.kind).toBe("topic_group");
    expect(body.payload.tags).toEqual(["穿搭", "通勤"]);
    w.unmount();
  });

  it("「全部添加」把组内 tag 全部 addTopic", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "1", kind: "topic_group", payload: { name: "g", tags: ["a", "b", "c"] }, created_at: "t" }] },
    });
    const store = useXhs();
    const spy = vi.spyOn(store, "addTopic");
    const w = mount(TopicPanel);
    await flushPromises();
    await w.find(".xhs-mine-tab").trigger("click"); // 切到我的（如用普通 tab 改 selector）
    await w.find(".xhs-addall").trigger("click");
    expect(spy).toHaveBeenCalledTimes(3);
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/TopicPanel.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

`TopicPanel.vue` `<script setup>` 增：

```typescript
import { onMounted } from "vue";
import { useXhsAssets } from "@/stores/xhsAssets";
import { useToast } from "@/composables/useToast";

const assets = useXhsAssets();
const toast = useToast();
onMounted(() => { void assets.ensureLoaded(); });

const MINE = "__mine__";

async function saveTopicGroup() {
  if (!xhs.topics.length) {
    toast.error("先在正文区加几个话题，再存为分组");
    return;
  }
  await assets.create("topic_group", { name: "我的话题", tags: [...xhs.topics] });
  toast.success("已存为话题分组");
}

function addAll(tags: string[]) {
  for (const t of tags) xhs.addTopic(t);
}
```

`<template>`：把「我的」加进分组 tab；选中时渲染 `assets.topicGroups`，每组一个卡片含「全部添加」按钮 + 各 tag chip（点击 `addTopic`）+ 删除组：

```html
<button type="button" class="xhs-save-topicgroup xhs-mine-tab" @click="saveTopicGroup">＋ 存为话题分组</button>
...
<template v-if="grp === MINE">
  <div v-if="!assets.topicGroups.length" class="xhs-empty">还没有自定义话题分组～</div>
  <div v-for="a in assets.topicGroups" :key="a.id" class="xhs-tg-card">
    <div class="xhs-tg-head">
      <span>{{ a.payload.name || '我的话题' }}</span>
      <button type="button" class="xhs-addall" @click="addAll(a.payload.tags)">全部添加</button>
      <button type="button" class="xhs-mine-del" title="删除分组" @click="assets.remove(a.id)">✕</button>
    </div>
    <div class="flex flex-wrap" :style="{ gap: '6px' }">
      <button v-for="(t, i) in a.payload.tags" :key="i" type="button" class="xhs-tag-chip" @click="xhs.addTopic(t)">#{{ t }}</button>
    </div>
  </div>
</template>
```

`<style scoped>` 补 `.xhs-save-topicgroup`（主色小按钮）、`.xhs-tg-card`（边框卡）、`.xhs-tg-head`（标题行，`全部添加` 推到右、删除在末）、`.xhs-addall`（ghost 小按钮）、`.xhs-tag-chip`（蓝底话题 chip，复用 NoteEditor 话题 chip 配色 `#3a6fb0`）、`.xhs-empty`/`.xhs-mine-del` 同 T5。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/TopicPanel.spec.ts`
Expected: PASS（2 个）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/xhs/panels/TopicPanel.vue frontend/src/components/xhs/panels/__tests__/TopicPanel.spec.ts
git commit -m "feat(xhs): 话题面板「我的」分组 + 存为话题分组 + 全部添加 (P4 T6)"
```

---

# Track B — AI prompt 设置（T7–T9）

## Task 7: AppConfig 加 xhs prompt 字段 + service 接 config（TDD）

**Files:**
- Modify: `csm_core/config.py`（`AppConfig` 加两字段）
- Modify: `sidecar/csm_sidecar/services/xhs_ai_service.py`（接 `config_service`）
- Test: `sidecar/tests/test_xhs_ai_service.py`（追加自定义/默认 prompt 测试）

- [ ] **Step 1: 写失败测试**

在 `sidecar/tests/test_xhs_ai_service.py` 追加（沿用该文件既有的 `_RecordingClient` + `monkeypatch.setattr(service.llm_factory, "build_client", ...)` 风格；此处再 monkeypatch `service.config_service.load`）：

```python
from csm_core.config import AppConfig


def test_generate_uses_custom_system_prompt(monkeypatch):
    from csm_sidecar.services import xhs_ai_service as service

    recorded = {}

    class _Rec:
        def complete(self, *, system, user, temperature=None):
            recorded["system"] = system
            recorded["user"] = user
            return '{"title":"t","body":"b","topics":[]}'

    monkeypatch.setattr(service.llm_factory, "build_client", lambda **kw: _Rec())
    monkeypatch.setattr(service.config_service, "load", lambda: AppConfig(xhs_generate_prompt="我的生成提示词"))
    service.generate_note("主题")
    assert recorded["system"] == "我的生成提示词"


def test_generate_falls_back_to_default_when_empty(monkeypatch):
    from csm_sidecar.services import xhs_ai_service as service

    recorded = {}

    class _Rec:
        def complete(self, *, system, user, temperature=None):
            recorded["system"] = system
            return '{"title":"t","body":"b","topics":[]}'

    monkeypatch.setattr(service.llm_factory, "build_client", lambda **kw: _Rec())
    monkeypatch.setattr(service.config_service, "load", lambda: AppConfig())  # 空串
    service.generate_note("主题")
    assert recorded["system"] == service.DEFAULT_GENERATE_SYSTEM


def test_polish_uses_custom_system_prompt(monkeypatch):
    from csm_sidecar.services import xhs_ai_service as service

    recorded = {}

    class _Rec:
        def complete(self, *, system, user, temperature=None):
            recorded["system"] = system
            return "润色后"

    monkeypatch.setattr(service.llm_factory, "build_client", lambda **kw: _Rec())
    monkeypatch.setattr(service.config_service, "load", lambda: AppConfig(xhs_polish_prompt="我的润色提示词"))
    out = service.polish_note("原文")
    assert recorded["system"] == "我的润色提示词"
    assert out == "润色后"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_service.py -v
```
Expected: FAIL（`AttributeError: ... has no attribute 'config_service'` 或 `AppConfig 无 xhs_generate_prompt`）

- [ ] **Step 3a: 实现 config 字段**

`csm_core/config.py`，在 `AppConfig` 现有 mining prompt 字段（`mining_summary_prompt`/`mining_suggest_prompt`）之后追加：

```python
    # ── XHS editor AI prompts (P4) ──────────────────────────────────────
    # 空字符串 = 用 xhs_ai_service 内置默认 prompt（DEFAULT_GENERATE_SYSTEM /
    # DEFAULT_POLISH_SYSTEM）。用户在设置页改了之后，下次 AI 生成/润色优先用这里。
    xhs_generate_prompt: str = ""
    xhs_polish_prompt: str = ""
```

- [ ] **Step 3b: 实现 service 接 config**

`sidecar/csm_sidecar/services/xhs_ai_service.py`：顶部加 import 与 helper（`config_service` 在同包 services 下）：

```python
from csm_core.config import AppConfig
from . import config_service


def _load_config() -> AppConfig:
    """读全局配置；未初始化（如部分单测未注入路径）时退回默认值，保证内置 prompt 可用。"""
    try:
        return config_service.load()
    except Exception:
        return AppConfig()


def _resolve_system(custom: str, default: str) -> str:
    """空白自定义 → 内置默认。"""
    return custom if custom.strip() else default
```

`generate_note(intent)`：把原来 `client.complete(system=DEFAULT_GENERATE_SYSTEM, ...)` 改为：

```python
    cfg = _load_config()
    system = _resolve_system(cfg.xhs_generate_prompt, DEFAULT_GENERATE_SYSTEM)
    raw = client.complete(system=system, user=f"主题 / 关键词：{intent}")
```

`polish_note(text)`：同理把 `system=DEFAULT_POLISH_SYSTEM` 改为：

```python
    cfg = _load_config()
    system = _resolve_system(cfg.xhs_polish_prompt, DEFAULT_POLISH_SYSTEM)
    out = client.complete(system=system, user=text)
```

> 保持 `generate_note`/`polish_note` 其余逻辑（空输入早返、解析兜底）不变。`_load_config` 的 try/except 让既有 13 个测试（不注入 config）继续走默认分支、零改动通过。

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_service.py -v
```
Expected: PASS（既有 13 + 新增 3 = 16 个）

- [ ] **Step 5: Commit**

```bash
git add csm_core/config.py sidecar/csm_sidecar/services/xhs_ai_service.py sidecar/tests/test_xhs_ai_service.py
git commit -m "feat(xhs): AI prompt 可配置——AppConfig xhs_generate/polish_prompt + service 接 config (P4 T7)"
```

---

## Task 8: ai_prompts GET/PATCH 路由（TDD）

**Files:**
- Modify: `sidecar/csm_sidecar/routes/xhs.py`（加 import + payload + 两端点）
- Test: `sidecar/tests/test_xhs_ai_prompts_routes.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_xhs_ai_prompts_routes.py`，**夹具照 `sidecar/tests/test_mining_ai_prompts_routes.py`**（它已跑通 config 初始化到 tmp + token）：

```python
"""GET/PATCH /api/xhs/ai_prompts —— 夹具结构对齐 test_mining_ai_prompts_routes.py。"""
from __future__ import annotations

import pytest


# client/auth/config-tmp 夹具：复制 test_mining_ai_prompts_routes.py 的同名夹具，
# 把请求路径换成 /api/xhs/ai_prompts、字段换成 generate/polish。


def test_get_shape_defaults_empty(client):
    r = client.get("/api/xhs/ai_prompts")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"generate", "polish"}
    assert data["generate"]["current"] == ""
    assert data["polish"]["current"] == ""
    assert data["generate"]["default"]  # 内置默认非空


def test_patch_persists_generate(client):
    r = client.patch("/api/xhs/ai_prompts", json={"generate": "自定义生成"})
    assert r.status_code == 200
    assert r.json()["generate"]["current"] == "自定义生成"
    # 再 GET 仍是自定义
    assert client.get("/api/xhs/ai_prompts").json()["generate"]["current"] == "自定义生成"


def test_patch_empty_clears_back_to_default(client):
    client.patch("/api/xhs/ai_prompts", json={"polish": "x"})
    r = client.patch("/api/xhs/ai_prompts", json={"polish": ""})
    assert r.json()["polish"]["current"] == ""


def test_patch_no_fields_400(client):
    assert client.patch("/api/xhs/ai_prompts", json={}).status_code == 400


def test_requires_auth(client_noauth):
    # 对齐 mining 测试：无 token 的 client 应 401
    assert client_noauth.get("/api/xhs/ai_prompts").status_code == 401
```

> `client` / `client_noauth` 夹具直接照搬 `test_mining_ai_prompts_routes.py`（仅改路径/字段）。务必先 `Read` 那个文件确认夹具名与 token 注入法。

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_prompts_routes.py -v
```
Expected: FAIL（端点 404）

- [ ] **Step 3: 实现路由**

`sidecar/csm_sidecar/routes/xhs.py`：确保已 `from ..services import xhs_ai_service`（P3 已有）；加 `from ..services import config_service`。加 payload 模型 + 两端点：

```python
class XhsAiPromptsPatch(BaseModel):
    """PATCH /api/xhs/ai_prompts 体。空字符串 = 回内置默认。"""
    generate: str | None = None
    polish: str | None = None


def _xhs_ai_prompts_payload() -> dict[str, Any]:
    cfg = config_service.load()
    return {
        "generate": {
            "current": cfg.xhs_generate_prompt,
            "default": xhs_ai_service.DEFAULT_GENERATE_SYSTEM,
        },
        "polish": {
            "current": cfg.xhs_polish_prompt,
            "default": xhs_ai_service.DEFAULT_POLISH_SYSTEM,
        },
    }


@router.get("/api/xhs/ai_prompts")
def get_xhs_ai_prompts() -> dict[str, Any]:
    return _xhs_ai_prompts_payload()


@router.patch("/api/xhs/ai_prompts")
def patch_xhs_ai_prompts(body: XhsAiPromptsPatch) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if body.generate is not None:
        updates["xhs_generate_prompt"] = body.generate
    if body.polish is not None:
        updates["xhs_polish_prompt"] = body.polish
    if not updates:
        raise HTTPException(status_code=400, detail="no fields provided")
    config_service.patch(updates)
    return _xhs_ai_prompts_payload()
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_prompts_routes.py -v
```
Expected: PASS（5 个）

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/xhs.py sidecar/tests/test_xhs_ai_prompts_routes.py
git commit -m "feat(xhs): GET/PATCH /api/xhs/ai_prompts（仿 mining_ai_prompts）(P4 T8)"
```

---

## Task 9: XhsPromptsCard.vue + 设置页注册

**Files:**
- Create: `frontend/src/components/settings/XhsPromptsCard.vue`
- Modify: `frontend/src/views/SettingsView.vue`（import + 在 `models` 段 `<MiningPromptsCard />` 后渲染）

> 非 TDD（纯 UI，逻辑与 `MiningPromptsCard` 同构、其后端已被 T8 测试覆盖）。先 `Read` `MiningPromptsCard.vue` 全文，复制改名。

- [ ] **Step 1: 实现 XhsPromptsCard.vue**

复制 `frontend/src/components/settings/MiningPromptsCard.vue` 为 `XhsPromptsCard.vue`，按下表改：
- 端点 `"/api/mining/ai_prompts"` → `"/api/xhs/ai_prompts"`。
- 两段从 `summary`/`suggest` → `generate`/`polish`（refs `generateDraft/generateBaseline/generateDefault`、`polishDraft/...`；dirty/isDefault 同步改名）。
- 标题文案：`AI 速览` → `AI 生成整篇`、`AI 建议` → `AI 润色正文`（对齐 `AiPanel.vue` 措辞）。
- **xhs prompt 是单段 system，无占位变量** → 删掉 `vars` 相关（`fmtVars`、占位变量提示行、payload 里 `data.summary.vars` 的读取）。保留 textarea + 保存 + 恢复默认 三态逻辑。
- 卡片外层标题：「小红书 AI 提示词」。

实现要点（与 Mining 卡一致）：
- `onMounted` `GET /api/xhs/ai_prompts` → 填 `current`(baseline/draft) 与 `default`(placeholder)。
- `saveGenerate`：`!dirty || saving` 早返；`PATCH {generate: draft}`；成功 `baseline = data.generate.current; draft = baseline`；toast。
- `resetGenerate`：`PATCH {generate: ""}` → `current` 变 `""` → baseline/draft 清空（占位回到 default）。
- `polish` 同理。
- 用 `useSidecar().client` + `useToast()`；按钮用 `Btn`、`Pill`、`Spinner`、`Icon`，配色照 Mining 卡（`var(--card-2)`/`var(--line)`/`var(--dark)`/`var(--yellow)`）。

- [ ] **Step 2: 注册进 SettingsView**

`frontend/src/views/SettingsView.vue`：
1. import 区（`MiningPromptsCard` import 之后）加：
```typescript
import XhsPromptsCard from "@/components/settings/XhsPromptsCard.vue";
```
2. 在 `section === 'models'` 块、`<MiningPromptsCard />` 之后加：
```html
            <div class="mb-3 mt-5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              小红书 AI 提示词
            </div>
            <XhsPromptsCard />
```

- [ ] **Step 3: 类型检查 + 构建**

Run（工作目录 `frontend/`）: `npx vue-tsc -b ; npx vite build`
Expected: 零错。跑后 `git status` 检查 `vite.config.js`/`*.d.ts` 产物，有则 `git checkout -- <产物>`。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/settings/XhsPromptsCard.vue frontend/src/views/SettingsView.vue
git commit -m "feat(xhs): 设置页小红书 AI 提示词卡 XhsPromptsCard + 注册 (P4 T9)"
```

---

# Track C — 预览 chip + 打磨（T10–T15）

## Task 10: `xhsCodes.ts` 代码 tokenizer（TDD）

**Files:**
- Create: `frontend/src/utils/xhsCodes.ts`
- Test: `frontend/src/utils/__tests__/xhsCodes.spec.ts`

- [ ] **Step 1: 写失败测试**

```typescript
import { describe, it, expect } from "vitest";
import { tokenizeXhsCodes } from "@/utils/xhsCodes";

describe("tokenizeXhsCodes", () => {
  it("空串 → 空数组", () => {
    expect(tokenizeXhsCodes("")).toEqual([]);
  });

  it("纯文本 → 单个 text 段", () => {
    expect(tokenizeXhsCodes("今天天气好")).toEqual([{ type: "text", value: "今天天气好", label: "" }]);
  });

  it("单个代码 → label 去掉 []R", () => {
    expect(tokenizeXhsCodes("[害羞R]")).toEqual([{ type: "code", value: "[害羞R]", label: "害羞" }]);
  });

  it("文本夹代码 → text/code/text 三段", () => {
    const segs = tokenizeXhsCodes("开心[偷笑R]结束");
    expect(segs).toEqual([
      { type: "text", value: "开心", label: "" },
      { type: "code", value: "[偷笑R]", label: "偷笑" },
      { type: "text", value: "结束", label: "" },
    ]);
  });

  it("多个代码相邻", () => {
    const segs = tokenizeXhsCodes("[害羞R][色R]");
    expect(segs.map((s) => s.type)).toEqual(["code", "code"]);
    expect(segs.map((s) => s.label)).toEqual(["害羞", "色"]);
  });

  it("非 R 结尾的方括号不当代码", () => {
    expect(tokenizeXhsCodes("[备注]说明")).toEqual([{ type: "text", value: "[备注]说明", label: "" }]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/utils/__tests__/xhsCodes.spec.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

新建 `frontend/src/utils/xhsCodes.ts`：

```typescript
/**
 * 小红书官方贴纸「文字代码」切分（设计稿 §6）。
 *
 * 小红书贴纸代码形如 `[害羞R]`、`[偷笑R]`（中文标签 + 尾随 R，方括号包裹）。
 * 本工具把正文切成 文本段 / 代码段，供 PhonePreview 把代码段渲染成占位 chip
 * （小药丸，显示去掉 []R 的标签）—— **不渲染任何官方贴纸图片**（版权 / ToS）。
 * 编辑区仍是纯文本，所见即所得只在预览面板承担。
 */
export interface XhsTextSegment {
  type: "text" | "code";
  value: string; // 原始片段（code 段含方括号，如 "[害羞R]"）
  label: string; // code 段的展示标签（去掉 []R，如 "害羞"）；text 段为空串
}

// 贪婪匹配最短的非方括号内容 + 尾随 R + 闭方括号。捕获组 1 = 标签文字。
const CODE_RE = /\[([^[\]]+?)R\]/g;

export function tokenizeXhsCodes(text: string): XhsTextSegment[] {
  if (!text) return [];
  const out: XhsTextSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(CODE_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) {
      out.push({ type: "text", value: text.slice(last, idx), label: "" });
    }
    out.push({ type: "code", value: m[0], label: m[1] });
    last = idx + m[0].length;
  }
  if (last < text.length) {
    out.push({ type: "text", value: text.slice(last), label: "" });
  }
  return out;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/utils/__tests__/xhsCodes.spec.ts`
Expected: PASS（6 个）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/xhsCodes.ts frontend/src/utils/__tests__/xhsCodes.spec.ts
git commit -m "feat(xhs): xhsCodes tokenizer（[xxxR] 代码切分）(P4 T10)"
```

---

## Task 11: PhonePreview 正文渲染代码 chip

**Files:**
- Modify: `frontend/src/components/xhs/PhonePreview.vue`
- Test: `frontend/src/components/xhs/__tests__/PhonePreview.spec.ts`（追加）

> 先 `Read` `PhonePreview.vue`，定位渲染 `{{ displayBody }}` 的正文 `<div>`（笔记页）。把其文本内容换成按 `tokenizeXhsCodes(displayBody)` 分段渲染。

- [ ] **Step 1: 写失败测试**

在 `PhonePreview.spec.ts` 追加：

```typescript
describe("PhonePreview 代码 chip", () => {
  it("正文含 [害羞R] 渲染成 chip（显示标签「害羞」）", () => {
    const store = useXhs();
    store.$patch({ body: "今天[害羞R]好开心", previewTab: "note" });
    const w = mount(PhonePreview);
    const chips = w.findAll(".xhs-code-chip");
    expect(chips.length).toBe(1);
    expect(chips[0].text()).toBe("害羞");
    // 周围文本仍在
    expect(w.text()).toContain("今天");
    expect(w.text()).toContain("好开心");
    w.unmount();
  });

  it("正文无代码时不产生 chip", () => {
    const store = useXhs();
    store.$patch({ body: "纯文本正文", previewTab: "note" });
    const w = mount(PhonePreview);
    expect(w.findAll(".xhs-code-chip").length).toBe(0);
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/__tests__/PhonePreview.spec.ts`
Expected: FAIL（无 `.xhs-code-chip`）

- [ ] **Step 3: 实现**

`PhonePreview.vue` `<script setup>` 加：

```typescript
import { tokenizeXhsCodes } from "@/utils/xhsCodes";
// displayBody 已是 computed（正文或占位）。分段：
const bodySegments = computed(() => tokenizeXhsCodes(displayBody.value));
```

把笔记页正文 `<div ...>{{ displayBody }}</div>` 改为分段渲染（保留原 `:style`，含 `whiteSpace: 'pre-wrap'`）：

```html
<div :style="{ fontSize: '13px', lineHeight: 1.7, color: xhs.body ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">
  <template v-for="(seg, i) in bodySegments" :key="i">
    <span v-if="seg.type === 'text'">{{ seg.value }}</span>
    <span v-else class="xhs-code-chip">{{ seg.label }}</span>
  </template>
</div>
```

`<style scoped>` 加（小药丸，主色淡底，inline-block 不破 pre-wrap）：

```css
.xhs-code-chip {
  display: inline-block;
  padding: 0 6px;
  margin: 0 1px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--primary);
  background: rgba(238, 106, 42, 0.12);
  vertical-align: baseline;
  white-space: nowrap;
}
```

> 注意：`displayBody` 为占位文案（正文空时）也会过 tokenizer —— 占位无代码、返回单 text 段，行为不变。只动笔记页正文；标题不处理（标题极少含贴纸代码，YAGNI）。`scale` 等比缩放对 chip 同样生效（它在 `.screen-scale` 内）。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/__tests__/PhonePreview.spec.ts`
Expected: PASS（既有 14 + 新增 2 = 16 个）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/xhs/PhonePreview.vue frontend/src/components/xhs/__tests__/PhonePreview.spec.ts
git commit -m "feat(xhs): 预览正文把 [xxxR] 代码渲染成占位 chip（非贴纸图，§6）(P4 T11)"
```

---

## Task 12: isEmpty 纳入 topics + 字数超限文字提示

**Files:**
- Modify: `frontend/src/stores/xhs.ts`（`isEmpty` getter）
- Modify: `frontend/src/components/xhs/NoteEditor.vue`（超限提示）
- Test: `frontend/src/stores/__tests__/xhs.spec.ts`（追加 isEmpty）

- [ ] **Step 1: 写失败测试**

在 `frontend/src/stores/__tests__/xhs.spec.ts` 追加：

```typescript
describe("isEmpty 纳入 topics（P4）", () => {
  it("仅有话题时 isEmpty 为 false", () => {
    const s = useXhs();
    s.$patch({ title: "", body: "", imageIds: [], topics: ["穿搭"] });
    expect(s.isEmpty).toBe(false);
  });

  it("标题/正文/图/话题全空时 isEmpty 为 true", () => {
    const s = useXhs();
    s.$patch({ title: "  ", body: "", imageIds: [], topics: [] });
    expect(s.isEmpty).toBe(true);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: FAIL（首个用例：当前 isEmpty 不看 topics → 返回 true）

- [ ] **Step 3a: 实现 isEmpty**

`frontend/src/stores/xhs.ts`，`isEmpty` getter 改为：

```typescript
    isEmpty: (s): boolean =>
      s.title.trim() === "" &&
      s.body.trim() === "" &&
      s.imageIds.length === 0 &&
      s.topics.length === 0,
```

- [ ] **Step 3b: 实现超限提示**

`frontend/src/components/xhs/NoteEditor.vue`，标题计数 `<span>` 改为带超出量：

```html
        <span :style="{ color: xhs.titleOver ? 'var(--red)' : 'var(--ink-2)' }">
          {{ xhs.titleCount }}/{{ TITLE_SOFT_LIMIT }}<template v-if="xhs.titleOver"> · 超 {{ xhs.titleCount - TITLE_SOFT_LIMIT }} 字</template>
        </span>
```

正文计数 `<span>` 同理：

```html
        <span :style="{ color: xhs.bodyOver ? 'var(--red)' : 'var(--ink-2)' }">
          {{ xhs.bodyCount }}/{{ BODY_SOFT_LIMIT }}<template v-if="xhs.bodyOver"> · 超 {{ xhs.bodyCount - BODY_SOFT_LIMIT }} 字</template>
        </span>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: PASS（含既有 isEmpty 相关用例 —— 若既有用例假设「仅 topics → empty」需同步更新为新语义）

> ⚠️ 若既有测试里有「只设 topics 仍 isEmpty=true」之类断言，按新语义改它（topics 现在算内容）。同时确认 `_ensureCreated` 相关测试不受影响（仅 topics 现在会触发建草稿，符合预期）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/xhs.ts frontend/src/components/xhs/NoteEditor.vue frontend/src/stores/__tests__/xhs.spec.ts
git commit -m "fix(xhs): isEmpty 纳入 topics + 字数超限显示超出量 (P4 T12)"
```

---

## Task 13: 有序列表按「列表块」重计数（TDD）

**Files:**
- Modify: `frontend/src/utils/xhsTheme.ts`（加 `nextOrderedNumber`）
- Modify: `frontend/src/stores/xhs.ts`（`_cursorProbe` + `registerCursorProbe` + `insertOrdered` 改用块计数）
- Modify: `frontend/src/components/xhs/NoteEditor.vue`（注册光标探针）
- Test: `frontend/src/utils/__tests__/xhsTheme.spec.ts` + `frontend/src/stores/__tests__/xhs.spec.ts`

- [ ] **Step 1: 写失败测试（util）**

在 `frontend/src/utils/__tests__/xhsTheme.spec.ts` 追加：

```typescript
import { nextOrderedNumber } from "@/utils/xhsTheme";

describe("nextOrderedNumber 按列表块计数", () => {
  it("空文本 → 1", () => {
    expect(nextOrderedNumber("", "circle")).toBe(1);
  });
  it("当前块已有 ①② → 3", () => {
    expect(nextOrderedNumber("① 第一\n② 第二\n", "circle")).toBe(3);
  });
  it("空行分隔后新块从 1 起", () => {
    expect(nextOrderedNumber("① 上一组\n\n", "circle")).toBe(1);
  });
  it("前文有块、空行后当前块已 1 个 → 2", () => {
    expect(nextOrderedNumber("引言\n\n① 当前块第一\n", "circle")).toBe(2);
  });
  it("emoji 样式同理", () => {
    expect(nextOrderedNumber("1️⃣ a\n2️⃣ b\n", "emoji")).toBe(3);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/utils/__tests__/xhsTheme.spec.ts`
Expected: FAIL（`nextOrderedNumber` 未导出）

- [ ] **Step 3a: 实现 util**

`frontend/src/utils/xhsTheme.ts` 末尾加（复用既有 `countOrderedMarkers`）：

```typescript
/**
 * 光标处「下一个有序序号」——只数当前列表块（最后一个空行之后的文本）里的同样式序号。
 * 这样跨多个列表块会各自从 1 重新计数（P4 打磨，取代 P3 的全文连续计数）。
 */
export function nextOrderedNumber(textBeforeCursor: string, style: OrderedStyle): number {
  // 空行（仅空白的整行）分隔列表块；取光标前最后一块。
  const blocks = textBeforeCursor.split(/\n[ \t]*\n/);
  const currentBlock = blocks[blocks.length - 1] ?? "";
  return countOrderedMarkers(currentBlock, style) + 1;
}
```

- [ ] **Step 3b: 写失败测试（store 探针）**

在 `frontend/src/stores/__tests__/xhs.spec.ts` 追加：

```typescript
describe("insertOrdered 按光标前列表块计数（P4）", () => {
  it("有探针时按块算下一个序号", () => {
    const s = useXhs();
    s.applyTheme("warm_yellow"); // ordered=emoji（按 themes.json 实际样式调整）
    const inserted: string[] = [];
    s.registerInserter((t) => inserted.push(t));
    // 探针返回：光标前已有「①\n\n② 」式——这里用 circle 主题更直观；按实际主题样式断言
    s.registerCursorProbe(() => ({ before: "前言\n\n" + s.activeTheme!.heading })); // 当前块无序号
    s.insertOrdered();
    expect(inserted[0].startsWith(orderedMarkerOf(s, 1))).toBe(true); // 见下注
  });

  it("无探针时回退用整段正文的尾块", () => {
    const s = useXhs();
    s.applyTheme("warm_yellow");
    s.registerInserter(() => {});
    s.registerCursorProbe(null);
    // 不抛错即可（回退路径）
    expect(() => s.insertOrdered()).not.toThrow();
  });
});
```

> 上面 `orderedMarkerOf` 仅示意 —— 实际断言用 `@/utils/xhsTheme` 的 `orderedMarker(1, style)` 比对插入文本前缀。测试可简化为：注册探针返回当前块含 1 个序号字形的 `before`，断言插入的是第 2 个序号字形。务必用 `s.activeTheme!.ordered` 取样式，避免硬编码。

- [ ] **Step 3c: 实现 store**

`frontend/src/stores/xhs.ts`：
1. import 加 `nextOrderedNumber`：
```typescript
import { orderedMarker, countOrderedMarkers, nextOrderedNumber } from "@/utils/xhsTheme";
```
2. 模块级单例加探针：
```typescript
// 光标上下文探针：NoteEditor 注册，返回光标前文本，用于有序列表按块计数。
let _cursorProbe: (() => { before: string }) | null = null;
```
3. `_resetXhsModuleState()` 里加 `_cursorProbe = null;`。
4. `registerInserter` 附近加：
```typescript
    /** NoteEditor 挂载时注册光标上下文探针（取光标前文本）；卸载传 null。 */
    registerCursorProbe(fn: (() => { before: string }) | null): void {
      _cursorProbe = fn;
    },
```
5. `insertOrdered` 改为按块：
```typescript
    insertOrdered(): void {
      const t = this.activeTheme;
      if (!t) return;
      const before = _cursorProbe ? _cursorProbe().before : this.body;
      const n = nextOrderedNumber(before, t.ordered);
      this.insertAtCursor(orderedMarker(n, t.ordered) + " ");
    },
```

> `countOrderedMarkers` 仍被 `nextOrderedNumber` 内部使用，保留 import。

- [ ] **Step 3d: NoteEditor 注册探针**

`frontend/src/components/xhs/NoteEditor.vue`：`onMounted/onUnmounted` 增探针注册（`bodyRef` 是 textarea）：

```typescript
onMounted(() => {
  xhs.registerInserter(insert);
  xhs.registerCursorProbe(() => {
    const el = bodyRef.value;
    const pos = el ? el.selectionStart ?? el.value.length : 0;
    return { before: (el?.value ?? xhs.body).slice(0, pos) };
  });
});
onUnmounted(() => {
  xhs.registerInserter(null);
  xhs.registerCursorProbe(null);
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/utils/__tests__/xhsTheme.spec.ts src/stores/__tests__/xhs.spec.ts`
Expected: PASS（util 5 新增 + store 探针 2）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/xhsTheme.ts frontend/src/stores/xhs.ts frontend/src/components/xhs/NoteEditor.vue frontend/src/utils/__tests__/xhsTheme.spec.ts frontend/src/stores/__tests__/xhs.spec.ts
git commit -m "feat(xhs): 有序列表按光标前列表块重计数（空行分块）(P4 T13)"
```

---

## Task 14: 后端草稿复制副本 + 图片拷贝（TDD）

**Files:**
- Modify: `sidecar/csm_sidecar/services/xhs_images_service.py`（加 `copy_images`）
- Modify: `sidecar/csm_sidecar/routes/xhs.py`（加 `POST /api/xhs/drafts/{id}/duplicate`）
- Test: `sidecar/tests/test_xhs_images_service.py`（追加 `copy_images`）+ `sidecar/tests/test_xhs_routes.py`（追加 duplicate；文件名按既有 draft 路由测试实际名）

- [ ] **Step 1: 写失败测试**

`copy_images`（在既有 `test_xhs_images_service.py` 追加，沿用其 `tmp_path`/`init` 夹具）：

```python
def test_copy_images_clones_files_with_new_ids(images_env):
    svc = images_env  # 既有夹具返回 service（root 指向 tmp）
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # 合法 jpeg magic
    id1 = svc.save_image("draftA", jpeg)
    new_ids = svc.copy_images("draftA", "draftB", [id1])
    assert len(new_ids) == 1
    assert new_ids[0] != id1
    # 新文件存在、内容一致
    assert svc.get_image_path(new_ids[0]) is not None
    assert svc.get_image_path(new_ids[0]).read_bytes() == jpeg


def test_copy_images_skips_missing(images_env):
    svc = images_env
    assert svc.copy_images("draftA", "draftB", ["nope"]) == []
```

duplicate 路由（在既有 draft 路由测试文件追加，沿用其 `client` + token 夹具）：

```python
def test_duplicate_draft_copies_fields_and_images(client):
    # 建草稿
    d = client.post("/api/xhs/drafts", json={"title": "原标题", "body": "正文", "topics": ["a"]}).json()
    did = d["id"]
    # 上传一张图并挂上
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    up = client.post(f"/api/xhs/drafts/{did}/images", files={"file": ("x.jpg", jpeg, "image/jpeg")}).json()
    client.patch(f"/api/xhs/drafts/{did}", json={"image_ids": [up["image_id"]], "cover_index": 0})

    r = client.post(f"/api/xhs/drafts/{did}/duplicate")
    assert r.status_code == 201
    dup = r.json()
    assert dup["id"] != did
    assert dup["title"] == "原标题（副本）"
    assert dup["body"] == "正文"
    assert dup["topics"] == ["a"]
    assert len(dup["image_ids"]) == 1
    assert dup["image_ids"][0] != up["image_id"]  # 新 id


def test_duplicate_missing_draft_404(client):
    assert client.post("/api/xhs/drafts/nope/duplicate").status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_images_service.py sidecar/tests/test_xhs_routes.py -v
```
Expected: FAIL（`copy_images` 不存在 / duplicate 404→405）

- [ ] **Step 3a: 实现 copy_images**

`sidecar/csm_sidecar/services/xhs_images_service.py` 末尾加：

```python
def copy_images(src_draft_id: str, dst_draft_id: str, image_ids: list[str]) -> list[str]:
    """把 src 草稿的若干图片复制进 dst 草稿目录，返回新 image_id 列表（缺失的跳过）。
    复用 save_image：按内容在 dst 子目录落新文件、生成新 id（不共享文件，避免删 src 误删 dst）。"""
    new_ids: list[str] = []
    for image_id in image_ids:
        path = get_image_path(image_id)
        if path is None:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        new_ids.append(save_image(dst_draft_id, data))
    return new_ids
```

- [ ] **Step 3b: 实现 duplicate 路由**

`sidecar/csm_sidecar/routes/xhs.py` 加（draft 路由附近；`xhs_images_service` P3 已 import）：

```python
@router.post("/api/xhs/drafts/{draft_id}/duplicate", status_code=201)
def duplicate_draft(draft_id: str) -> dict[str, Any]:
    src = xhs_storage.get_draft(draft_id)
    if src is None:
        raise HTTPException(status_code=404, detail="not found")
    new_id = xhs_storage.create_draft(
        title=(src["title"] or "") + "（副本）",
        body=src["body"],
        topics=src["topics"],
        cover_index=src["cover_index"],
        theme_id=src["theme_id"],
    )
    new_image_ids = xhs_images_service.copy_images(draft_id, new_id, src["image_ids"])
    if new_image_ids:
        xhs_storage.update_draft(new_id, image_ids=new_image_ids)
    result = xhs_storage.get_draft(new_id)
    return result
```

> `create_draft` 不接 `image_ids` 拷贝（图片要先落盘拿新 id），故先建文本草稿、拷图、再 `update_draft` 挂图。`cover_index` 随 src（图片数一致，下标有效）。

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_images_service.py sidecar/tests/test_xhs_routes.py -v
```
Expected: PASS（copy_images 2 + duplicate 2）

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/xhs_images_service.py sidecar/csm_sidecar/routes/xhs.py sidecar/tests/test_xhs_images_service.py sidecar/tests/test_xhs_routes.py
git commit -m "feat(xhs): 草稿复制副本 POST /drafts/{id}/duplicate + 图片拷贝 (P4 T14)"
```

---

## Task 15: 前端草稿重命名 + 复制副本

**Files:**
- Modify: `frontend/src/stores/xhs.ts`（`renameDraft`/`duplicateDraft`）
- Modify: `frontend/src/views/XhsEditorView.vue`（下拉行加 重命名 inline + 复制副本）
- Test: `frontend/src/stores/__tests__/xhs.spec.ts`（追加两 action）

- [ ] **Step 1: 写失败测试**

```typescript
describe("草稿 重命名 / 复制副本（P4）", () => {
  it("renameDraft PATCH 标题并刷新列表；当前草稿同步标题", async () => {
    const s = useXhs();
    s.$patch({ draftId: "d1", title: "旧" });
    const sidecar = useSidecar(); // 测试已 mock client（见文件顶部 mock）
    (sidecar.client.patch as any).mockResolvedValue({});
    (sidecar.client.get as any).mockResolvedValue({ data: { drafts: [] } });
    await s.renameDraft("d1", "新标题");
    expect(sidecar.client.patch).toHaveBeenCalledWith("/api/xhs/drafts/d1", { title: "新标题" });
    expect(s.title).toBe("新标题");
  });

  it("duplicateDraft POST duplicate 并刷新列表", async () => {
    const s = useXhs();
    const sidecar = useSidecar();
    (sidecar.client.post as any).mockResolvedValue({ data: { id: "d2" } });
    (sidecar.client.get as any).mockResolvedValue({ data: { drafts: [] } });
    await s.duplicateDraft("d1");
    expect(sidecar.client.post).toHaveBeenCalledWith("/api/xhs/drafts/d1/duplicate");
  });
});
```

> 若 `xhs.spec.ts` 既有的 sidecar mock 形态不同，按该文件已有 mock 风格对齐（保持 `client.patch/post/get` 可被 mock）。

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: FAIL（`renameDraft`/`duplicateDraft` 不存在）

- [ ] **Step 3a: 实现 store actions**

`frontend/src/stores/xhs.ts`，`deleteDraft` 附近加：

```typescript
    /** 重命名草稿（仅改标题）。当前打开的就是它则同步本地标题。 */
    async renameDraft(id: string, title: string): Promise<void> {
      const sidecar = useSidecar();
      await sidecar.client.patch(`/api/xhs/drafts/${id}`, { title });
      if (this.draftId === id) this.title = title;
      await this.loadDrafts();
    },
    /** 复制副本：后端建副本（含图片拷贝），刷新列表。返回新 id。 */
    async duplicateDraft(id: string): Promise<string | null> {
      const sidecar = useSidecar();
      const r = await sidecar.client.post(`/api/xhs/drafts/${id}/duplicate`);
      await this.loadDrafts();
      return r.data?.id ?? null;
    },
```

- [ ] **Step 3b: 实现下拉 UI**

`frontend/src/views/XhsEditorView.vue` 草稿下拉每行（现有删除按钮处）加 重命名（inline 输入）+ 复制副本。`<script setup>` 加：

```typescript
const renamingId = ref<string | null>(null);
const renameText = ref("");
function startRename(id: string, current: string, ev: Event) {
  ev.stopPropagation();
  renamingId.value = id;
  renameText.value = current;
}
async function commitRename(id: string, ev?: Event) {
  ev?.stopPropagation();
  const t = renameText.value.trim();
  renamingId.value = null;
  if (t) await xhs.renameDraft(id, t);
}
async function duplicate(id: string, ev: Event) {
  ev.stopPropagation();
  await xhs.duplicateDraft(id);
}
```

每行模板：标题区在 `renamingId === d.id` 时换成 `<input v-model="renameText" @keydown.enter.prevent="commitRename(d.id, $event)" @blur="commitRename(d.id)" @click.stop>`；行尾按钮组加「重命名」「复制副本」「删除」三个小图标按钮（沿用现有 `Icon` + `:style` 风格；重命名用 `Icon name="edit"` 或文字、复制用 `Icon name="copy"`）。

- [ ] **Step 4: 跑测试 + 类型检查**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: PASS（2 个）
Run: `npx vue-tsc -b ; npx vite build`（跑后还原可能的 `vite.config.js`/`.d.ts` 产物）
Expected: 零错。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/xhs.ts frontend/src/views/XhsEditorView.vue frontend/src/stores/__tests__/xhs.spec.ts
git commit -m "feat(xhs): 草稿下拉支持 重命名（行内）+ 复制副本 (P4 T15)"
```

---

## Task 16: 全量验证

**Files:** 无新增，仅跑闸门。

- [ ] **Step 1: 后端全量 pytest**

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests -q
```
Expected: 新增/相关全过（`test_xhs_custom_assets` 10、`test_xhs_ai_prompts_routes` 5、`test_xhs_ai_service` 16、`test_xhs_images_service` +2、draft 路由 +2）。仓库既有的 baidu/mining_schema/monitor zhihu_search/ms-playwright 等**环境性失败**与 P4 无关（在 origin/main 上同样失败），逐一确认非本次引入。

- [ ] **Step 2: 前端全量 vitest**

Run（工作目录 `frontend/`）: `npx vitest run`
Expected: 全过（新增 xhsCodes 6 + xhsAssets 3 + 三面板各 2 + PhonePreview +2 + xhsTheme +5 + xhs store +若干 + 既有全绿）。

- [ ] **Step 3: 类型检查 + 构建**

Run: `npx vue-tsc -b ; npx vite build`
Expected: 零错零警告。
⚠️ 跑后 `git status` 检查 `vite.config.js` / `*.d.ts` 产物 → 有则 `git checkout -- <产物>` 还原。

- [ ] **Step 4: 确认无意外改动**

```bash
git status
git diff --stat origin/main
```
Expected: 仅本计划列出的文件（含本 plan md）；main 未动；`sidecar/csm-sidecar.spec` 未改。

---

## Self-Review（计划自检，已过）

**1. Spec 覆盖（设计稿 §1 P4 / §3.4 / §6 / §7）：**
- 自定义素材 `xhs_custom_assets`（template/copy/topic_group，与起步合并、标「我的」）→ T1（表+DAO）/T2（路由）/T3（store）/T4-T6（三面板「我的」+录入+全部添加）。✓
- AI prompt 设置（`AppConfig.xhs_generate_prompt`/`xhs_polish_prompt` + 仿 `MiningPromptsCard` + `GET/PATCH /api/xhs/ai_prompts`）→ T7（config+service）/T8（路由）/T9（卡+注册）。✓
- 预览 `[害羞R]` 代码占位 chip（非贴纸图）→ T10（tokenizer）/T11（PhonePreview 渲染）。✓
- 字数超限提示 → T12（NoteEditor 显示超出量）。✓
- 空状态 → 各「我的」分组空态（T4-T6 `.xhs-empty`）；编辑器/预览空态 P0/P3 已具备。✓
- `isEmpty` 纳入 topics → T12。✓
- 有序列表按列表块重计数 → T13。✓
- 草稿列表管理（重命名/删除/复制副本）→ 删除 P0 已有；重命名 + 复制副本 T14（后端）/T15（前端）。✓
- emoji 字体一致性 → **决定不打包字体**（背景节已记录，无代码任务，符合 §6「评估」措辞）。✓
- 键盘焦点 → 录入 input 支持回车提交（T5/T6/T15 inline 输入 `@keydown.enter`）。✓

**2. Placeholder 扫描：** 无 TODO/TBD。`test_xhs_custom_assets.py` 的 `client` 夹具、`test_xhs_ai_prompts_routes.py` 的 `client/client_noauth` 夹具、各面板测试 selector，均显式标注「对齐既有 `test_xhs_ai_routes.py` / `test_mining_ai_prompts_routes.py` 夹具」——执行时先 Read 既有文件复用，不是占位。

**3. 类型一致性：**
- 后端：`create_custom_asset(*, kind, payload) -> dict`、`list_custom_assets(kind=None)`、`delete_custom_asset(id) -> bool`；路由 `_ASSET_KINDS` 与 store `XhsAssetKind` 三值一致（template/copy/topic_group）。`copy_images(src, dst, ids) -> list[str]`。`config_service.load/patch`、`xhs_ai_service.DEFAULT_GENERATE_SYSTEM/DEFAULT_POLISH_SYSTEM` 跨 T7/T8 一致引用。
- 前端：`tokenizeXhsCodes -> XhsTextSegment[]`（`{type,value,label}`）T10 定义、T11 消费一致；`nextOrderedNumber(textBeforeCursor, style)` T13 定义并被 `insertOrdered` 调用；store 新增 `registerCursorProbe`/`renameDraft`/`duplicateDraft` 命名跨 store/组件/测试一致；payload 形状（template `{name,title,body,topics}` / copy `{text}` / topic_group `{name,tags}`）在 T2 测试、T3 store、T4-T6 面板间一致。

---

## Execution Handoff

沿用 P1/P2/P3 既定方式：**子代理逐任务 + 两阶段评审（spec 合规 → 代码质量）**，三轨可并行推进，全部任务后跨层终审（opus），再交浏览器验收（用户用 `.bat` 启动 dev；Python 路由改动需重启 .bat，前端走 Vite HMR），验收 OK 才 `push -u origin claude/xhs-editor-p4`（避开 origin/main 推送陷阱）+ `gh pr create --base main`，停在 pending 等网页 merge。

## P5 / 后续衔接（不在本计划）
- emoji 字体一致性：若用户实测「豆腐块」，再评估打包 Twemoji（CC-BY）/ Noto Color Emoji（OFL）。
- 用户自备贴纸图「代码 → 图片」点亮（§6 扩展位，默认不附带）。
- 自定义素材的编辑（当前 MVP 删后重建）、导入导出、跨设备同步。
