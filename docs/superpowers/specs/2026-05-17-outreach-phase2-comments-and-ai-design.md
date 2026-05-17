# Outreach 评论楼 + AI（Phase 2 + Phase 3）— 设计稿

- 日期：2026-05-17
- 范围：Phase 1 视觉骨架已上线。本 spec 接 Phase 2（评论楼草稿管理 + 增强导出）和 Phase 3（AI 速览 + AI 建议），两期共享 schema 和 LLM client，所以放在一个 spec 一次性发。
- 关键澄清（来自用户）：
  - **不做评论自动发布**。评论由用户在应用里写好草稿（含盖楼层级 + 图片），导出 CSV / 复制到剪贴板，交给外包机构去真实发评论。后端零浏览器自动化。
  - **图片走本地文件**（`%APPDATA%\com.csm.gui\mining_images\{video_id}\{uuid}.{ext}`），sidecar 起静态路由，不依赖云存储。
  - **AI 复用** `sidecar/csm_sidecar/services/llm_factory.build_client()`（同设置 UI 里"文章润色"用的那一套）。零额外配置。

---

## 1. 范围

### Phase 2 — 评论楼草稿管理 + 导出（in scope）

- **DB schema v4**：新增 `video_comments` 表（tier 字段支持盖楼 N 层），不再加 `done` 列（`already_commented` + 评论状态足够）
- **后端 CRUD**：`/api/mining/videos/{id}/comments` GET/POST/PATCH/DELETE
- **图片上传**：`POST /api/mining/comments/images`（multipart）→ 写本地文件 → 返回 `image_id` + URL；`GET /api/mining/images/{image_id}` 静态服务
- **前端 composer 真能写**：`VideoCard.vue` 评论楼区块从 placeholder 变成可用：
  - 第 1 层 composer 输入 + 上传图片 + 保存草稿
  - 保存后顺次展示已写的评论列表 + "发布第 N 层"按钮加更高 tier
  - 每条评论右上角"复制"按钮（文本 + 图片 caption 一起到剪贴板）
- **整卡片复制**：卡片右上角 ⋯ 菜单加"复制全部评论"，把本卡所有 tier 评论按格式 `[第 1 层] text\n[第 2 层] text` 一次性拷贝
- **导出 CSV 增强**：现有 CSV 加列 `comment_tier_1`, `comment_tier_2`, `comment_tier_3`...（按数据库里出现的最大 tier 数动态生成）+ `images_tier_N`（半角逗号分割的相对路径）
- **整卡片"标记已评论"**：现在浮动批量栏的"标记已评论"按钮变成 active，PATCH `videos.already_commented` 批量翻转
- **沿用 Phase 1 视觉**：评论楼区块仍然嵌在卡片里，颜色 / 边距 / 字号 1:1 匹配设计稿

### Phase 3 — AI 速览 + AI 建议（in scope）

- **DB schema v4 同时加** `videos.ai_summary` 列（TEXT，nullable）
- **`POST /api/mining/videos/{id}/ai_summary`** → 调 `llm_factory.build_client().complete(system, user)` → 写库 → 返回新值；带 `force=true` 走重新生成
- **`POST /api/mining/videos/{id}/ai_suggest_comment`** → 给 composer 用，返回一段建议草稿，前端拿到后填到 textarea（不自动保存）
- **可自定义 prompt**：内置默认 prompt（speec §4.3 写死的那两段），但用户可以在 设置 里改：
  - `AppConfig` 加两个字段：`mining_summary_prompt: str = ""` / `mining_suggest_prompt: str = ""`（空字符串 = 用内置默认）
  - 新路由 `GET /api/mining/ai_prompts` 返回 `{ summary: { current, default }, suggest: { current, default } }`
  - `PATCH /api/mining/ai_prompts` 接 `{ summary?, suggest? }`（空字符串 = 清回默认）
  - `mining_ai_service` 调用时优先用 user-defined，没有再 fallback default
- **设置页加一张卡片**：`SettingsView` 里新增 `MiningPromptsCard.vue`，两个 textarea + 重置按钮 + "查看变量"提示 hover 列出 `{title} {author} {tier1_text}` 等可用占位符
- **前端 VideoCard**：AI 速览区块从 placeholder 变成"点击生成"按钮 / loading / 已生成展示 / 重新生成；composer 加 AI 建议按钮
- **错误兜底**：未配置 default provider → 提示 "去 设置 选一个 LLM 服务"，链接到 settings 路由

### out of scope（明确不做）

- **不做评论真发布**（用户外包人工发）
- **不做盖楼 reply parent 关联**（tier=N 仅表示发布顺序，不是树形回复）
- **不做腾讯文档 / 飞书 / Google Docs 集成**（独立 Phase 4 spec 再调研）
- **不做 OSS 云存储**（图片本地存）
- **不做 AI 流式响应**（一次性返回；如果体感慢再升级 SSE）
- **不做 AI prompt 自定义 UI**（prompt 写死在 service 层；用户可在设置里改 LLM provider，prompt 留下次再说）
- **不做素材库 / 模板库**（YAGNI；当前一次写一条够用）

### 验收标准

- DB 自动 v3 → v4 升级，老数据零丢失（升级前后 `SELECT COUNT(*) FROM videos` 相同）
- 给一个 B 站视频写两层评论 + 各 1 张图 → 保存 → 刷新页面 → 评论按 tier 顺序回来，图片缩略图能看
- 导出 CSV，Excel 打开看到 `comment_tier_1` / `comment_tier_2` 两列含文本
- "复制全部评论"按钮按一下，弹出 toast "已复制"，剪贴板里能粘出格式化文本
- 点 AI 速览按钮 → 出 spinner → 几秒后写出一段 60-100 字摘要；下次刷新页面摘要还在
- 点 AI 建议按钮（composer 上方）→ textarea 填入一段建议文案
- LLM 未配置时点 AI 速览 → 错误 toast "请先在设置中配置 AI 服务"，链接跳 settings
- `vue-tsc -b && vite build` 零错零警告，所有 sidecar 测试通过 + 新加的 schema 迁移 + comment CRUD 测试

---

## 2. 文件清单

### 后端新增

- `csm_core/mining/storage.py` — 加 `_DDL_V4_MINING`（`video_comments` 表 + `videos.ai_summary` 列）+ `apply_v4_migration` + comment CRUD（`create_comment`, `list_comments`, `update_comment`, `delete_comment`, `bulk_mark_commented`）+ `set_ai_summary` + `list_videos` 选 `ai_summary` 字段
- `sidecar/csm_sidecar/services/mining_ai_service.py` — 新建。`summarize_video(video_id) → str` + `suggest_comment(video_id, context) → str`。装饰 `llm_factory.build_client` + 写死的 prompt 模板。
- `sidecar/csm_sidecar/services/mining_images_service.py` — 新建。`save_image(video_id, file_bytes, ext) → image_id` + `get_image_path(image_id) → Path` + `cleanup_orphans()`。底下封 `appdirs.user_data_dir`。
- `sidecar/csm_sidecar/routes/mining.py` — 加 6 个新路由：
  - `GET /api/mining/videos/{id}/comments`
  - `POST /api/mining/videos/{id}/comments`
  - `PATCH /api/mining/comments/{cid}`
  - `DELETE /api/mining/comments/{cid}`
  - `POST /api/mining/comments/images` (multipart)
  - `GET /api/mining/images/{image_id}` (静态文件)
  - `POST /api/mining/videos/{id}/ai_summary`
  - `POST /api/mining/videos/{id}/ai_suggest_comment`
  - `PATCH /api/mining/videos/bulk_mark_commented`
  - CSV export 改造（加 comment 列）

### 后端不动

- 现有 mining_jobs / videos 表（只加列，不动结构）
- mining runner / adapter 代码（Phase 1 已上线）
- 监控中心代码（评论楼独立于 monitor 任务）

### 前端新增

- `frontend/src/components/mining/CommentItem.vue` — 单条评论行（tier 徽章 + 文本 + 图片缩略图 + 复制 / 删除按钮）
- `frontend/src/components/mining/CommentComposer.vue` — 输入框 + 图片上传按钮 + AI 建议按钮 + 保存为第 N 层按钮。从 VideoCard 拆出来，便于复用
- `frontend/src/components/ui/Toast.vue` — 通用 toast 组件（轻量，复制成功 / AI 失败提示用）

### 前端改造

- `frontend/src/components/mining/VideoCard.vue` — 评论楼区块嵌 `<CommentItem>` 列表 + `<CommentComposer>`；AI 速览区块改为"点击生成"按钮 + 展示态切换；卡片 ⋯ 菜单加"复制全部评论"
- `frontend/src/views/MiningView.vue` — 浮动批量栏的"标记已评论"按钮接 API，"全部打开"按钮接现有 `window.open` 循环
- `frontend/src/stores/mining.ts` — 加 `loadComments(videoId)` / `createComment(...)` / `deleteComment(cid)` / `summarize(videoId)` / `suggestComment(videoId, context)` / `bulkMarkCommented(ids)` actions

### 文件不动

- `frontend/src/router/index.ts`、`frontend/src/components/LeftNav.vue`、settings 相关组件
- mining runner / adapter 代码

---

## 3. 数据模型

### 3.1 video_comments 表（新表）

```sql
CREATE TABLE IF NOT EXISTS video_comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    tier            INTEGER NOT NULL,           -- 1=第 1 层, 2=第 2 层 ...
    text            TEXT NOT NULL DEFAULT '',
    image_ids_json  TEXT NOT NULL DEFAULT '[]',  -- JSON 数组 ["uuid1", "uuid2"]
    status          TEXT NOT NULL DEFAULT 'draft', -- draft / assigned / done
    source          TEXT NOT NULL DEFAULT 'manual', -- manual / ai_suggested
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(video_id, tier)
);
CREATE INDEX IF NOT EXISTS idx_video_comments_video ON video_comments(video_id);
```

**设计决策**：
- `tier` 是 UNIQUE + video_id 组合，保证一个视频不会有两个第 1 层。前端发送时算 `MAX(tier)+1`，并发由 UNIQUE 兜底（前端拿 409 提示）。
- `image_ids_json` 存 image_id 列表，image 本身在文件系统。删评论时 cleanup_orphans 会扫这个 JSON 找到无人引用的图片清。
- `status` 留三态预留 Phase 4 / 共享文档同步；Phase 2 只用 `draft`。
- `source` 区分手写 vs AI 建议（统计 AI 采纳率，未来 ROI 用）。

### 3.2 videos.ai_summary 列（已有表加列）

```sql
ALTER TABLE videos ADD COLUMN ai_summary TEXT;
```

不索引（按 video_id 查，不会被 WHERE）。空字符串和 NULL 都视为未生成，前端按"生成"按钮触发。

### 3.3 Migration

加 `apply_v4_migration(conn)` 到 storage.py；monitor.storage._migrate 现在跑到 v3，bump 到 v4 并调 apply_v4_migration。保留 idempotent（IF NOT EXISTS + ALTER 包 try/except OperationalError "duplicate column"）。

---

## 4. 后端 API 约定

### 4.1 评论 CRUD

```
GET /api/mining/videos/{id}/comments
→ { "comments": [{ "id": 1, "tier": 1, "text": "...", "image_ids": ["uuid"], "image_urls": ["/api/mining/images/uuid"], "status": "draft", "source": "manual", "created_at": "..." }, ...] }

POST /api/mining/videos/{id}/comments
Body: { "tier": 1, "text": "...", "image_ids": ["uuid"], "source": "manual" }
→ 201 { "id": 12, ... 同 GET 单条 }
→ 409 if (video_id, tier) 冲突

PATCH /api/mining/comments/{cid}
Body: { "text"?: "...", "image_ids"?: [...], "status"?: "..." }
→ 200 { ...更新后单条 }

DELETE /api/mining/comments/{cid}
→ 204
（同时把 image_ids 里的图片排队 cleanup_orphans）
```

### 4.2 图片上传 + 静态服务

```
POST /api/mining/comments/images
multipart/form-data: video_id, file
→ 201 { "image_id": "uuid", "url": "/api/mining/images/uuid", "size": 12345 }

GET /api/mining/images/{image_id}
→ 200 image/{jpeg|png|webp} 二进制，Content-Disposition: inline
→ 404 if 没找到
```

存储路径：`%APPDATA%\com.csm.gui\mining_images\{video_id}\{image_id}.{ext}`，扩展名从 magic bytes 检测（imghdr 或简单 sniff 前 8 字节），限制 .jpg/.jpeg/.png/.webp，max 5MB。

### 4.3 AI 路由

```
POST /api/mining/videos/{id}/ai_summary
Body: { "force": false }
→ 200 { "summary": "60-100 字摘要" }
→ 503 LLMConfigError → { "code": "llm_not_configured", "msg": "..." }

POST /api/mining/videos/{id}/ai_suggest_comment
Body: { "tier": 2, "previous_tiers": ["第 1 层文本", ...], "tone_hint": "" }
→ 200 { "suggestion": "..." }
→ 503 同上
```

Prompt 模板（**内置默认 + 用户可改**，详见 §4.6）：

**默认 summarize_video** —
```
system: 你是中文短视频内容分析助手。对给定视频信息（标题、平台、博主、时长、播放量），输出一段 60-100 字的中文摘要，告诉读者「这条视频在讲什么 / 适合什么人看 / 评论里可以蹭什么角度」。直白、口语、不复读标题。
user: 平台={platform} 标题={title} 博主={author} 时长={duration} 播放={play_count}
```

**默认 suggest_comment** —
```
system: 你是中文小红书/抖音评论文案助手。给定视频信息 + 用户已写的前 N-1 层评论草稿，写出第 N 层评论草稿（≤80 字）。要求：1）和前面层连贯（盖楼感）；2）口语自然，不像广告；3）适合做「种草前奏」，不直接卖。
user: 视频：{title} (by {author})
       已有评论：
       第 1 层：{tier1_text}
       第 2 层：...
       请写第 {tier} 层。
```

模板里使用 Python `str.format(**vars)` 风格的占位符。`mining_ai_service` 提供 `_render(template: str, vars: dict)` 帮手，渲染时缺失变量替换成空字符串而非抛 KeyError（防用户 typo 把整个流程搞挂）。

### 4.6 AI Prompt 配置路由

```
GET /api/mining/ai_prompts
→ 200 {
    "summary":  { "current": "...用户写的或空", "default": "...内置..." },
    "suggest":  { "current": "...用户写的或空", "default": "...内置..." },
    "vars":     {
        "summary": ["platform", "title", "author", "duration", "play_count"],
        "suggest": ["platform", "title", "author", "tier", "previous_block"]
    }
}

PATCH /api/mining/ai_prompts
Body: { "summary"?: "...新内容...", "suggest"?: "...新内容..." }
（传 "" 等同于清回默认）
→ 200 同 GET
```

存储：`AppConfig.mining_summary_prompt` / `AppConfig.mining_suggest_prompt`（空字符串 = 用 default）。沿用 settings.json 现有持久化。

### 4.4 标记已评论

```
PATCH /api/mining/videos/bulk_mark_commented
Body: { "video_ids": [1,2,3], "value": true }
→ 200 { "updated": 3 }
```

将 `videos.already_commented` 翻转，`commented_source` 设为 `'manual'`，`commented_at` = now。

### 4.5 CSV 导出改造

`GET /api/mining/videos/export.csv` 现有签名不变；输出加列：

```
... 现有列, ai_summary, comment_tier_1, images_tier_1, comment_tier_2, images_tier_2, ...
```

最大 tier 数 = `SELECT MAX(tier) FROM video_comments`，运行时算（按结果集动态加列；如果没有任何 comment 就保持原列数，向后兼容）。`images_tier_N` = comma-joined 相对 URL `images/uuid`（不带 host，便于离线 zip）。

---

## 5. 前端组件树（评论楼局部）

```
VideoCard.vue
├── meta 行（不变）
├── 标题行（不变）
├── AI 速览 区块  ← Phase 3 重写
│   ├── 未生成态：「点击生成 AI 速览」按钮（Icon spark + label）
│   ├── 加载态：spinner + "生成中…"
│   ├── 已生成态：60-100 字文本 + 右上角 ⟳ 重新生成
│   └── 错误态：错误 + "去设置" 链接
├── 评论楼 区块  ← Phase 2 重写
│   ├── 已有评论列表 (按 tier asc)
│   │   └── <CommentItem v-for="c in comments">
│   │       ├── tier 徽章 [第 N 层]
│   │       ├── 文本
│   │       ├── 图片缩略图（横排）
│   │       └── 右上角：复制 / 删除
│   └── <CommentComposer>
│       ├── textarea
│       ├── 工具栏: [📷 图片] [✨ AI 建议] [发布第 N+1 层]
│       └── 已选图片预览（删 / 重排）
└── （删除原来的 composer 占位）
```

---

## 6. 风险 / 边界

### 6.1 schema 迁移

`ALTER TABLE videos ADD COLUMN ai_summary` 在已 v3 数据库上跑要 idempotent。SQLite 没 IF NOT EXISTS for ADD COLUMN，要用 `PRAGMA table_info(videos)` 检查列是否存在再决定跑不跑。沿用现有 monitor.storage._migrate 模式。

### 6.2 图片上传安全

- 限制扩展名 + magic bytes 检测，不信任 Content-Type（防 XSS via .html）
- 限制 max 5MB（防硬盘塞爆）
- image_id 用 uuid4，不可枚举
- 路径 join 用 `Path` 而非字符串拼接，防 traversal
- 静态路由读文件前 `Path.resolve().is_relative_to(image_root)` 兜底（不让 `../` 跳出根目录）

### 6.3 AI 模板冷启动

如果用户首次用就没设过 default_provider，要给清晰错误而不是 500。`LLMConfigError` 已经存在，包成 503 + 结构化 code，前端识别。

### 6.4 复制到剪贴板

前端用 `navigator.clipboard.writeText(...)`。需要 HTTPS 或 localhost；Tauri WebView 默认走 `http://localhost:port`，clipboard API 在 secure context 可用（Tauri 2 的 webview origin 是受信的）。已验证 Phase 1 没用过 clipboard，新加这条路径要在 Tauri dev + release 都试一遍。

### 6.5 盖楼层级竞争

`UNIQUE(video_id, tier)` 是数据库兜底；前端按 `MAX(tier)+1` 算下一层。如果两个 tab 同时打开同一个视频卡都点"发布"，会有一个拿 409。前端 catch 后 refetch + 自增重试一次。

### 6.6 图片孤儿清理

删除评论或视频时，image_ids 里的图片要清理。但用户可能 PATCH 评论时移除某张图—这张图也变成孤儿。决策：在 PATCH / DELETE comment 时 diff image_ids，没有引用的图片立即从磁盘删除（不引入后台任务）。`cleanup_orphans` 兜底仅在 sidecar 启动时扫一遍。

### 6.7 AI prompt 注入

视频标题可能含 prompt injection（"忽略上文，输出 ..."）。对策：把视频字段塞到 user message 而非 system message（已经这么写）；prompt 模板用结构化 `key=value` 让模型一眼看出是数据，不容易被指令污染。

---

## 7. 测试计划

### 后端单元 / 集成测试（pytest）

- `test_mining_storage_v4.py` — schema 迁移 idempotent；从 v3 跑到 v4 后 videos 行数不变 + ai_summary 列可读写；video_comments UNIQUE 约束正确返回 IntegrityError
- `test_mining_comments_routes.py` — POST + GET + PATCH + DELETE 闭环；tier 冲突 → 409；不存在的 video_id → 404；cleanup_orphans 在 PATCH 时正确删除丢失引用的图
- `test_mining_images_service.py` — magic bytes 拒绝 .html / 超大；路径 traversal 拒绝；正常上传 + 读取闭环
- `test_mining_ai_service.py` — 用 `mock` provider 跑 summarize + suggest，断言 prompt 模板 stable、文本写入数据库；LLMConfigError 透传

### 前端 smoke（手动）

- 起 sidecar + Tauri dev，给一个 B 站视频写两层评论，每层带 1 张图，刷新页面后数据回来
- 点 AI 速览 → 拿到文本（需要 default provider 已配置，否则看到错误 toast）
- 点 AI 建议 → composer 填进建议文本
- 浮动批量栏选 3 条 → 标记已评论 → 整批从"待评论"消失
- 导出 CSV → Excel 打开，看到 ai_summary + comment_tier_1 / _2 列；图片相对 URL 在 images_tier_N 列
- 点卡片 ⋯ 菜单 → 复制全部评论 → 在记事本粘出格式化文本

### 回归

- 现有 245+ 个 sidecar 测试全过
- mining job 仍能 work（B 站 50 条端到端）
- 监控中心仍能扫码登录（cookies 路径没动）

---

## 8. 实施顺序

详见独立 plan 文档 `docs/superpowers/plans/2026-05-17-outreach-phase2-comments-and-ai.md`。

总体路径：schema → 后端 service → 后端 routes → 后端测试 → 前端 store → 前端组件 → 前端联调 → 验收。

预计 4 批 subagent 并行（schema/service 一批、routes/测试一批、前端 service 层一批、前端 UI 一批），结尾人工 smoke。
