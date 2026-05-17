# Outreach 评论楼 + AI（Phase 2 + Phase 3）— 实施计划

- spec：`docs/superpowers/specs/2026-05-17-outreach-phase2-comments-and-ai-design.md`
- 总任务数：16
- 执行方式：subagent 4 批并行（按依赖分批）
- 验收：所有 sidecar 测试通过 + 手动 smoke 跑过本文末 10 条用例

---

## 批次拆分

| 批 | 任务 | 依赖 | 备注 |
|---|---|---|---|
| 批 1 | T1, T2, T3, T3b | 无 | 后端：schema 迁移 + image service + AI service + prompt config |
| 批 2 | T4, T5 | 批 1 | 后端：comment storage 函数 + routes + 测试 |
| 批 3 | T6, T7, T8 | 批 1 | 前端 store + 通用组件 |
| 批 4 | T9, T10, T11, T11b | 批 2 + 批 3 | 前端 UI 联调 + 设置页 prompt 卡片 |
| 收尾 | T12, T13, T14 | 全部 | CSV 改造 + smoke + commit |

---

## 任务清单

### T1 — DB schema v4 迁移
**文件**：`csm_core/mining/storage.py`、`csm_core/monitor/storage.py`（_migrate 加一行）
**做**：
- 加 `_DDL_V4_MINING`（CREATE TABLE video_comments + UNIQUE 索引）
- 加 `apply_v4_migration(conn)`：跑 CREATE TABLE；用 `PRAGMA table_info(videos)` 判断是否已有 `ai_summary` 列，没有就 `ALTER TABLE videos ADD COLUMN ai_summary TEXT`
- 在 monitor.storage._migrate 加 v3 → v4 分支调 apply_v4_migration
- bump CURRENT_SCHEMA_VERSION（搜确切位置）
**验收**：从 v3 库升到 v4 后 videos 行数不变 + video_comments 表存在 + 重复跑 idempotent

### T2 — mining_images_service
**文件**：`sidecar/csm_sidecar/services/mining_images_service.py`（新建）
**做**：
- `image_root()` → `Path(appdirs.user_data_dir("com.csm.gui")) / "mining_images"`
- `save_image(video_id: int, content: bytes, declared_ext: str) → str`（返回 image_id）
  - magic bytes 检测真实类型（jpeg/png/webp），不匹配 → raise ValueError
  - 写到 `{image_root}/{video_id}/{uuid}.{ext}`，返回 uuid
- `get_image_path(image_id: str) → Path | None`：扫 image_root（暴力遍历可以，sidecar 内只有自己用；后续要快再加索引文件）；`resolve().is_relative_to(image_root.resolve())` 兜底
- `delete_images(image_ids: list[str])`：用于评论 PATCH/DELETE 时清理
- 不引入 cleanup_orphans 后台任务，那条留到下次

### T3 — mining_ai_service
**文件**：`sidecar/csm_sidecar/services/mining_ai_service.py`（新建）
**做**：
- import `llm_factory`、`mining/storage`、`config_service`
- 模块顶部定义 `DEFAULT_SUMMARY_PROMPT_SYSTEM` / `..._USER`、`DEFAULT_SUGGEST_PROMPT_SYSTEM` / `..._USER`（spec §4.3 那两段）
- `_render(template: str, vars: dict) → str`：用 `str.format_map(_SafeDict(vars))`，缺失键填空字符串
- `summarize_video(video_id: int, force: bool = False) → str`
  - 从 DB 查视频字段
  - 如果 `not force and videos.ai_summary` 已有值 → 直接返回
  - 从 `config_service.load().mining_summary_prompt` 读用户自定义；空字符串则用默认。约定：用户自定义如果只是一行就当作 system，整段含 `---user---` 分隔符则切两部分
  - `client = build_client()` + `client.complete(system, user)`
  - `storage.set_ai_summary(video_id, text)` + 返回
- `suggest_comment(video_id: int, tier: int, previous_tiers: list[str], tone_hint: str = "") → str`
  - 同样 build_client + 模板 + complete + 直接返回（不落库，留前端选择是否保存）
  - vars 里 `previous_block` 是 previous_tiers 渲染好的多行字符串
- 通过 `LLMConfigError` 抛出未配置情况

### T3b — Prompt 配置存储 + 路由
**文件**：`csm_core/config.py`、`sidecar/csm_sidecar/services/config_service.py`、`sidecar/csm_sidecar/routes/mining.py`
**做**：
- `AppConfig` dataclass 加 `mining_summary_prompt: str = ""` / `mining_suggest_prompt: str = ""`
- `config_service.save_partial(...)` 支持这两个字段（沿用现有 partial-update 机制）
- 加路由：
  - `GET /api/mining/ai_prompts` → 返 spec §4.6 的结构（current + default + vars 列表）
  - `PATCH /api/mining/ai_prompts` → body `{ summary?, suggest? }`，写 AppConfig，返新结构
- DEFAULT_* 常量从 `mining_ai_service` import 过来，单一来源

### T4 — comment storage 函数
**文件**：`csm_core/mining/storage.py`（追加）
**做**：
- `create_comment(video_id, tier, text, image_ids, source='manual') → int`
- `list_comments(video_id) → list[dict]`（按 tier asc，image_ids 解 JSON）
- `update_comment(comment_id, text=None, image_ids=None, status=None) → dict | None`
  - 内部 diff 旧 image_ids 和新 image_ids，调用 `mining_images_service.delete_images(removed_ids)`
- `delete_comment(comment_id) → bool`（同样 delete 之前先回收图片）
- `set_ai_summary(video_id, text) → None`
- `bulk_mark_commented(video_ids: list[int], value: bool) → int`
- `next_tier(video_id) → int`（`SELECT COALESCE(MAX(tier), 0) + 1 ...`，供路由用，不强求前端算）

### T5 — comment / image / AI routes
**文件**：`sidecar/csm_sidecar/routes/mining.py`（追加路由）
**做**：
- 实现 spec §4.1 / §4.2 / §4.3 / §4.4 全部 9 个新路由
- 静态路由 `GET /api/mining/images/{image_id}` 用 FastAPI `FileResponse`（content_type 从扩展名）
- multipart upload 用 `UploadFile`；先读到内存，过 magic bytes，写文件
- `LLMConfigError` catch → 503 + `{"code": "llm_not_configured", "detail": "..."}`
- 在 v3 / v4 都能 work（如果 video_comments 表缺失，sidecar 启动迁移已经创建）

**测试**：在 `sidecar/tests/` 加 `test_mining_comments_routes.py`、`test_mining_images_service.py`、`test_mining_ai_service.py`（用 `mock` provider）。最少覆盖每条路由的 happy + 一个错误。

### T6 — Pinia store 扩展
**文件**：`frontend/src/stores/mining.ts`
**做**：加 actions：
- `loadComments(videoId)` → 写到 store 的 `commentsByVideo: Record<number, Comment[]>`
- `createComment(videoId, payload)`
- `updateComment(commentId, payload)`
- `deleteComment(commentId)`
- `summarize(videoId, force?)` → 更新 store 里对应 video 的 `ai_summary`
- `suggestComment(videoId, tier, previousTiers)` → 返回字符串（不写 store）
- `uploadImage(videoId, file)` → 返回 { image_id, url }
- `bulkMarkCommented(ids, value)` → 调 API + 本地刷新 videos
- type 定义：`Comment { id, tier, text, image_ids, image_urls, status, source, created_at }`

### T7 — CommentItem.vue
**文件**：`frontend/src/components/mining/CommentItem.vue`（新建）
**做**：
- props: `comment: Comment`, `videoId: number`
- emits: `delete`, `copy`
- 设计：tier 徽章（圆角小标签 + 渐变背景）+ 文本（白底卡）+ 图片缩略图横排（48×48 圆角，点击放大 modal 暂时不做，先 `<a target="_blank">` 看原图） + 右上角复制 / 删除按钮
- 复制：`navigator.clipboard.writeText(text)` + emit `copy`（toast 在父级展示）

### T8 — CommentComposer.vue
**文件**：`frontend/src/components/mining/CommentComposer.vue`（新建）
**做**：
- props: `videoId: number`, `nextTier: number`, `previousTiers: string[]`
- emits: `saved`（创建成功时；父级 reload）
- 内部 state：text、imageIds、imageUrls、isUploading、isSuggesting
- UI:
  - textarea（autosize）
  - 工具栏：📷 图片按钮（触发 `<input type=file>`，多选）、✨ AI 建议按钮（loading 时禁用）、发布第 N+1 层按钮（右侧，主色调）
  - 已选图片预览：横排缩略图 + ✕ 删除
- AI 建议：调 `store.suggestComment(...)` → 拿到字符串塞 textarea
- 保存：调 `store.createComment(...)` → 清空 → emit saved

### T9 — VideoCard.vue 接评论楼
**文件**：`frontend/src/components/mining/VideoCard.vue`
**做**：
- 替换"评论楼占位"区块为 `<CommentItem v-for>` + `<CommentComposer>`
- 替换"composer 占位"区块 → 删除（composer 现在在评论楼里）
- 卡片 ⋯ 菜单加"复制全部评论"项；点击拼接 `[第 N 层] text\n` 复制
- onMount / 评论数变化时 trigger `store.loadComments(videoId)`
- 计算 nextTier = max(existing tiers) + 1，传给 composer

### T10 — VideoCard.vue 接 AI 速览
**文件**：`frontend/src/components/mining/VideoCard.vue`（继续）
**做**：
- 替换"AI 速览占位"区块为 3 态切换：
  - `v.ai_summary` 为空 + 非 loading：「点击生成」按钮
  - loading：spinner
  - 已生成：文本 + ⟳ 重新生成
- 点击触发 `store.summarize(videoId)`；错误 toast "请先在设置中配置 AI 服务" + 跳 settings 链接

### T11b — MiningPromptsCard（设置页）
**文件**：`frontend/src/components/settings/MiningPromptsCard.vue`（新建）、`frontend/src/views/SettingsView.vue`（挂载）
**做**：
- 卡片标题 "Outreach AI 提示词"
- 两个 textarea（autosize，min 4 行）：AI 速览 prompt / AI 建议 prompt
- 每个 textarea 上方显示"可用占位符：{title} {author} ..."
- 每个 textarea 下方：[保存] [重置为默认]
- "重置为默认"按钮 PATCH `""` 让 backend 回 default；保存后 reload current/default 对比
- onMounted GET `/api/mining/ai_prompts` 灌满

### T11 — MiningView 浮动批量栏接 API
**文件**：`frontend/src/views/MiningView.vue`
**做**：
- "标记已评论"按钮去 disabled，点击调 `store.bulkMarkCommented(Array.from(selected.value), true)`
- "全部打开"按钮点击循环 `window.open(v.url, '_blank')`（已经 active 了，确认 work）
- "导出选中"按钮去 disabled，调 `store.exportUrl({ ids: [...] })`（路由侧加 `ids` 参数支持）→ 直接 `window.location = url`

### T12 — CSV 导出加 ai_summary + comment 列
**文件**：`sidecar/csm_sidecar/routes/mining.py` 现有 `export_csv` 函数
**做**：
- 算 `max_tier = SELECT MAX(tier) FROM video_comments WHERE video_id IN (...)`，没有就 0
- 表头追加 `ai_summary, comment_tier_1, images_tier_1, ..., comment_tier_{max_tier}, images_tier_{max_tier}`
- 数据行：JOIN video_comments 拉评论，按 tier 填入对应列
- 加 `?ids=1,2,3` 选择性导出（兼容现有所有过滤参数）

### T13 — Toast 组件 + 联调
**文件**：`frontend/src/components/ui/Toast.vue`（新建）、`frontend/src/main.ts`（挂载）
**做**：
- 轻量 toast：固定底部居中，3 秒淡出
- 暴露 `useToast()` composable：`success(msg)` / `error(msg)`
- 接到所有需要反馈的地方（复制成功、AI 失败、保存成功、删除成功）

### T14 — 验收 + commit + push
**做**：
- 启 sidecar + Tauri dev，跑 9 条 smoke 用例（见下文）
- `pnpm -C frontend exec vue-tsc -b`、`pnpm -C frontend build`
- `cd sidecar && python -m pytest -q`
- commit `feat(outreach): Phase 2 评论楼 + Phase 3 AI 速览/建议`
- push 到现有分支 + 顺手在 PR #26 加 review note

---

## Smoke 用例

1. 起 mining job，等 B 站 50 条进来
2. 选 1 条，写第 1 层评论 + 1 张图，保存。刷新页面，评论 + 图能看到
3. 同条加第 2 层评论 + 2 张图，保存。第 2 层在第 1 层下方，tier 徽章正确
4. 删除第 2 层的某张图，PATCH 后刷新，图片在磁盘上也没了（check 文件系统）
5. 点 AI 速览生成 → 出 60-100 字摘要；刷新页面摘要还在；点 ⟳ 重新生成
6. composer 点 AI 建议 → textarea 填进建议文案（带前面层上下文）
7. 浮动批量栏选 3 条 → 标记已评论 → 从待评论 tab 消失
8. 复制单条评论 → 记事本粘 OK；复制全部评论 → 拿到带 [第 N 层] 前缀的多行
9. 导出 CSV → Excel 打开看到 ai_summary + comment_tier_1 / 2 列 + images_tier_1 / 2 列
10. 设置页改 AI 速览 prompt（比如加"加上 emoji"），保存。回 MiningView 重新生成速览，新摘要带 emoji；点"重置为默认"后再生成，恢复无 emoji 风格

---

## 风险 watchlist（实施期间留意）

- SQLite ALTER TABLE 在 monitor / mining 同进程共享 conn 时是否需要锁（既有 WAL 应该 OK，但确认一下）
- `navigator.clipboard.writeText` 在 Tauri WebView 是否可用（dev OK 不代表 release OK）
- 现有 245+ 测试里有 schema 相关的，bump 版本会不会破老 fixture（重 setup_db()）
- AI 调用慢（>5s）时 spinner 体验 — 暂不流式，先看实测
