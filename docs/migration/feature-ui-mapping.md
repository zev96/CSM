# 功能 ↔ UI 对齐表（A2 终版）

> **状态：用户已拍板，可作为 A3 sidecar API 设计的输入。**
>
> 本表交叉对照 [csm_core/](../../csm_core/) 全部公开能力 × CSM-RE1 V1 原型
> 7 个屏幕的全部需求。原则：
> - **绝不动 `csm_core/`** 一行业务代码（仅 monitor/scheduler.py 的 QTimer 替换为 APScheduler）。
> - UI 上保留的视觉元素，若 csm_core 不直接支持，由 sidecar 现场算/适配。
> - csm_core 完全不支持且 sidecar 也无法廉价补足的，砍掉或进 v2 backlog。

## 图例

- ✅ —— 设计与代码已对齐，直接翻译。
- ⚠️ —— `csm_core` 有能力，原型未提供入口，或入口位置不清。**推荐补到某屏**。
- ❌ —— 原型有功能，`csm_core` 不支持。**推荐砍或简化**，决不 mock 假能力。
- 🔄 —— 命名/数据结构不一致。以 `csm_core` 字段为准，前端做适配。

---

## 一、模块视角：csm_core 每个能力归属哪屏

| `csm_core` 模块 | 关键接口 | 落点屏幕 | 判定 | 处置说明 |
|---|---|---|---|---|
| `llm/` | `make_client(provider)`、`LLMClient.complete(system, user, temperature)` | settings（Provider 卡）、article（模型徽章） | ✅ | provider 枚举完全匹配（mock/anthropic/deepseek/openai/gemini/qwen） |
| `pipeline.py` | `generate(req, on_stage)`，6 阶段：扫描资料库→加载模板→采样 blocks→组装 prompt→调用 LLM→导出 | home（关键词起飞）、article（重新随机）、batch（每条任务） | ✅ | `on_stage` 直接做 SSE 推送 |
| `assembler/` | `assemble_plan`、`compose_draft`、`reroll_pick(plan, block_id, pick_index, ...)` | article（组装预览左侧槽位列表 + 「重随」按钮） | ✅ | `BlockResult.kind` 枚举 7 种与 article 屏槽位卡显示一致 |
| `title/` | `generate_titles(keyword, llm, vault_root, template_type) → list[str]`（约 3 候选） | article（DocHeaderBar 应加「换标题」按钮） | ⚠️ | **推荐补**：article 标题点击展开候选列表 |
| `monitor/platforms/` | `fetch(task) → MonitorResult` × 4 平台 | monitor（知乎/B站/抖音/快手 tab） | ✅ | 平台代码与 UI tab 一一对应 |
| `monitor/scheduler.py` | `parse_schedule`、`is_task_due`、`select_due` | sidecar 内部（启动后台轮询） | ✅ | UI 不直接调，仅显示「检查频率」配置 |
| `monitor/rate_limit.py` | `slot()`、`RequestPacer`、`CircuitBreaker`、Cookie 池 | （内部）| ✅ | UI 仅 settings 显示 Cookie 池状态 |
| `dedup/` | `DedupAnalyzer.build_index(progress_cb)`、`analyze(text) → DuplicateReport`（含 `top_matches` + `hits` 段落级命中） | article（质检报告 + **新增查重明细抽屉**）、settings（历史/Vault 索引重建） | ⚠️ | **推荐补**：article 屏右侧质检卡里"重复率"数字可点击 → 滑出查重命中段落抽屉，复用 `DuplicateReport.hits` 的 `start/end/source_excerpt` |
| `template/` | `load_template`、`save_template`、`list_templates`、7 种 Block kind | templates、template-builder | ✅ | template-builder 的 7 种块 picker 与 schema 完全对应 |
| `vault/` | `scan_vault(root) → VaultIndex`、`ParsedNote.variants`（按 ①②③ 切分） | settings（vault 根目录）、home（最近文档间接依赖）、template-builder（NotesQuerySource 选模块） | ✅ | scan 是长任务（vault 大小 × 0.01–0.05s/note），需进度回调（A3 决定是否加 progress_cb） |
| `export/` | `export_article(out_dir, keyword, final_text, plan, fmt)`，`ExportFormat: "markdown" \| "docx"` | article（导出弹层）、batch（自动写盘）、settings（默认格式） | 🔄 | **见下方"格式枚举"决策点** |
| `batch/` | `run_batch(keywords, ..., on_item_started, on_item_finished, should_cancel)`，`BatchItem.status: "success" \| "failed"` | batch 屏 | 🔄 | UI 状态枚举 `done/running/queued` 比 csm_core 多两态——running 由 `on_item_started` 推断、queued 由"未触发 started"推断；前端在 store 里合成 |
| `updater_client/` | `check_for_update`、`download_with_verification(progress_cb, is_cancelled)` | settings（关于 → 检查更新）、Tauri 主壳（自动更新提示） | ✅ | progress_cb 走 SSE |
| `config.py` | `AppConfig`、`get_secret/set_secret/delete_secret` | settings 全屏 | ✅ | A1 已新建 |

---

## 二、屏幕视角：每屏的需求 → 代码支持情况

### 1. home 工作台（[src/screens/home.jsx](../../../../CSM-RE1（V1）/src/screens/home.jsx)）

| 区块/功能 | 数据需求 | 代码支持 | 判定 | 处置 |
|---|---|---|---|---|
| 关键词输入框 + 模板/Skill 快选 → 触发生成 | 关键词、模板列表、Skill 列表 | `pipeline.generate` + `template.list_templates` + skill 目录扫描 | ✅ | 直译 |
| 问候条「昨日 X 字 / 本周 Y 字」 | 写作量统计 | **无** | ❌ | **推荐砍**：csm_core 无统计模块；可由 sidecar 现场扫 `out_dir` 文件 mtime + 字数聚合（廉价），但已超 v1 范围 → **v1 显示固定问候语，统计字段进 backlog** |
| 日历卡：本月排期（已完成/排期数） | `CAL_DATA: {done: number[], scheduled: number[]}` | **无**——csm_core 没有任务排期模块 | ❌ | **推荐砍**：v1 直接移除日历卡。"排期"语义不清（用户主动排？AI 推荐？）。进 backlog |
| 排名异动卡（Top 4 知乎告警，含 alert/warn/info 等级） | 历史 MonitorResult + 等级判定 | csm_core 的 `should_alert()` 只返回 **bool**，**无等级** | ❌ | **推荐简化**：UI 只展示"已告警"和"未告警"两态；告警等级（red/yellow/green）映射为 csm_core `MonitorStatus`：`failed/risk_control` → red、`ok && rank > top_n` → yellow、`ok && rank ≤ top_n` → green |
| 平台评论留存率（B站/抖音/快手 饼图 + delta） | 各平台留存比例 | `MonitorResult.metric` 含 `retained/total`，但聚合统计需 sidecar 当场算 | ⚠️ | **推荐补**：sidecar 加 `GET /api/monitor/summary` 端点，按平台聚合最近 N 次的均值 |
| 最近文档列表（7 日内 5 条，字段 `tpl/words/when/status/source`） | 历史导出文件 | `export.export_article` 写盘但无登记 | 🔄 | **以代码为准**：sidecar 扫 `out_dir` 列出 .md/.docx 文件 + mtime + 解析 frontmatter 拿 title/template；`status` 字段（已发布/草稿/归档）**无意义砍掉**；`source` 字段（vault/polish）**无意义砍掉** |
| 4 个快捷操作卡（粘贴洗稿/模板库/监测/Skill） | 仅导航 | — | ✅ | 路由跳转 |

### 2. article 创作区（[src/screens/article.jsx](../../../../CSM-RE1（V1）/src/screens/article.jsx)）

| 区块/功能 | 数据需求 | 代码支持 | 判定 | 处置 |
|---|---|---|---|---|
| 头部字数/重复率徽章 | 字数+`DuplicateReport.duplicate_ratio` | ✅ | ✅ | 直译 |
| 3 标签页（组装/初稿/成稿） | `BlockResult` 树 + `final_text` | `assembler.compose_draft` + `pipeline.generate` 都返回 | ✅ | 组装预览用 `BlockResult.children/picks` 渲染 |
| 组装预览右侧槽位「润色」按钮 | 单段落改写 | csm_core 无"单段落润色"接口 | ❌ | **推荐两选一**：(a) 砍按钮，只保留整篇润色；(b) sidecar 加便捷端点 `POST /api/polish/block` 内部包装 LLM 调用——**v1 推荐 (a)，整篇润色已经够用** |
| 组装预览右侧槽位「重随」按钮 | `assembler.reroll_pick(plan, block_id, pick_index)` | ✅ | ✅ | 直译；`NoCandidatesError` 提示用户 |
| 初稿/成稿 contentEditable 富文本 | — | UI 自有 | ✅ | 计划里说会改用 **Tiptap** 替代 contentEditable，更稳定 |
| 整篇润色（进度条 0–100%） | LLM 段落级进度 | csm_core 无段落级进度，只有"整篇生成的 6 阶段名" | 🔄 | **推荐降级**：进度条改为 `pipeline.generate` 的 6 阶段名进度（每阶段一格），不假装百分比；前端做平滑动画即可 |
| 质检报告卡（6 个指标：重复率/标题候选数/字数/关键词密度/段落质感/...） | 多个独立计算 | 重复率 ✅；字数 ✅；标题候选数 ✅（call `generate_titles`）；**关键词密度/段落质感 无** | 🔄 | **推荐**：保留重复率/字数/标题候选数三项；关键词密度可由 sidecar 现场算（廉价，扫文本即可）；**段落质感砍**——无客观度量标准 |
| 质检报告"重复率"点击 → 查重命中明细 | `DuplicateReport.hits[].start/end/source_excerpt` | ✅ | ⚠️ 补 UI | **推荐补**：UI 加滑出抽屉，命中段落用下划线高亮 + 来源链接 |
| Skill 下拉 | skill 列表 + 描述 + uses | csm_core 无 SkillRegistry，skills 是 `skill_dir` 下的 .md 文件 | ⚠️ | **推荐补**：sidecar 加 `GET /api/skills` 扫目录解析 frontmatter（name/desc）；`uses` 字段无来源 → 砍或暂返 0 |
| 「换标题」按钮（**原型未明示，但 DocHeaderBar 有 title**） | `title.generate_titles` 候选列表 | ✅ | ⚠️ | **推荐补**：article 标题点击 → 展开候选列表 |
| 导出弹层 5 种格式（md/docx/weixin/zhihu/txt） | `ExportFormat` | csm_core 只有 **markdown/docx** | ❌ | **推荐砍 weixin/zhihu/txt**：weixin/zhihu 涉及平台 API 集成，超 v1；txt 是 markdown 弱化版，无意义。**v1 仅保留 markdown / docx** |
| 导出选项「附带 frontmatter / 附带查重报告 / 附带 vault 引用」 | export 函数参数 | `export_article` 已有 `prompt_snapshot/plan` 参数，但**无"附带查重报告"开关** | ⚠️ | **推荐补**：sidecar 端做拼接（导出前调用 `dedup.analyze` 把 markdown 报告附在文末），不动 `csm_core/export/`；vault 引用 = frontmatter 里的 source 列表，已有 |
| 8 个快捷键面板 | — | UI 自有 | ✅ | Tauri 全局快捷键 |

### 3. batch 批量生成（[src/screens/batch.jsx](../../../../CSM-RE1（V1）/src/screens/batch.jsx)）

| 区块/功能 | 数据需求 | 代码支持 | 判定 | 处置 |
|---|---|---|---|---|
| 队列表格（关键词/状态/耗时/操作） | `BatchReport.items[]`、运行中状态 | `BatchItem.status: success\|failed`，**queued/running 由调度推断** | 🔄 | sidecar 在 store 里合成：未触发 `on_item_started` = queued、started 未 finished = running、finished = success/failed |
| 内联添加关键词 | append 到 `keywords: list[str]` | ✅ | ✅ | 在任务启动前可改；启动后用 `should_cancel` + 重启策略 |
| 英雄卡进度（段 5/8、字数 1640/2400、62%） | 段落级进度 | **无**，只有 6 阶段 + 当前文档 LLM 调用是黑盒 | ❌ | **推荐降级**：英雄卡进度改为「当前阶段 + 当前文档第 N/M 篇」；段/字进度砍 |
| 行操作「查看」（done） | 跳转 article 屏 | ✅ | ✅ | 直译 |
| 行操作「×」（queued） | 取消未启动项 | 改 `keywords` 列表（启动前）or 终止整个 batch | ⚠️ | **推荐**：v1 启动前可删；启动后只能"取消整个批量"（cooperative cancel via `should_cancel`），单条不能 skip |
| 取消按钮（running） | `should_cancel` 协作式取消 | ✅ | ✅ | SSE 端点收到取消请求即翻 flag |
| 批量配置摘要（模板/Skill/字数/润色/查重） | 批量任务的当时配置 | `run_batch` 参数 | ✅ | 显示启动时快照即可 |

### 4. monitor 监测中心（[src/screens/monitor.jsx](../../../../CSM-RE1（V1）/src/screens/monitor.jsx)）

| 区块/功能 | 数据需求 | 代码支持 | 判定 | 处置 |
|---|---|---|---|---|
| 3 tab（知乎/平台评论/历史报告） + 平台子 tab | `TaskType` 枚举 4 种 | ✅ | ✅ | 直译 |
| 任务表格（关键词/类型/上次排名/变化/状态） | `MonitorTask` + 最近 `MonitorResult` | ✅ | 🔄 | `lastRank/prevRank` 由 csm_core 历史结果计算；`delta` 字符串前端拼 |
| 紧急告警英雄卡 | 最近一条触发告警的 task | `should_alert()` bool 返回 | ✅ | 直译 |
| **告警等级** alert/warn/info（红/黄/灰） | 告警严重度分级 | **无** | ❌ | **推荐砍等级，改为 ok/告警 二态**；颜色按 `MonitorStatus`：failed/risk_control → 红、ok && rank > top_n → 黄、ok && rank ≤ top_n → 绿（这是"运行+业务"复合状态，不是真等级） |
| 知乎右侧「14 次快照 sparkline」 | 历史 MonitorResult 时序 | ⚠️ csm_core 应该写 sqlite（settings_page 提到 `monitor.db`），但**未在公开 API 暴露查询**接口 | ⚠️ | **推荐补**：sidecar 加 `GET /api/monitor/results?task_id=X&limit=14` 包装 db 查询 |
| 「Top 3 抢占者」 | `MonitorResult.metric` 里是否含竞争对手列表 | ⚠️ 不确定，需 A3 写 sidecar 时实测一次 fetch 看 metric 字段 | ⚠️ | **推荐**：A3 阶段实测；若 metric 不含 → UI 改为只显示"目标当前排名 + 第 1 名链接" |
| 平台评论 tab 子 tab（B/抖/快） + 留存率/被删评论 | `MonitorResult.metric` 形状 | 各 platform 自定 metric | 🔄 | sidecar 提供平台特定的响应 schema（按 type 分支） |
| 平台评论"被删/折叠评论列表" | 详细文本快照 | 应在 metric 里 | ⚠️ | 同上，A3 实测 |
| 历史报告 tab（日报/周报） | 聚合报表 | **无聚合报表生成器** | ❌ | **推荐砍历史报告 tab**，进 backlog；csm_core 当前只存原始 MonitorResult 不做聚合 |
| Cookie 池状态（知乎/B站） | csm_core `drivers/cookie_store` | ✅ | ⚠️ | **推荐补**：sidecar 加 `GET /api/monitor/cookies` 查询 + `POST /api/monitor/cookies/{platform}` 更新 |
| 桌面通知 | csm_core `monitor/notify.py` | ✅（应该有）| ⚠️ | sidecar 触发后通过 SSE → Tauri 端用 `tauri-plugin-notification` 显示 |

### 5. templates 模板库 + template-builder

| 区块/功能 | 代码支持 | 判定 | 处置 |
|---|---|---|---|
| 模板卡片网格、预览槽位 | `template.load/list/save_template` | ✅ | 直译 |
| Skill 库（4 个 .md 风格） | csm_core 无 SkillRegistry | ⚠️ | sidecar `GET /api/skills` 扫 `skill_dir` |
| Skill 详情 .md 代码预览 | 直接读文件内容 | ✅ | sidecar `GET /api/skills/{id}` 返回 raw text |
| 7 种块 picker（template-builder） | `template/schema.py` 7 种 BlockKind | ✅ | 完全对齐 |
| 块 config panel（每种块字段不同） | schema 字段（source/pick_notes/constraints/depends_on） | ✅ | 直译 |
| 块拖拽排序 | UI 自管（编辑后 save_template）| ✅ | 直译 |

### 6. settings 设置（9 分组）

| 分组 | 字段 | 代码支持 | 判定 | 处置 |
|---|---|---|---|---|
| **通用** | 用户名/主题/强调色/语言/字体/关闭行为/开机自启/检查更新 | `user_name/close_action` ✅；其他 UI 自管 | ✅ | 主题/强调色/字体存到 `AppConfig` 新增字段（v1 可暂不加，写到 localStorage） |
| **存储路径** | vault/导出/默认模板/skills 目录 | `vault_root/out_dir/default_template/skill_dir` ✅ | ✅ | 走 Tauri dialog API |
| **模型** | 4 个 Provider 卡 + API Key + 测试 + 默认 | ✅；测试用 `make_client + complete` ping | ✅ | API Key 写 keyring（A1 已搭好） |
| 高级（超时/并发/上传训练提示） | `timeout_seconds/concurrency` ✅；`upload_training_hints` 字段在但**无对应实现** | 🔄 | **推荐砍 "上传训练提示" toggle**——AppConfig 里删字段或留作占位 |
| **Skill 默认** | 首选 Skill / 克制度起点 / 信息密度起点 / vault 引用 / 句长上限 | 首选 Skill ✅；其他 4 项 csm_core 无对应 | ❌ | **推荐砍 4 项 sliders**：pipeline 用 `user_skill_prompt` 字符串和 Skill .md 控制风格，无独立数值参数；想保留只能映射到 user_config dict 但无定义 |
| **导出** | 默认格式 / 文件名模板 / frontmatter / 查重报告 / 图片处理 / 导出后操作 | 默认格式 ✅；文件名模板：csm_core 写死 `MMDD-N`；frontmatter ✅（已是默认）；查重报告：sidecar 拼；图片/导出后操作 **无** | 🔄 | **推荐**：保留 默认格式 + 附带查重报告；砍 文件名模板（写死）/ 图片处理 / 导出后操作 |
| **历史查重** | 历史/Vault 索引重建 + 阈值 | `dedup.build_index` + `dedup_threshold_green/yellow` ✅ | ✅ | 直译 |
| **监测** | 检查频率 / 告警阈值 / 桌面通知 / 浏览器路径 / AI 摘要 / Cookie 状态 | `MonitorConfig` 完全覆盖 ✅ | ✅ | 直译；Cookie 状态需新端点（见 monitor 屏） |
| **账号** | 个人 / 工作空间 / 同步状态 / 导出账号数据 / 退出登录 | csm_core **无账号系统、无云同步** | ❌ | **推荐整个砍**：v1 是单机工具，无登录概念。"导出账号数据"=导出 settings.json 已有渠道（settings 顶部加按钮足够） |
| **关于** | Logo / 版本 / 检查更新 / 文档 / 许可 / 致谢 | `updater_client.check_for_update` ✅；版本字符串 ✅ | ✅ | 直译 |

### 7. states 状态预览

仅 UI 演示，无后端依赖。✅ 直译。

---

## 三、Skill 库的归属（独立小节）

原型多处涉及"风格 Skill"（home 快选、article 下拉、templates Skill 库、settings 默认 Skill）。csm_core 当前**没有 SkillRegistry**，skills 是 `skill_dir` 下的 .md 文件，pipeline 用 `user_skill_prompt: str` 直接拼到 prompt 里。

**推荐处置**（不动 csm_core）：

- sidecar 新增 `GET /api/skills` —— 扫 `skill_dir`，每个 .md 解析 frontmatter（name/desc/tone）+ 文件内容；`uses` 字段（使用次数）**砍掉**或返回 0
- `GET /api/skills/{id}` —— 返回 raw markdown
- 用户在 article/home 选 Skill → 前端把 Skill 的 markdown 内容作为 `user_skill_prompt` 传给 `/api/generate`

---

## 四、字段重命名汇总（前端适配）

| 原型字段 | csm_core 来源 | 改用 |
|---|---|---|
| `RECENT_DOCS.tpl` | `Template.name` | `template_name` |
| `RECENT_DOCS.status` (`已发布/草稿/归档`) | 无 | **砍掉** |
| `RECENT_DOCS.source` (`vault/polish`) | 无 | **砍掉** |
| `MONITOR_TASKS.delta` (`-2` 字符串) | `rank - prevRank` 计算 | 前端拼 |
| `MONITOR_TASKS.status` (`ok/warn/alert`) | `MonitorStatus` (`ok/failed/risk_control/skipped`) | 见 home/monitor 屏的复合映射 |
| `BATCH_QUEUE.status` (`done/running/queued`) | `BatchItem.status` (`success/failed`) | 前端 store 合成 running/queued |
| `ALERT_FEED.level` (`alert/warn/info`) | `should_alert()` bool | **砍等级** |
| `SKILLS.uses` | 无 | **砍**或返 0 |

---

## 五、需要新增的 sidecar 端点（驱动 A3）

由本表得出的、超出 csm_core 直接包装的"组合端点"：

1. `GET /api/recent` —— 扫 `out_dir` 列最近文档（home 屏用）
2. `GET /api/skills` / `GET /api/skills/{id}` —— Skill 目录扫描
3. `GET /api/monitor/summary` —— 平台留存率聚合（home 屏 + monitor 屏概览）
4. `GET /api/monitor/results?task_id=X&limit=14` —— 历史时序（monitor sparkline）
5. `GET /api/monitor/cookies` / `POST /api/monitor/cookies/{platform}` —— Cookie 池查询和更新
6. `POST /api/dedup/analyze` —— 包装 `DedupAnalyzer.analyze`
7. `POST /api/title` —— 包装 `title.generate_titles`
8. `POST /api/keyword/density` —— 关键词密度（sidecar 自实现，不进 csm_core）

其余端点（`/api/generate`、`/api/batch`、`/api/templates`、`/api/config` 等）直接包装 csm_core 函数。

---

## 六、最终决策（用户已拍板）

### ❌ 砍掉的功能（共 6 项）

| # | 功能 | 屏幕 | 砍因 |
|---|---|---|---|
| 5 | 导出格式 weixin/zhihu/txt | article | csm_core 只支持 markdown/docx；其他需平台 API 集成，进 v2 backlog |
| 6 | 质检报告"段落质感"指标 | article | 无客观度量标准 |
| 9 | Skill 默认 4 个 sliders（克制/密度/句长/vault 引用） | settings | pipeline 用 prompt 字符串而非数值参数 |
| 10 | 账号分组整个（工作空间/同步/退出登录） | settings | 单机工具无账号系统 |
| 11 | 文件名模板 / 图片处理 / 导出后操作 | settings 导出分组 | csm_core 写死 `MMDD-N`，其他无支持 |
| 12 | "上传训练提示" toggle | settings 高级 | AppConfig 有字段但无实现，砍掉时字段一并删除 |

### ✅ 保留的 UI 元素（csm_core 不直接支持，由 sidecar 适配）

| # | 功能 | 屏幕 | sidecar 适配方式 |
|---|---|---|---|
| 1 | 日历卡（本月排期） | home | 扫 batch 历史 + 导出文件 mtime → 已完成日；"排期"v1 返回空数组（占位）。新端点 `GET /api/calendar?month=YYYY-MM` |
| 2 | 昨日/本周字数统计 | home 问候条 | 扫 `out_dir` 文件，按 mtime 聚合字数。新端点 `GET /api/stats/words?range=yesterday\|this-week` |
| 3 | 告警 3 等级（alert/warn/info） | home + monitor | **不在 csm_core 加 level 字段**；前端把 `MonitorStatus` 复合映射为视觉 3 级（见 §四 字段重命名 ii） |
| 4 | 单段落润色按钮（组装预览） | article | sidecar 新增 `POST /api/polish/block`，内部包装一次 LLM 调用，输入段落文本 + Skill prompt |
| 7 | batch 段进度（5/8、1640/2400） | batch 英雄卡 | **软妥协**：不引入段级回调（pipeline 改动太大）。UI 改为「当前阶段 / 当前文档 N/M 篇」，前端在 6 阶段间做平滑过渡动画 |
| 8 | 历史报告 tab（日报/周报） | monitor | sidecar 现场聚合 `monitor.db` 历史 MonitorResult。新端点 `GET /api/monitor/reports?period=daily\|weekly` |

### ⚠️ 补到某屏的功能（A–F 全数采纳）

| 标记 | 功能 | 屏幕 | 实现路径 |
|---|---|---|---|
| A | 标题候选列表 | article DocHeaderBar | 标题点击 → `POST /api/title` → `title.generate_titles` |
| B | 查重命中明细抽屉 | article 质检报告 | 重复率数字点击 → 滑出 `DuplicateReport.hits` 段落级命中 + 来源 |
| C | Skill 库 | article 下拉 / templates / settings | `GET /api/skills` 扫 `skill_dir` 解析 frontmatter |
| D | 监测历史 sparkline | monitor 知乎右侧 | `GET /api/monitor/results?task_id=X&limit=14` |
| E | Cookie 池状态/更新 | monitor + settings | `GET /api/monitor/cookies`、`POST /api/monitor/cookies/{platform}` |
| F | 评论留存聚合 | home 评论卡 | `GET /api/monitor/summary` |

### 🔄 字段降级（前端适配，不动 csm_core）

| 原型字段 | 改用 |
|---|---|
| `RECENT_DOCS.status` (`已发布/草稿/归档`) | 砍——文档只有"导出后存在" |
| `RECENT_DOCS.source` (`vault/polish`) | 砍——语义不清 |
| `RECENT_DOCS.tpl` | 改名 `template_name`，由 frontmatter 解析 |
| `MONITOR_TASKS.delta` (`-2` 字符串) | 前端用 `rank - prevRank` 拼字符串 |
| `MONITOR_TASKS.status` (`ok/warn/alert`) | 前端把 `MonitorStatus` 4 态合成视觉 3 态：`failed`/`risk_control` → red(alert)、`ok && rank > top_n` → yellow(warn)、`ok && rank ≤ top_n` → green(info) |
| `BATCH_QUEUE.status` (`done/running/queued`) | 前端 store 合成：未触发 `on_item_started` = queued、started 未 finished = running、finished = success/failed → done |
| `ALERT_FEED.level` (alert/warn/info) | 与 MONITOR_TASKS.status 同套映射 |
| `SKILLS.uses` | 返回 0，前端隐藏字段 |

---

## 七、A3 阶段需要落地的 sidecar 端点（汇总）

下列端点驱动 A3 阶段实现。前 11 项是 csm_core 直接包装；后 11 项是组合/适配端点。

**直接包装 csm_core（无业务逻辑）**：

1. `GET /health` ✅（已实现）
2. `GET /api/version` ✅（已实现）
3. `POST /api/shutdown` ✅（已实现）
4. `GET/PATCH /api/config` ← `AppConfig`
5. `GET /api/keyring/{provider}` / `POST /api/keyring/{provider}` ← keyring helpers
6. `POST /api/vault/scan` ← `vault.scan_vault`
7. `GET /api/vault/notes` ← `VaultIndex.query`
8. `GET/POST/PATCH/DELETE /api/templates` ← `template.list/load/save/delete_template`
9. `POST /api/generate` + `GET /api/events/{job_id}` SSE ← `pipeline.generate`
10. `POST /api/title` ← `title.generate_titles`
11. `POST /api/dedup/analyze` ← `DedupAnalyzer.analyze`
12. `POST /api/dedup/build-index` + SSE 进度 ← `DedupAnalyzer.build_index`
13. `POST /api/batch` + SSE ← `batch.run_batch`
14. `GET/POST /api/monitor/tasks` ← MonitorTask CRUD
15. `GET /api/monitor/results` ← 单任务历史结果（参数 `task_id`、`limit`）
16. `POST /api/export/{format}` ← `export.export_article`（仅 markdown/docx）
17. `GET /api/updater/check` + `POST /api/updater/download` + SSE ← `updater_client`

**组合/适配端点（sidecar 内部组装，不动 csm_core）**：

18. `GET /api/recent` —— 扫 `out_dir` 列最近文档（home 屏）
19. `GET /api/skills` / `GET /api/skills/{id}` —— Skill 目录扫描（C）
20. `GET /api/calendar?month=YYYY-MM` —— 月排期（保留 1）
21. `GET /api/stats/words?range=yesterday|this-week` —— 字数统计（保留 2）
22. `POST /api/polish/block` —— 单段落润色（保留 4）
23. `GET /api/monitor/summary` —— 平台留存率聚合（F）
24. `GET /api/monitor/reports?period=daily|weekly` —— 历史报告聚合（保留 8）
25. `GET /api/monitor/cookies` / `POST /api/monitor/cookies/{platform}` —— Cookie 池（E）
26. `POST /api/keyword/density` —— 关键词密度（质检报告卡用）

**Tauri 端原生处理（不走 sidecar）**：

- 文件/目录选择对话框 → `@tauri-apps/api/dialog`
- 系统通知 → `tauri-plugin-notification`（sidecar 通过 SSE 推送告警事件，Tauri 端转发为系统通知）
- 系统托盘 / 单实例锁 / 全局快捷键 → Tauri 内置
