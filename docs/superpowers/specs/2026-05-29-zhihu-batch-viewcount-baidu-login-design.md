# 设计：知乎批量监测 + 问题浏览量 + 百度登录修复

- **日期**：2026-05-29
- **状态**：待评审（brainstorming 产出，未进入实现计划）
- **分支**：`claude/lucid-leavitt-a30b7b`
- **范围**：监测模块三项改动 —— 知乎任务批量化（A）、知乎问题浏览量抓取与展示（B）、Cookie 管理器百度登录 bug 修复 + 入口迁移（C）。

> A、B 高度耦合（都动 `ZhihuMonitorModule.vue` 与 zhihu 任务/适配器），合并设计；C 独立但一并交付。

---

## 背景 / 现状

- 监测任务统一存在 `monitor_tasks` 表（`csm_core/monitor/storage.py`），`TaskType` 含 `zhihu_question` / `*_comment` / `baidu_keyword`（`csm_core/monitor/base.py:44`）。每条结果存 `monitor_results.metric_json`（任意 JSON）。
- **批次模式现状**：不是真实父子关系，而是**命名约定** —— 任务名形如 `"批次名 - 尾部"`，前端 `parseBatchName()`（`frontend/src/utils/monitor-batch.ts`）按最后一个 `" - "` 切出批次名分组。评论平台（`CommentMonitorModule.vue`）已是「L1 批次列表 → L2 视频子任务 → L3 详情」三层。
- **知乎现状**：`ZhihuMonitorModule.vue` 是**扁平**列表（列：问题名字 | 类型「问题」| 卡位 | 变化 | 操作 ▶✎🗑），右侧是单问题详情面板。`BatchImportTaskModal.vue` 已支持 zhihu 批量导入，但每行各带品牌词、且不做批次分组。
- **浏览量现状**：`zhihu_question.py` 适配器只抓回答级字段（voteup/comment/content），**完全没抓问题浏览量**。
- **百度登录现状（已用日志定位根因）**：Cookie 管理器（`CookieManagerModal.vue`）选「百度」→「登录百度」走 `/api/monitor/baidu/login` → `open_login_window`（headed，完整 Chromium，正常）。状态读取 `get_login_status` 用 `headless=True` → Patchright 去找 `chrome-headless-shell.exe`，**该二进制未随包**（bundle 只有完整 chromium），启动抛错 → 路由吞掉 → **永远显示未登录**。同一根因也会拖垮「默认 headless」抓取（`baidu_browser.py:107` 自建分支也没传 `executable_path`）。

---

## A. 知乎任务批量化（总任务 → 子任务）

### 决策
- 沿用评论平台的**命名约定批次**（不引入新的 `parent_id`/批次实体），保持与现有模式一致、复用 `parseBatchName` 与 `BatchImportTaskModal`。子任务名 = `"批次名 - 问题标题"`。
- **批次共享一个目标品牌词 + 监测前 N 个回答**（不再每行单独设品牌词）。
- 放弃「理想/未理想」状态聚合概念（用户明确不要）。

### UI（对齐原生暖色风格，操作列复用原生 ▶✎🗑 图标）
左面板在两态间切换，右侧单问题详情面板**不变**：

- **L1 批次列表**：列 = `批次名 | 问题数 | 操作`
  - 顶部按钮：`批量导入`、`新增批次`
  - 操作：▶ 启动批次内所有子任务 · ✎ 编辑批次共享设置（品牌词 / 前 N / 定时）· 🗑 删除整个批次
  - **不显示浏览量**（汇总层）
- **L2 子任务列表**（点批次进入，带「‹ 返回批次」面包屑）：列 = `问题名字 | 浏览量 | 卡位 | 变化 | 操作`
  - 浏览量放在原「类型」列位置（万单位，见 B）
  - 操作：▶ 启动该子任务监测 · ✎ 编辑单个任务 · 🗑 删除该子任务
- 再点单个子任务 → 复用**现有单问题详情**（卡位数量 / 最高排名 / 7 天趋势 / 前 10 答案），不动。

### 批量导入弹窗调整（`BatchImportTaskModal.vue` zhihu 分支）
- 批次级字段：`批次名` + `共享品牌词` + `共享前 N`（+ 定时）。
- 每行 = `问题名<TAB>问题URL`（2 列；不再有 per-row 品牌/topN）。
- 提交：每行 POST `/api/monitor/tasks`，`name = "{批次名} - {问题名}"`，`config = {target_brand: 共享品牌, top_n: 共享N}`。

### 后端 / 数据
- 无表结构变更。批次靠命名约定。
- 批次操作映射到现有单任务路由：
  - 启动批次 = 对批次内每个子任务调 run-now（`/api/monitor/tasks/{id}/run-now`）。
  - 删除批次 = 删除批次内每个子任务（`DELETE /api/monitor/tasks/{id}`）。
  - 编辑批次 = 对批次内每个子任务 PATCH 共享 config（改名则同步重写各子任务名前缀）。

### 取舍 / 已知限制
- 命名约定的固有限制：问题标题含 `" - "` 会破坏分组；批次重命名要改全部子任务名。沿用评论平台同款限制，刻意保持一致。
- 现存扁平 zhihu 任务（名无 `" - "`）将各自显示为「单问题批次」，向后兼容。

---

## B. 知乎问题浏览量

### 决策
- **每次抓取都记录**浏览量（存进每次结果的 `metric`，可看涨跌）。
- 列表用**知乎原生万单位**展示：`< 1万`（< 10⁴）显原数（如 `856`）；`1万 ~ 1亿` 显 `X.X万`（如 `1.2万`、`350万`）；`≥ 1亿`（10⁸）显 `X.X亿`。仅在 **L2 子任务层**显示，L1 不显示。
- 去掉原「类型：问题」标签（知乎 tab 下本来全是问题）。

### 抓取（`csm_core/monitor/platforms/zhihu_question.py`）
- 现状只调 `/api/v4/questions/{qid}/answers`（回答级）。新增问题级浏览量来源，**优先 API**：调 `/api/v4/questions/{qid}?include=visit_count`（字段名以实测为准，常见 `visit_count`）；失败回退 **DOM 抓取**问题头部「被浏览 X」文本（浏览器兜底路径里加一个 selector + `_parse_count()`）。
- 解析到的整数写入返回的 `metric`，键名 `question_visit_count`（无表结构变更）。
- 加 **INFO 级 raw 日志**：记录浏览量来源（api/dom/缺失）+ 原始值，便于后续 silent failure 排查（沿用项目「silent failure 先加 raw logging」教训）。

### 展示（`ZhihuMonitorModule.vue`）
- 新增 `formatVisitCount(n)`：万单位格式化。
- L2 行从 `taskSnapshots[t.id]?.latest?.metric?.question_visit_count` 读取并渲染；无值显 `—`。
- 数据已随 `GET /api/monitor/results` 的 `metric` 返回（`monitor-snapshot.ts` 已透传 metric），无需新接口。

### 测试
- 适配器：mock API 响应含/不含 `visit_count` → 断言 metric 写入 / 回退到 DOM / 缺失为 None。
- 前端：`formatVisitCount` 边界（856 → "856"；12000 → "1.2万"；3_500_000 → "350万"）。

---

## C. 百度登录：headless 二进制根因修复 + 入口迁移

### C1. 根因修复（代码方案，不重新打包二进制）
- **问题**：`headless=True` 启动让 Patchright 去找未随包的 `chrome-headless-shell.exe`。
- **修法**：headless 启动显式传**完整 Chromium 的 `executable_path`**（已随包、headed 登录正常证明其存在），绕开 headless-shell。涉及：
  - `csm_core/monitor/drivers/baidu_login.py` → `get_login_status`（headless 读 cookie）。
  - `csm_core/monitor/drivers/baidu_browser.py` → 自建 profile 分支（`headless=headless` 那段，让「默认 headless」抓取也一并修好）。
  - executable_path 取 `pw.chromium.executable_path`（启动 playwright 后可得）。
- **加 INFO 级 raw 日志**到 `_open_login_poll` / `get_login_status`：拿到 cookie 数、各 name/domain、是否抛异常、BDUSS 是否命中、轮询结局 —— 把当前的静默失败变可观测（DEBUG→INFO）。
- **次要**：`open_login_window` 的 `page.goto` 改 `wait_until="domcontentloaded"` 降低 30s 超时；goto 失败已被容忍，不阻塞轮询。
- **验证前提**：需实测确认 patchright 下「传完整 Chromium executable_path + headless=True」可正常启动并读到 cookie；若不可行，退化到打包 `chrome-headless-shell`（备选，不在本期默认范围）。

### C2. 登录入口迁移
- 把百度「登录态 + 登录百度」这块 UI 从 `CookieManagerModal.vue`（移除其 `baidu` 平台分支）**迁到** `SettingsView.vue` 百度关键词设置区，置于**「默认 headless」开关上方**。
- 复用现有接口：`POST /api/monitor/baidu/login` + `GET /api/monitor/baidu/login-status`（逻辑不变，C1 修好后状态即正常）。
- Cookie 管理器平台下拉移除「百度」（百度不走 cookie 池）。

### 测试
- `_status_from_cookies` 既有单测保留；为 `get_login_status` 新增「executable_path 被传入」断言（monkeypatch 假 playwright 捕获 launch kwargs）。
- 路由层：`login-status` 在假驱动返回 logged_in 时透传成功。

---

## 不在本期范围
- 不引入真实批次实体（`batch_id`/外键）—— 维持命名约定。
- 不打包 `chrome-headless-shell` 二进制（除非 C1 实测不可行）。
- 百度 native 副本登录（System B，设置页「登录百度（副本）」）状态展示不在本期改动。

## 待实现时确认的锚点（非阻塞）
- 知乎问题浏览量的确切 API 字段 / DOM selector（实测定）。
- `SettingsView.vue` 中「默认 headless」开关精确位置。
- 「新增批次」与「批量导入」两个入口是否合并为一个弹窗（实现时定）。
