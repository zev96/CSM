# 引流评论模板库（Comment Template Library）— 设计稿

- 日期：2026-05-19
- 范围：在 Outreach Phase 2 评论楼基础上，给 mining 模块加一个跨视频复用历史评论的「模板库」。包含三个界面：CommentComposer 上方 chips 行 + 右侧抽屉 + 设置页独立管理区。
- 关键澄清（与用户对话定下的）：
  - **数据来源混合**：评论 `status` 翻到 `done` 自动入库 + 用户可标精选/隐藏/编辑/删除管理；同时支持手动新建模板和批量导入。
  - **手动打标签 + 搜索**：检索靠 free-form 标签 + 全文搜索；不做 AI 智能推荐。
  - **UI 入口 C+B 混搭**：Composer 上方露 5 个精选 chips，旁边"更多 →"打开右侧抽屉看长列表；同时设置页有独立完整管理区。
  - **全平台汇总**：抽屉/chips 默认混展三平台所有模板（标签区分），设置页支持按平台筛选。
  - **只存文本**：模板不带图片（图片在评论场景重新挑），数据模型最简。
  - **独立 `comment_templates` 表**（路线 A）：与 `video_comments` 解耦，自动入库通过 trigger 复制一份。
  - **去 Emoji**：UI 全部用项目自研 `<Icon name="..." />`（feather-icons 风格），新增 3 个 SVG path：`bookmark` / `tag` / `upload`。

---

## 1. 范围

### in scope（本期做）

- **DB schema v5**：新增 `comment_templates` 表 + 复合索引 + 一次性历史回填
- **后端 7 个 API 端点**：模板 CRUD / use 计数 / 批量导入 / 标签列表（详见 §3）
- **`Icon.vue` 新增 3 个图标**：`bookmark` / `tag` / `upload`
- **CommentComposer chips 行**：输入框上方露最多 5 个精选 chips + "更多 →"按钮 + 空状态文案
- **模板抽屉（右侧滑出）**：搜索 + 标签筛选 + 列表 + 轻量操作（填入/标精选/编辑/隐藏）
- **设置页 `TemplateLibrarySection.vue`**：完整 CRUD + 批量导入 + 导出 JSON + 显示隐藏开关
- **自动入库钩子**：`update_comment` DAO 在 `status: draft → done` 时同事务 UPSERT 到模板表
- **历史回填**：v4 → v5 升级时扫描已有 `status='done'` 评论一次性入库
- **键盘流**：Composer 输入框 `Ctrl + /` 直接打开抽屉；抽屉里 `↑↓` 选条目、`Enter` 填入、`Esc` 关闭
- **复用计数**：点 chip / 抽屉填入按钮触发 `POST /use`，影响 chips top 5 排序

### out of scope（明确不做）

- **不做 AI 智能推荐 / embedding 相似度**（YAGNI；用户选了"手动打标签"作为检索方式）
- **不做模板带图片**（图片在评论场景重新挑）
- **不做变量占位符** `{产品名}` 替换（用户偏好"先填完整文本 → 手动微调"工作流）
- **不做软删 + 回收站**（删除即硬删，二次确认即可）
- **不做按用户分库**（CSM 当前单工作空间单用户；如未来多用户再做一次 migration 加 user_id）
- **不做导出 CSV**（tags 是数组，CSV 处理嵌套字段啰嗦；JSON 足够）
- **不做独立"标签管理"页**（标签 free-form，新建/编辑模板时下拉列出已用标签 + 允许输入新值）
- **不做自动给模板加标签**（避免 AI 调用成本；同文本第二次入库时 ON CONFLICT 合并历史 tags 作为弥补）

### 验收标准

- DB 自动 v4 → v5 升级，历史 `status='done'` 评论一次性回填，重跑幂等
- 在快手视频发布一条评论后，模板库自动出现这条，去重生效（同文本再发不新增 row、`use_count` +1）
- 打开 CommentComposer 时，chips 行显示 top 5（按 `starred DESC, last_used_at DESC, use_count DESC` 排序），点击填入输入框 + use_count +1
- 点 chip 时若输入框已有内容，弹小确认「替换 / 追加 / 取消」
- 点"更多 →"右侧抽屉滑出，能搜索文本、按标签多选筛选、能逐条标精选/编辑/隐藏
- `Ctrl + /` 在输入框按下时打开抽屉（不与浏览器/Tauri 系统快捷键冲突）
- 设置页"评论模板库" section 能新建/编辑/删除模板，能勾"显示隐藏"看隐藏条目并恢复
- 批量导入支持粘贴多行（每行一条）、选公共标签、选来源平台、预览"新增 X / 跳过 Y 重复" → 确认导入
- 导出 JSON 一键下载所有模板（含 hidden）的完整结构化数据
- UI 零 Emoji，全部使用 `<Icon name="..." />`；3 个新图标 (`bookmark` / `tag` / `upload`) 在 `Icon.vue` 中可正常渲染
- `vue-tsc -b && vite build` 零错零警告，sidecar pytest 全过 + 新加的模板库测试

---

## 2. 文件清单

### 后端新增

- `csm_core/mining/storage.py` — 加 `_DDL_V5_TEMPLATES`（`comment_templates` 表 + 索引）+ `apply_v5_migration`（建表 + 历史回填）+ DAO：`upsert_template_from_comment`, `list_templates`, `create_template`, `update_template`, `delete_template`, `bump_template_use`, `bulk_import_templates`, `list_used_tags`
- `csm_core/mining/test_templates.py` — 测 UPSERT 去重、status draft→done 触发、text 归一化、tag 合并、长度校验、回填幂等性
- `sidecar/csm_sidecar/routes/mining.py` — 加 7 个新路由（详见 §3.2）
- `sidecar/csm_sidecar/tests/test_templates_api.py` — 集成测：7 端点 happy path + 错误码

### 后端修改

- `csm_core/mining/storage.py` — `update_comment` DAO 加自动入库 hook（在事务里调 `upsert_template_from_comment`，仅在 status `draft → done` 时触发）

### 前端新增

- `frontend/src/components/mining/TemplateChipsRow.vue` — Composer 上方 chips 行（top 5 + 更多按钮 + 空状态）
- `frontend/src/components/mining/TemplateDrawer.vue` — 右侧滑出抽屉（搜索 + 标签筛选 + 列表 + 轻量管理）
- `frontend/src/components/settings/TemplateLibrarySection.vue` — 设置页独立 section（完整管理 + 批量导入 + 导出）
- `frontend/src/components/settings/TemplateEditModal.vue` — 新建/编辑模板的模态（textarea + 标签 multi-select）
- `frontend/src/components/settings/TemplateBulkImportModal.vue` — 批量导入模态（多行 textarea + 公共标签 + 预览）
- `frontend/src/stores/templates.ts` — Pinia store：`list`, `useTemplate`, `create`, `update`, `delete`, `star`, `hide`, `bulkImport`, `export`
- `frontend/src/stores/__tests__/templates.test.ts` — store action 单测

### 前端修改

- `frontend/src/components/ui/Icon.vue` — `PATHS` 字典新增 3 项：`bookmark`, `tag`, `upload`
- `frontend/src/components/mining/CommentComposer.vue` — 在 textarea 上方挂 `<TemplateChipsRow />` + 监听 `Ctrl + /` 打开抽屉 + 处理 chip 点击的"替换/追加/取消"弹层
- `frontend/src/views/SettingsView.vue` — `SECTIONS` 数组加 `{ k: "templates", l: "评论模板库", icon: "bookmark", sub: "..." }` + section switch 渲染 `<TemplateLibrarySection />`
- `frontend/src/stores/mining.ts` — 不动；新建 `templates.ts` 独立 store

---

## 3. 数据模型 & 后端 API

### 3.1 SQLite Schema v5

```sql
CREATE TABLE comment_templates (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  text              TEXT    NOT NULL,
  text_hash         TEXT    NOT NULL UNIQUE,             -- sha1(text.strip().lower())
  tags_json         TEXT    NOT NULL DEFAULT '[]',       -- JSON array<string>
  source_platform   TEXT,                                -- 'douyin'|'kuaishou'|'bilibili'|NULL(手动)
  source_comment_id INTEGER REFERENCES video_comments(id) ON DELETE SET NULL,
  starred           INTEGER NOT NULL DEFAULT 0,          -- 0/1
  hidden            INTEGER NOT NULL DEFAULT 0,          -- 0/1（chips/抽屉默认不显示，设置页勾选可见）
  use_count         INTEGER NOT NULL DEFAULT 0,
  first_seen_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_templates_starred_last ON comment_templates(starred DESC, last_used_at DESC);
CREATE INDEX idx_templates_hidden       ON comment_templates(hidden);
```

#### 字段约束

| 字段 | 约束 |
|---|---|
| `text` | 必填，长度 1-2000（与评论平台上限对齐）|
| `text_hash` | 必填，UNIQUE，去重靠它 |
| `tags_json` | JSON 数组，最多 10 个 tag，单 tag 最多 12 字 |
| `source_platform` | 可空（手动新建时为 NULL），仅做信息展示，不参与查询过滤 |
| `source_comment_id` | 可空（手动新建时为 NULL）；评论被删时 SET NULL，模板保留 |
| `starred` / `hidden` | 0/1，独立维度 |

#### 文本归一化

```python
def _normalize(text: str) -> str:
    return text.strip().lower()

def _hash(text: str) -> str:
    return hashlib.sha1(_normalize(text).encode("utf-8")).hexdigest()
```

**仅 strip + lower**，保留标点 / emoji / 中间空格。「很赞！」与「很赞」视为同一条（trailing 标点 + 大小写归一），「种草」与「种 草」视为不同（中间空格保留用户原意）。

### 3.2 REST API（挂 `routes/mining.py`，prefix `/api/mining/templates`）

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/api/mining/templates` | `?search=&tags=种草,对比&platform=douyin&starred=1&hidden=0&limit=50&offset=0` | `{ items: Template[], total: number }` |
| POST | `/api/mining/templates` | `{ text, tags?, source_platform? }` | `{ template: Template }` 或 409 `{ detail: "duplicate", existing_id: N }` |
| PATCH | `/api/mining/templates/{id}` | `{ text?, tags?, starred?, hidden? }` | `{ template: Template }` |
| DELETE | `/api/mining/templates/{id}` | — | `{ ok: true }` |
| POST | `/api/mining/templates/{id}/use` | — | `{ text: string }`（use_count +1, last_used_at = now） |
| POST | `/api/mining/templates/bulk-import` | `{ texts: string[], tags?: string[], source_platform? }` | `{ created: N, skipped_duplicates: M }` |
| GET | `/api/mining/templates/tags` | — | `{ tags: string[] }`（所有已用过的 tag 字典序）|

#### `list_templates` 查询语义

- `search`：`text LIKE '%kw%'`（库 < 5k 条时可接受；超过转 FTS5 是 future work）
- `tags`：CSV，多个 tag **取交集**（同时含全部）。SQL 用 JSON1 `EXISTS (SELECT 1 FROM json_each(tags_json) WHERE value IN (...))` + GROUP BY 条件
- `platform`：精确匹配 `source_platform`（特殊值 `manual` 匹配 NULL）
- `starred`：`= 1` 仅返回精选
- `hidden`：默认 `= 0` 仅返回未隐藏；前端勾"显示隐藏"传 `hidden=all`
- 排序：`ORDER BY starred DESC, last_used_at DESC, use_count DESC`

#### `bulk-import` 行为

- 输入 `texts` 数组按 `text_hash` 内部去重 + 与库内已存在的去重
- 每条新建时 `tags_json = tags`、`source_platform = source_platform`（参数透传）
- 跳过重复**不更新** `use_count`（与"发布评论自动入库"不同，导入是引入，不是复用）
- 单次调用上限 500 条，超 → 400 `{ detail: "max_batch_exceeded" }`

### 3.3 自动入库钩子

在 `csm_core/mining/storage.py` 的 `update_comment` DAO 同事务里：

```python
def update_comment(conn, comment_id: int, payload: UpdateCommentPayload) -> Comment:
    with conn:  # SQLite 事务上下文
        before = _fetch_comment(conn, comment_id)
        _apply_update(conn, comment_id, payload)
        after = _fetch_comment(conn, comment_id)
        if before.status != "done" and after.status == "done":
            _upsert_template_from_comment(conn, after)
        return after

def _upsert_template_from_comment(conn, comment: Comment) -> None:
    text_hash = _hash(comment.text)
    platform = _get_video_platform(conn, comment.video_id)  # JOIN videos
    conn.execute("""
        INSERT INTO comment_templates
          (text, text_hash, source_platform, source_comment_id,
           use_count, first_seen_at, last_used_at)
        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(text_hash) DO UPDATE SET
          use_count = use_count + 1,
          last_used_at = CURRENT_TIMESTAMP
          -- tags_json 不动：评论自动入库本身没 tags 可合并；
          -- starred / hidden 也不动：用户的管理状态优先于自动行为
    """, (comment.text, text_hash, platform, comment.id))
```

钩子放 DAO 层而不是 API 层 → 任何路径（HTTP / 后台 job / 单测）都会触发。

### 3.4 历史回填

`apply_v5_migration` 包在一个事务里：

```python
def apply_v5_migration(conn) -> None:
    conn.executescript(_DDL_V5_TEMPLATES)  # 建表 + 索引
    rows = conn.execute(
        "SELECT id, video_id, text, status FROM video_comments "
        "WHERE status = 'done' ORDER BY created_at ASC"
    ).fetchall()
    for row in rows:
        _upsert_template_from_comment(conn, Comment.from_row(row))
```

回填幂等（重跑也是 UPSERT），失败不阻塞 v4 → v5 升级：异常时整事务回滚，给 user toast「模板库初始化失败：<err>」，但 video_comments 继续可用。

---

## 4. UI 设计

### 4.1 CommentComposer · chips 行（C 形态）

挂载位置：[CommentComposer.vue](frontend/src/components/mining/CommentComposer.vue) 现有 `<textarea>` 上方。

```
┌─ TemplateChipsRow ────────────────────────────────────────────┐
│ ⭐ 吸力够大拖地一次过…   ⭐ 求推荐性价比的…                     │
│ ⭐ 续航对比下…    <Icon name="stack"/> 更多 (28)              │
├───────────────────────────────────────────────────────────────┤
│ [在这里写第一条评论…]                                         │
├───────────────────────────────────────────────────────────────┤
│ <Icon image/> 图片  <Icon wand/> AI 续写    ▶ 发布第1层  ✓完成 │
└───────────────────────────────────────────────────────────────┘
```

| 决策点 | 默认 |
|---|---|
| chips 数量 | top 5（含"更多"按钮共 6 个位）|
| 排序 | `starred DESC, last_used_at DESC, use_count DESC` |
| chip 文本 | 截断到 12 字 + `…`，hover tooltip 显示完整 |
| 精选标识 | chip 左侧渲染 `<Icon name="skills" :filled="true" />`，未精选不显示 |
| 平台过滤 | 默认混展全平台 |
| 点击空输入框 | 直接填入 + 聚焦光标 + 调 `POST /use` |
| 点击非空输入框 | 弹小确认「替换 / 追加 / 取消」（floating popover，不全屏 modal）|
| 空状态 | 库为空整行隐藏；库有但 top 5 为空显示灰提示「还没有模板，点 AI 续写或在设置里添加」|
| 抽屉触发 | "更多 →"按钮 + `Ctrl + /` 快捷键 |

### 4.2 CommentComposer · 抽屉（B 形态）

右侧滑出，宽 420px，半模态（点外部空白关闭，不阻挡主面板交互）。

```
┌─ <Icon stack/> 模板库                              <Icon x/> ┐
│ <Icon search/> [搜索文本或标签…]                              │
│ <Icon tag/> 全部 · 种草 · 对比 · 求推荐  [+ 新标签]            │
├──────────────────────────────────────────────────────────────┤
│ <Icon skills filled/> 这款吸力够大拖地一次过…                 │
│   #种草 · 用过 12 次                                          │
│   [填入] [<Icon skills/>] [<Icon edit/>] [<Icon eye/>隐藏]    │
├──────────────────────────────────────────────────────────────┤
│   求推荐性价比高的无线吸…                                     │
│   #求推荐 · 抖音 · 用过 3 次                                  │
│   [填入] [<Icon skills/>] [<Icon edit/>] [<Icon eye/>隐藏]    │
├──────────────────────────────────────────────────────────────┤
│   <Icon arrowDown/> 加载更多…                                 │
└──────────────────────────────────────────────────────────────┘
```

抽屉里能做的（轻量管理）：
- **填入**主输入框（调用 `/use` + 关抽屉）
- **标精选 / 取消精选**（`PATCH starred`）
- **编辑文本/标签**（行内 inline edit，回车保存）
- **隐藏**（`PATCH hidden=1`，从抽屉列表移除）
- **不能硬删**（避免误操作；硬删只在设置页）
- **不能批量导入**（批量只在设置页）

键盘：`↑↓` 选条目，`Enter` 填入并关抽屉，`Esc` 关抽屉。

### 4.3 设置页 · TemplateLibrarySection

在 [SettingsView.vue:170](frontend/src/views/SettingsView.vue:170) `SECTIONS` 数组末尾追加：

```ts
{ k: "templates", l: "评论模板库", icon: "bookmark",
  sub: "查看/编辑/批量导入/导出 评论模板" },
```

主体拆独立组件 `<TemplateLibrarySection v-if="section === 'templates'" />`。

#### 布局

```
┌─ 评论模板库 ─────────────────────────────────────────────────┐
│ <Icon search/> [搜索…]                                       │
│ <Icon tag/> 全部标签 ▼  平台：全部 ▼  □ 显示隐藏              │
│                                                              │
│ [<Icon plus/> 新建模板] [<Icon upload/> 批量导入]            │
│ [<Icon download/> 导出 JSON]            共 47 条 · 3 隐藏    │
├──────────────────────────────────────────────────────────────┤
│ <Icon skills filled/>                                        │
│   text 预览（150 字宽，超 …）                                │
│   #种草 #吸尘器 · 快手 · 用过 12 次 · 2025-03 入库            │
│        [<Icon edit/> 编辑] [<Icon skills/>] [<Icon eye/>]   │
│        [<Icon trash/> 删除]                                  │
├──────────────────────────────────────────────────────────────┤
│ <Icon skills/>                                               │
│   text 预览…                                                 │
│   (无标签) · 抖音 · 用过 1 次 · 2025-05 入库                  │
│        [<Icon edit/>] [<Icon skills/>] [<Icon eye/>]        │
│        [<Icon trash/>]                                       │
├──────────────────────────────────────────────────────────────┤
│  第 1-50 条 / 共 47 · ← 上一页 · 下一页 →                    │
└──────────────────────────────────────────────────────────────┘
```

#### 5 个核心操作

| 操作 | 行为 |
|---|---|
| **新建** | 模态 `<TemplateEditModal>`：textarea + 标签 multi-select + 保存 → `POST /templates`；text_hash 冲突 → 红字「已存在同文本，[跳转原条目]」|
| **编辑** | 同模态，预填数据，`PATCH /templates/{id}` |
| **批量导入** | 模态 `<TemplateBulkImportModal>`：大 textarea（每行一条）+ 公共标签 multi-select + 来源平台下拉 + 实时预览"将导入 X / 跳过 Y 重复" → 确认调 `POST /bulk-import` |
| **导出** | 一键下载 `templates-export-YYYYMMDD.json`，含 hidden 条目，结构同 GET list |
| **删除** | 二次确认弹窗；如果 use_count > 0 加红字警告「这条用过 12 次，确定删除？」→ `DELETE` |

#### 隐藏 / 显示

- 眼睛图标切换 `hidden`
- 隐藏的模板默认不在列表里显示
- 勾"显示隐藏" → 列表追加 hidden 条目（**变灰 0.55 透明度** 显示在同一列表里），右侧按钮变成"恢复"
- 不分组（避免页面分段）

#### 空状态

库空时：

```
        <Icon bookmark size=48/>
        评论模板库还是空的
        发一条评论它就会自动入库
        或者点 + 新建模板 先攒几条
```

### 4.4 Icon.vue 新增

```ts
// in PATHS dict
bookmark: '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
tag:      '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>',
upload:   '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
```

---

## 5. 边界 / Edge Cases

| 场景 | 处理 |
|---|---|
| 改 video_comments.text 后再 done | 不触发再入库（status 没变化）|
| 删除 video_comments 行 | source_comment_id 自动 SET NULL，模板保留 |
| 评论 status 由 done 回到 draft | 模板保留（"曾经发过的"快照）|
| 同文本在 N 个视频被多次 done | use_count=N，source 始终指向首次入库那条 |
| text 超 2000 字 | 后端 400 `{ detail: "text_too_long" }` |
| tags 超 10 个 | 后端 400 `{ detail: "too_many_tags" }` |
| 单 tag 超 12 字 | 后端 400 `{ detail: "tag_too_long" }` |
| 批量导入超 500 条 | 后端 400 `{ detail: "max_batch_exceeded" }` |
| 手动新建时 text_hash 撞 UNIQUE | 后端 409 + `{ existing_id }`；前端弹「已存在 [跳转]」|
| 批量导入全部重复 | toast「N 条全为重复，未导入新内容」|
| 删除时 use_count > 0 | 二次确认弹窗加红字警告 |
| 历史回填失败 | 整事务回滚 + toast「模板库初始化失败」，老评论功能不受影响 |
| API 失败（网络/sidecar 挂）| toast 红字 + 抽屉里 retry 按钮 |
| 1k 条以下库 | chips/抽屉/搜索均 < 5ms（索引 + LIKE）|
| 1k-5k 条库 | 偶有抖动，可接受 |
| 5k+ 条库 | future work 转 FTS5 全文索引（本期不做）|

---

## 6. 测试策略

| 层级 | 文件 | 测什么 |
|---|---|---|
| **后端单测** | `csm_core/mining/test_templates.py` | UPSERT 去重 / status `draft→done` 触发 / text 归一化 / tag 合并 / 长度校验 / 回填幂等性 |
| **后端集成** | `sidecar/csm_sidecar/tests/test_templates_api.py` | 7 端点 happy path + 错误码（409 dup / 400 长度 / 400 batch limit）|
| **前端单测** | `frontend/src/stores/__tests__/templates.test.ts` | store action（list / use / star / hide / bulkImport）|
| **前端组件测** | — | skip（项目没有 Vue 组件测试基建）|
| **手测脚本** | spec 附录 §7 | 用户在 dev 环境跑一遍 |

---

## 7. 手测 Checklist

发给用户在 dev 启动后跑一遍验收：

- [ ] **DB 升级**：启动应用看 sidecar 日志「migration v4 → v5 ok, backfilled N templates」
- [ ] **自动入库**：在某视频发一条评论 → 标记完成 → 打开任一其他视频 Composer，chips 行应出现这条
- [ ] **去重**：复用同一条评论文本发到另一个视频 → 完成 → 模板库里该条 `use_count` 应 +1，**不出现重复 row**
- [ ] **chips 排序**：手动标精选两条 → chips 行精选优先 + 按 last_used_at 排
- [ ] **chips 截断**：用 30 字以上长文本测，chip 应显示 12 字 + `…`，hover 显示完整
- [ ] **替换/追加确认**：输入框先打 5 个字，再点 chip，应弹「替换/追加/取消」
- [ ] **Ctrl + / 快捷键**：在 textarea 内按 `Ctrl + /` 抽屉应滑出
- [ ] **抽屉搜索**：搜索框输入关键词，列表实时过滤
- [ ] **抽屉标签筛选**：勾两个标签应取交集（含 A 且 B）
- [ ] **抽屉隐藏**：在抽屉里隐藏一条 → 抽屉刷新看不到 → 设置页勾"显示隐藏"能看到（变灰）
- [ ] **设置页新建**：手动新建一条带两个标签 → 列表出现 + chips 行优先级低于 done 评论
- [ ] **设置页编辑**：编辑文本，text_hash 变化但 id 不变；编辑撞重复 → 红字提示
- [ ] **设置页删除**：删一条 use_count=12 的应弹警告，再删一条 use_count=0 的不弹警告
- [ ] **批量导入**：粘贴 10 行（含 2 行重复）+ 选标签 `测试` + 选平台 `douyin` → 预览「新增 8 跳过 2」→ 确认 → 列表里 8 条新增条目都带标签 `测试`
- [ ] **导出 JSON**：点导出，下载 `templates-export-20260519.json`，打开是完整结构数组
- [ ] **历史回填测试**：在 v4 数据库手动塞 5 条 `status='done'` 评论 → 升级 v5 → 模板表应有 5 条（按 created_at 升序）
- [ ] **跨平台过滤**：设置页"平台：全部"→"平台：douyin" → 列表只剩 source_platform='douyin' 的 + manual 不显示
- [ ] **空状态**：删光所有模板 → Composer chips 行整行隐藏；设置页显示「评论模板库还是空的」提示
- [ ] **Icon 渲染**：左侧导航"评论模板库"图标 = bookmark 形状，搜索/批量导入/导出图标都是 SVG（无 emoji）
- [ ] **类型/构建**：`pnpm vue-tsc -b && pnpm build` 零错零警告
