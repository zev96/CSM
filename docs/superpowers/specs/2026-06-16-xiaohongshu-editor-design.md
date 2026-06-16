# 小红书图文笔记编辑器 — 设计稿

- 日期：2026-06-16
- 范围：全新独立模块「小红书」，对齐参考产品 reditorapp（reditorapp.com/dashboard）的 9 个面板：模版 / 主题 / 表情 / 标题 / 文案 / 话题 / 装饰 / 图片 / AI 助手。分 5 个阶段（P0–P4）交付，每阶段可单独跑通、单独验收。
- 目标用户场景：在本应用里排好一篇小红书图文笔记（图片 + 标题 + 正文 + 话题），实时预览成小红书卡片样式，然后**复制文案 / 存草稿**，自己去小红书 App 发布。

## 关键澄清（来自用户）

- **全功能克隆**：要做齐 reditorapp 的全部 9 面板，不是 MVP 子集。但按阶段交付。
- **导出 = 复制文案到剪贴板 + 应用内存草稿。不做「预览转 PNG」**。所以右侧手机预览是**纯展示**，不需要 DOM 转图能力（html2canvas 等一律不引）。
- **编辑器内核用轻量纯文本，不复用创作区的 Tiptap**。理由：小红书正文本质是纯文本（Emoji = Unicode、装饰符 = 特殊字符、无富文本格式、#话题是独立结构），纯文本模型让「一键复制」零损耗、字数统计准确、光标插入简单可靠。
- **起步素材由实现方撰写一套中文库**（模版/排版主题/标题公式/文案/话题/装饰/emoji 分组），随前端版本走。
- **表情与排版边界**（详见 §6）：
  - 标准 Unicode emoji + 排版预设 = 全做，纯内置，不爬任何站点。
  - 小红书官方专属贴纸（`[害羞R]` 类）= 只支持**文字代码**插入（发到小红书 App 会渲染成贴纸）；**不打包官方贴纸图片**（版权 / ToS），预览里显示代码占位 chip。
  - **不爬 reditorapp、不爬小红书**。
- **持久化沿用现有惯例**：草稿走 sidecar SQLite，图片走 sidecar 本地文件 + 静态路由（1:1 复刻 `mining_images_service` 已验证过的安全逻辑），AI 复用 `llm_factory`。

---

## 1. 范围

### P0 — 地基（in scope）

- 路由 `/xhs`（name `xhs`）+ 左侧导航新增「小红书」入口
- Pinia store `useXhs`：当前草稿 + 草稿列表 + 面板状态 + 素材库（懒加载）
- 三栏骨架：左素材面板（9 标签）/ 中编辑区 / 右手机预览
- **纯文本编辑器内核**：标题 `<input>` + 正文 `<textarea>` + 话题 chips；`insertAtCursor(text)` 在正文光标处插入并复位光标
- 字数计数：标题（软上限 20）、正文（软上限 1000），超限只提示不拦截
- 草稿持久化：`xhs_drafts` 表 + `/api/xhs/drafts` CRUD + 前端**去抖自动保存**
- **复制到剪贴板**：标题 / 正文 / 全文 各一个复制按钮
- 右侧预览（笔记页 / 发现页两个 tab）随编辑实时联动（P0 先用占位图，真实图在 P2 接）

### P1 — 文字素材面板（in scope）

- 6 个「点一下＝插入/应用」的面板，全部由打包 JSON 驱动（纯前端、零后端）：
  - **模版**：分类笔记模板，点击载入标题 + 正文 + 话题（编辑器非空时弹确认）
  - **表情**：两段式 —— 系统分组（色系 + 题材）+ 全量 Unicode 分类 + 小红书代码组；点击在正文光标处插入
  - **标题**：爆款标题公式模板（带 `xx` 占位），点击填入标题
  - **文案**：文案片段库（互动文案 / 个人简介 等组），点击光标处插入
  - **话题**：分类 #话题清单，点击加 chip（去重、去前导 #）
  - **装饰**：分割线 + 项目符号，点击光标处插入
- 排版主题面板的「应用排版主题」= 设定当前激活的小标题/无序/有序/分割线符号组，并在编辑器工具条提供这组符号的快捷插入按钮（主题面板归在「主题」标签下，§5）。P1 先放 2–3 套起步主题，P3 扩到 6–8 套色系

### P2 — 图片（in scope）

- 图片上传：`usePathPicker` 选文件 → 读字节 → `POST /api/xhs/drafts/{id}/images`（multipart）→ sidecar 落盘 + 返回 image_id/URL
- 图片管理：缩略图网格、拖拽排序、设封面（cover_index）、删除
- 预览显示真实图片（笔记页轮播首图 = 封面；发现页卡片 = 封面）

### P3 — 主题排版 + AI 助手（in scope）

- 排版主题预设完整化（多套色系，§5「主题」）
- AI 助手：
  - `POST /api/xhs/ai/generate`：输入意图/关键词 → 返回 `{title, body, topics[]}`，前端填入（不自动覆盖已有内容，先弹确认）
  - `POST /api/xhs/ai/polish`：把当前正文润色成小红书风（加 emoji 排版、口语化）→ 返回文本填回
  - 复用 `llm_factory.build_client()`；内置默认 prompt；未配置 LLM 时错误提示并链接到设置

### P4 — 自定义素材 + 打磨（in scope）

- 自定义素材：`xhs_custom_assets` 表 —— 「存为我的模版」「自定义文案」「自定义话题分组」，运行时与起步素材合并显示
- AI prompt 可在设置里自定义（仿 `MiningPromptsCard`，AppConfig 加 `xhs_generate_prompt` / `xhs_polish_prompt`）
- 打磨：字数超限提示、空状态、emoji 字体一致性（§6）、键盘焦点、草稿列表管理（重命名/删除/复制副本）

### out of scope（明确不做）

- **不做预览导出图片（PNG）** —— 用户已确认
- **不做真发布到小红书** —— 无公开发布 API
- **不打包小红书官方贴纸图片** —— 版权 / ToS（仅支持文字代码）
- **不爬取 reditorapp / 小红书** —— 法务 + ToS，且无必要
- **不做视频笔记** —— 仅图文
- **不做云存储 / 多端同步 / 协作**
- **不复用 Tiptap**（见关键澄清）

### 验收标准（分阶段，见 §7 每阶段细化）

- 总验收：`vue-tsc -b && vite build` 零错零警告；新增 sidecar 测试全过（schema 迁移 + draft CRUD + 图片存取 + AI service mock）；全程不联网即可完成 P0–P2（AI 在 P3 才需 LLM）。

---

## 2. 文件清单

### 后端新增

- **xhs 持久化模块**（仿 `csm_core/mining/storage.py` 模式）：独立 `xhs.db` + `xhs_drafts` 表 + schema 版本/迁移 + CRUD（`create_draft` / `get_draft` / `list_drafts` / `update_draft` / `delete_draft`）。P4 加 `xhs_custom_assets` 表。
- `sidecar/csm_sidecar/services/xhs_images_service.py` —— 新建，**1:1 仿 `mining_images_service.py`**：`save_image(draft_id, content) -> image_id`（magic-byte 校验 jpeg/png/webp + 5MB 上限）、`get_image_path(image_id)`（含 `..` 越界防护）、`delete_images(ids)`。落盘 `core_config.default_config_dir() / "xhs_images" / {draft_id} / {uuid}.{ext}`。
- `sidecar/csm_sidecar/services/xhs_ai_service.py` —— 新建（P3）：`generate_note(intent) -> dict` + `polish_note(text) -> str`，装饰 `llm_factory.build_client()` + 内置 prompt。
- `sidecar/csm_sidecar/routes/xhs.py` —— 新建，挂这些路由：
  - `GET /api/xhs/drafts`、`POST /api/xhs/drafts`、`GET /api/xhs/drafts/{id}`、`PATCH /api/xhs/drafts/{id}`、`DELETE /api/xhs/drafts/{id}`
  - `POST /api/xhs/drafts/{id}/images`（multipart）、`GET /api/xhs/images/{image_id}`（静态 FileResponse）
  - `POST /api/xhs/ai/generate`、`POST /api/xhs/ai/polish`（P3）
  - `GET/PATCH /api/xhs/ai_prompts`（P4，仿 mining_ai_prompts）
- `sidecar/csm_sidecar/main.py` —— 注册 xhs router。
- `sidecar` PyInstaller spec —— 确认新模块/数据文件被收（参考既有 `collect_data_files` catch-all；本模块无 .graphql/数据文件，主要是 .py，常规收即可）。

### 后端不动

- 现有 article / mining / monitor / templates 路由与存储（小红书模块完全独立，不碰它们的表）

### 前端新增

- `frontend/src/views/XhsEditorView.vue` —— 三栏主视图
- `frontend/src/components/xhs/` —— 面板与子组件：
  - `PanelRail.vue`（9 标签切换）
  - `panels/TemplatePanel.vue` / `ThemePanel.vue` / `EmojiPanel.vue` / `TitlePanel.vue` / `CopyPanel.vue` / `TopicPanel.vue` / `DecorationPanel.vue` / `ImagePanel.vue` / `AiPanel.vue`
  - `NoteEditor.vue`（标题 + 正文 textarea + 工具条 + 话题 chips + 字数）
  - `PhonePreview.vue`（笔记页 / 发现页两 tab）
- `frontend/src/stores/xhs.ts` —— `useXhs` Pinia store
- `frontend/src/composables/useCursorInsert.ts` —— textarea 光标插入/复位
- `frontend/src/data/xhs/*.json` —— 起步素材：`templates.json` / `themes.json` / `emoji.json` / `titles.json` / `copy.json` / `topics.json` / `decorations.json`
- （可选 P4）`frontend/src/components/settings/XhsPromptsCard.vue`

### 前端改动

- `frontend/src/router/index.ts` —— 加 `/xhs` 路由
- `frontend/src/components/LeftNav.vue` —— `NAV_TOP` 加 `{ key: "xhs", icon: "notebook", label: "小红书" }`
- `frontend/src/components/ui/Icon.vue` —— 若无 `notebook`/`book` 图标则新增一个

---

## 3. 数据模型

### 3.1 草稿表 `xhs_drafts`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | uuid4 hex |
| `title` | TEXT | 标题（纯文本，含 emoji） |
| `body` | TEXT | 正文（纯文本，含 emoji / 换行 / 装饰符） |
| `topics_json` | TEXT | 话题数组 JSON，元素不含前导 `#` |
| `image_ids_json` | TEXT | 有序 image_id 数组 JSON |
| `cover_index` | INTEGER | 封面在 image_ids 中的下标，默认 0 |
| `theme_id` | TEXT | 当前激活排版主题 id（可空） |
| `created_at` | TEXT | ISO8601 |
| `updated_at` | TEXT | ISO8601 |

### 3.2 图片

- 存储：`%LOCALAPPDATA%\CSM-Data\xhs_images\{draft_id}\{image_id}.{ext}`
- 安全：magic-byte 嗅探（仅 jpeg/png/webp）、5MB 上限、uuid 不可枚举、`get_image_path` 解析后校验仍在 `xhs_images` 根内（防 `..` 穿越）—— 全部沿用 `mining_images_service` 的实现。
- 前端取图：`sidecar.sseURL("/api/xhs/images/{id}")` 拼完整 localhost URL（同 mining 缩略图惯例）。

### 3.3 起步素材 JSON 结构（前端打包，`frontend/src/data/xhs/`）

```jsonc
// templates.json
[{ "id": "t_zhishi_01", "category": "知识技能", "name": "考证攻略",
   "title": "各类国家考试报考日期合集｜必须收藏✨",
   "body": "今天我们就来看看…\n💛 2024年上半年\n▪️ 四六级笔试：6月15日\n…",
   "topics": ["考证", "大学生", "干货"] }]

// themes.json  —— 排版主题（emoji 结构符号套装）
[{ "id": "warm_yellow", "name": "温暖黄",
   "heading": "💛", "bullet": "🔸", "ordered": "emoji",      // emoji|circle|superscript
   "divider": "✨━━━━━━✨" }]

// emoji.json
{ "curatedGroups": [{ "key": "warm", "name": "温暖黄", "emojis": ["💛","🌟","🔆","🍯"] },
                    { "key": "food",  "name": "美食探店", "emojis": ["🍰","☕","🍜"] }],
  "unicodeGroups": [{ "key": "smileys", "name": "笑脸", "emojis": ["😀","😄","🥰", "…"] }],
  "xhsCodes":     [{ "code": "[害羞R]", "label": "害羞" }, { "code": "[偷笑R]", "label": "偷笑" }] }

// titles.json
{ "categories": [{ "key": "hot", "name": "爆款通用",
   "items": ["99%不知道的xx，让你xxx！", "保姆级xx教程，谁还不会", "我宣布xx就是无敌"] }] }

// copy.json
{ "groups": [{ "key": "interact", "name": "互动文案",
   "items": ["喜欢我就点个赞，收藏加关注哦😋", "❤️ 喜欢就点赞｜收藏｜关注我吧"] }] }

// topics.json
{ "groups": [{ "key": "hot", "name": "热门", "tags": ["每日穿搭", "好物分享", "干货分享"] }] }

// decorations.json
{ "groups": [{ "key": "divider", "name": "分割线", "items": ["✨━━━━✨", "· · · · · ·", "▶▷▶▷▶▷"] },
             { "key": "bullet",  "name": "项目符号", "items": ["▪️", "🔸", "◦", "✅", "👉"] }] }
```

### 3.4 自定义素材 `xhs_custom_assets`（P4）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | uuid |
| `kind` | TEXT | `template` / `copy` / `topic_group` |
| `payload_json` | TEXT | 与对应起步素材同形状的单条记录 |
| `created_at` | TEXT | ISO8601 |

运行时：`合并素材 = 起步 JSON + custom_assets`，custom 标「我的」分组。

---

## 4. 架构与数据流

### 4.1 三栏布局

- 左 `PanelRail`（~190px）：9 个 icon+label 标签，点击切换右下内容区面板。
- 中 `NoteEditor`（flex-1）：图片条（P2 起）→ 标题输入（带计数）→ 工具条（当前排版主题的快捷符号 + emoji 快捷）→ 正文 textarea（带计数）→ 话题 chips。
- 右 `PhonePreview`（~184px）：笔记页 / 发现页切换，读 store 实时渲染。

### 4.2 编辑器内核（光标插入）

- `useCursorInsert(textareaRef)` 暴露 `insert(text)`：取 `selectionStart/End` → 用 text 替换选区 → 更新 `body` → `nextTick` 后把光标设到插入串末尾并重新 focus。
- 所有「点素材插入」（emoji / 装饰 / 文案 / 主题符号）都走这一个入口。
- 标题模板 → 直接 set 标题值（不走光标）；话题 → push 进 topics 数组。
- 字数：`[...str].length`（emoji 计 1）。超软上限时计数变红 + 提示，不阻止输入。

### 4.3 预览联动

- `PhonePreview` 是纯 computed 渲染：
  - 笔记页：头像 + 昵称 + 关注（红色 pill，模拟小红书）+ 封面图（无图用占位）+ 标题 + 正文（`white-space: pre-wrap` 保换行 + emoji）+ 话题蓝色 #tag + 假互动栏。
  - 发现页：瀑布流卡片（封面 + 标题两行截断 + 头像昵称 + 假点赞数）。
- emoji 渲染依赖系统 Segoe UI Emoji（WebView2 自带彩色字形）；§6 评估是否打包 Twemoji 兜底。

### 4.4 复制到剪贴板

- 标题复制 = `title`；正文复制 = `body`；全文复制 = `title + "\n\n" + body + "\n\n" + topics.map(t => "#"+t).join(" ")`。
- 用 `navigator.clipboard.writeText`，成功 toast「已复制」。

### 4.5 自动保存

- `body/title/topics/images/cover/theme` 变化 → 去抖 800ms → `PATCH /api/xhs/drafts/{id}`。
- 首次有内容（标题或正文非空）时 `POST` 建草稿拿 id，避免空草稿堆积。草稿列表入口在视图顶部（「我的草稿」下拉/抽屉）。

### 4.6 AI（P3）

- `xhs_ai_service` 复用 `llm_factory.build_client()`（与「文章润色」同一套设置）。
- `generate`：prompt 引导输出 JSON（title/body/topics），service 端解析；解析失败兜底为纯文本填正文。
- `polish`：输入正文 → 输出小红书风正文（emoji 分点、口语化、结尾引导）。
- 错误兜底：未配置 default provider → toast「请先在设置中配置 AI 服务」+ 跳 settings。

---

## 5. 9 面板详细规格

| 面板 | 数据源 | 交互 | 起步素材量 |
|---|---|---|---|
| **模版** | `templates.json` | 顶部分类 tab（出行/户外/美妆/穿搭/读书/知识技能/创业/时尚探店…）；卡片点击 → 载入 title+body+topics（编辑器非空弹确认覆盖） | 8 分类 × 3–5 |
| **主题** | `themes.json` | 多套排版预设卡（小标题/无序/有序/分割线），每卡带样例预览；点击 = 设为激活主题，编辑器工具条出现这套快捷符号 | 6–8 套色系 |
| **表情** | `emoji.json` | 系统分组（色系/题材）+ 全量 Unicode 分类（标准 picker 分类条）+「小红书代码」组；点击插入正文 | 数百 Unicode + 常用代码 |
| **标题** | `titles.json` | 分类 tab（爆款通用/互动/女生/旅行/好物美妆/母婴）；条目点击填入标题（保留 `xx` 让用户替换） | 6 分类 × 10+ |
| **文案** | `copy.json` | 系统文案（互动文案/个人简介）+（P4）自定义；点击光标处插入 | 40–60 条 |
| **话题** | `topics.json` | 热门 + 分类；点击加 chip；（P4）自定义话题分组 + 「全部添加」 | 100+ |
| **装饰** | `decorations.json` | 分割线 / 项目符号分组；点击光标处插入 | 30–40 |
| **图片** | sidecar | 上传 / 缩略图 / 拖拽排序 / 设封面 / 删除（P2） | — |
| **AI 助手** | sidecar LLM | 生成整篇 / 润色当前（P3） | — |

---

## 6. 表情与排版：采集与版权边界

- **标准 Unicode emoji**：整理成 `emoji.json` 内置清单，不爬任何站点。色系分组（温暖黄/天蓝蓝/深情红…）与题材分组（美食探店/阅读手帐/出行户外/穿搭/运动）都是对 Unicode 子集的人工归类。
- **排版主题（小红书风排版）**：核心就是用 emoji 当结构符号（小标题符号 / 无序列表符号 / 有序列表样式 / 分割线），全部 Unicode，做成 `themes.json` 预设 + 工具条一键插入。这是价值最大、最容易的部分。
- **小红书官方专属贴纸（`[害羞R]` 类）**：
  - 支持：内置常用**文字代码**清单（`xhsCodes`），点击在正文插入代码；用户复制发到小红书 App 会渲染成贴纸。
  - 不支持：**不打包官方贴纸图片**（版权 / ToS）。预览里这类显示为代码占位 chip（如 `[害羞]` 小药丸），非真实贴纸图。
  - 扩展位：「代码 → 图片」显示机制做好；若用户**自行提供**贴纸图素材（放约定目录），预览可点亮 —— 默认不附带。
- **emoji 字体一致性**：默认依赖 WebView2 的 Segoe UI Emoji 彩色字形（Win11 自带，编辑器与预览都能正常显示）。P4 评估是否打包 Twemoji（CC-BY）/ Noto Color Emoji（OFL）作跨字体一致性兜底，解决个别缺字「豆腐块」。
- **合规**：不抓取 reditorapp（登录墙 + 竞品内容）、不抓取小红书。素材全部为内置 Unicode 清单 + 自撰中文文案/标题/话题。

---

## 7. 分阶段交付计划

每阶段产出一份独立实现计划（经 writing-plans），独立提 PR、独立验收。

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0 地基** | 路由+导航+store+三栏骨架+纯文本编辑器+字数+草稿 CRUD+自动保存+复制+预览联动（占位图） | 新建草稿 → 写标题/正文 → 加话题 → 右侧预览实时更新 → 复制全文粘出格式化文本 → 刷新页面草稿回来 |
| **P1 文字素材面板** | 模版/表情/标题/文案/话题/装饰 6 面板（JSON 驱动）+ 排版主题快捷插入 | 每个面板点击都能正确插入/应用；模版载入弹确认；话题去重；正文光标插入位置正确 |
| **P2 图片** | 上传/排序/封面/删除 + 预览显示真实图 | 上传 jpg/png/webp → 缩略图 → 排序 → 设封面 → 预览封面更新 → 刷新后图片仍在；超 5MB / 非图片被拒 |
| **P3 主题+AI** | 排版主题完整化 + AI 生成/润色 | 选主题后工具条符号切换；AI 生成出 title/body/topics 填入；AI 润色把朴素正文变小红书风；未配置 LLM 给出跳设置提示 |
| **P4 自定义+打磨** | 自定义素材 + AI prompt 设置 + 字数超限/空状态/草稿管理/emoji 字体 | 存为我的模版 → 模版面板「我的」出现；自定义话题分组；超限提示；草稿列表增删改 |

> P0+P1 完成即得到可用编辑器（文字笔记 + 全部文字素材 + 实时预览 + 复制/存草稿），是功能价值的大头。

---

## 8. 风险与决策

- **素材内容工作量**：起步素材（模版/标题/文案/话题/装饰/emoji 分组）是隐藏的大头，分摊在 P1/P3。先做「合理规模」起步库，质量优先于数量。
- **sidecar 打包风险**：本模块新增的是常规 .py + 一个静态图片目录，无 .graphql 这类易漏数据文件；但发版前仍按既有教训本地 `npx npm@10 ci` + sidecar 测试 + spec 收文件确认。
- **图片孤儿清理**：删草稿时级联删 `xhs_images/{draft_id}/`；删单图时 `delete_images`。不做跨草稿引用计数（每草稿图独立）。
- **emoji 计数口径**：用 `[...str].length`（码点），与小红书官方计数可能有个位数差异，作为软提示可接受。
- **编辑器内核**：纯 textarea 不支持「行内彩色 chip 预览」（如把 `[害羞R]` 现场渲染成图）。这是选纯文本模型的已知取舍 —— 行内所见即所得放预览面板承担，编辑区保持纯文本。
- **不复用现有模板系统**：现有 `/api/templates` 是为长文 block（HeadingBlock/ParagraphBlock…）设计，与小红书「整篇示例 + 占位」模型不匹配，故 xhs 模版另起 JSON，不强行复用。
