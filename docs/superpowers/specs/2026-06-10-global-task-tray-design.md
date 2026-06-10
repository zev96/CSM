# 全局任务托盘（Global Task Tray）— 设计

- 日期：2026-06-10
- 分支：`claude/sharp-chatterjee-e2792c`
- 状态：设计已与用户确认，待 spec 复核 → writing-plans
- 注意：与 `2026-05-07-tray-background`（系统托盘后台驻留）无关，本文是**应用内**任务托盘。

## 1. 目标

监测 / 引流抓取 / 批量生成 / 单篇生成都是 5–10 分钟级长任务，SSE 跨页同步已存在，但用户离开任务页后导航上没有任何「有东西在跑」的迹象。本功能在侧栏底部加一个**常驻任务入口**：有任务时显示数字角标 + 呼吸动效，点开浮层列出各任务进度条、ETA、排队/验证码状态与取消按钮；任务完成后进通知铃铛。分工：**托盘 = 进行中，铃铛 = 已发生**。

## 2. 范围

**做：**
- 新建 `taskTray` 聚合 store（纯前端，读现有 4 个 store，不新建 SSE 连接）。
- 新建 `TaskTrayButton`（LeftNav 底部、铃铛上方）+ `TaskTrayPanel`（浮层）。
- `monitorStatus` 扩展：消费 `waiting_chrome_close` / `chrome_closed` / `captcha_required` / `captcha_resolved` 事件（后端已在发，前端未接）。
- 监测任务名缓存（id → {name, type}，懒加载 `GET /api/monitor/tasks`）。
- 托盘内取消：监测（组）/ 引流 / 批量走现有端点；**单篇生成补后端取消端点**（唯一后端改动）。
- 通知补齐：监测/引流/批量/单篇四类的完成与失败全部推入通知铃铛（见 §6 勘误——铃铛此前是空壳）。
- 「最近完成」区：托盘底部保留最近 3 条终态任务。

**不做：**
- 不做后端统一任务注册表（方案 B，将来阶段 3 RPA 任务多了再评估；`TrayTask` 接口已按可替换数据源设计）。
- 查重索引构建、更新下载不进托盘 v1。
- 不做托盘内启动/重试任务；不持久化「最近完成」（重启清空，完成历史有铃铛和各页面兜底）。
- LeftNav 既有导航项、路由不动。

## 3. 现状事实（本设计依赖的基建）

| 任务类型 | store / 状态 | SSE（已跨页存活） | 取消端点 |
|---|---|---|---|
| 监测 run-now | `stores/monitorStatus.ts`：`runningTaskIds: Set<number>`、`taskProgress: Record<id,{current,total}>` | `/api/monitor/events`：`started/progress/finished/failed/needs_captcha`（广播总线；`waiting_chrome_close/captcha_required` 等后端已发、前端未接） | ✅ `POST /api/monitor/tasks/{id}/cancel`（store 已封装 `cancel()`） |
| 引流抓取 | `stores/mining.ts`：`activeJob.progress: Record<Platform,{got,target,phase,note}>` | `/api/mining/jobs/{id}/events`：`job.progress/job.platform_done/job.finished/login.required/done` | ✅ `POST /api/mining/jobs/{id}/cancel` |
| 批量生成 | `stores/batch.ts`：`items[]`（queued/running/success/failed/cancelled）、`progress` getter | `/api/events/{jobId}`：`started/item_started/item_finished/cancel_requested/done/error` | ✅ `POST /api/batch/{id}/cancel` |
| 单篇生成 | `stores/article.ts`：`status/currentStage/stageIndex`（6 阶段） | `/api/events/{jobId}`：`stage/assembly/done/error` | ❌ 本设计补 |

- 所有 store 为 app 生命周期单例，路由切换不断 SSE —— 托盘零新增连接。
- `monitorStatus.start()` 在 App 启动时订阅，自带 30s 轮询 `GET /api/monitor/running` 兜底对账。
- 浮层范式：`NotificationDropdown.vue`（`absolute; bottom:0; left:52px`、320px、z-50）可直接复刻。
- 通知：`composables/useNotifications.ts` 的 `push(title,{body,tone,category})` + 分类偏好（localStorage、向前兼容默认开）。
- 后端无统一 running-jobs 端点；监测有 `/api/monitor/running`，引流单任务串行（忙时 409），批量有 `GET /api/batch/{id}` 快照。
- 进度粒度不均：监测仅部分类型（如百度）发关键词级 progress，其余只有 started/finished —— 托盘必须兼容**无进度数据**的任务（不确定态）。

## 4. 数据层：`frontend/src/stores/taskTray.ts`（新建）

```ts
interface TrayTask {
  key: string                 // "monitor:<type>" | "mining:<id>" | "batch:<uuid>" | "article:<uuid>"
  kind: "monitor" | "mining" | "batch" | "article"
  title: string               // 知乎问题监测 · 5 个任务 / 引流抓取 ·「宠物吸尘器」
  subtitle: string            // 正在检查「扫地机器人怎么选」 / 快手 31/50 · 抖音已完成
  progress: number | null     // 0~1；null = 不确定态（ProgressBar shimmer）
  state: "running" | "waiting" | "captcha" | "done" | "failed" | "cancelled"
  etaText?: string            // 「约 2 分钟」/「不到 1 分钟」
  cancellable: boolean
  route: RouteLocationRaw     // 点击行跳转
  startedAt: number
  finishedAt?: number         // 最近完成区排序用
}
```

### 4.1 聚合规则（computed，对齐 mockup）

- **监测按 `task.type` 分组成一张卡**：标题「{类型中文名} · N 个任务」；subtitle = 当前在跑任务的名称/关键词；progress = 组内有进度数据的任务 Σcurrent/Σtotal，**全组无进度数据则 null**。类型→中文名、类型→监测中心 tab 的映射复用 MonitorView 现有常量（type 枚举值实现时以 `csm_core/monitor/base.py` 为准）。
- **任务名缓存**：首个监测任务出现或托盘首开时拉一次 `GET /api/monitor/tasks` 建 `id → {name,type}`；缓存未命中的 id 显示「任务 #id」并触发一次补拉。
- **引流一张卡**：标题带关键词；subtitle 按平台拼接（`快手 31/50 · 抖音已完成`，phase=captcha_waiting → 计入验证码态）；progress = Σgot/Σtarget。
- **批量**：「批量生成 · 第 i/N 篇」，subtitle 当前关键词；progress 用 store 现成 getter。
- **单篇**：subtitle = 当前阶段名；progress = (stageIndex+1)/6。
- **state 推导优先级**：captcha > waiting > running。`waiting_chrome_close` → 「排队中 · 等待浏览器空闲」；`captcha_required` / `login.required` / phase=captcha_waiting → 「需要人工验证」（橙色，点击直达处理页）。
- **角标数 N** = 底层运行中任务总数（如监测 5 + 引流 1 = 6），非卡片数；>9 显示 `9+`。

### 4.2 ETA 估算（纯前端）

按卡维护进度速率 EMA（α=0.3，进度事件触发更新）：`eta = (1 - p) / rate`。显示门槛：p ≥ 5% 且 ≥ 2 个样本；< 60s 显示「不到 1 分钟」，否则「约 X 分钟」（取整）。不满足门槛或速率异常时不显示（避免乱跳）。

### 4.3 取消分发（✕ 按钮，不弹确认框）

| kind | 行为 |
|---|---|
| monitor 组卡 | 循环对组内 running ids 调 `monitorStatus.cancel(id)`（监测可断点续跑，非破坏性） |
| mining | store 现有 cancel action（已抓数据保留） |
| batch | store 现有 cancel action（协作式，queued 项标 cancelled） |
| article | 新增 store `cancel()` → 新端点（见 §7） |

取消后 toast 反馈；失败（如已结束撞 409）静默落到终态。

### 4.4 最近完成区

任务到终态（done/failed/cancelled）后从运行区移入「最近完成」：保留最近 3 条，显示 ✓/✗、标题、耗时，可点击跳转，一键清除；仅内存。

## 5. UI 层

### 5.1 任务按钮（LeftNav 底部，铃铛上方；按铃铛先例内联在 LeftNav.vue，不单抽组件）

- 44×44、radius 14px，与现有底部按钮同规格；图标常驻（0 任务时安静态：无角标、无动效，仍可点开看空态/最近完成）。
- 有任务：右上数字角标（参照铃铛红点样式放大为数字 pill）+ 呼吸动效；tooltip「N 个任务运行中」。
- 托盘与铃铛 dropdown 互斥：open state 统一提升到 LeftNav 管理，开一个关另一个。

### 5.2 `TaskTrayPanel`（浮层）

- 定位复刻 NotificationDropdown：`absolute; bottom:0; left:52px`、z-50；宽 ~340px、max-height 480px、`--bg-inner` 底 + `--line` 边 + `--radius-card`。
- 结构：头部「后台任务 · N」→ 任务卡列表（图标 + 标题 + subtitle + `ProgressBar`（tone 随 state）+ `64% · 约 2 分钟` + ✕）→「最近完成」分区 → footer 静态文案「切到任何页面任务都继续跑 · 完成后通知」。
- 空态：「暂无后台任务」+ 引导文案。
- 点击任务行跳转：monitor → `/monitor?tab=<type对应tab>`；mining → `/mining`；batch → `/batch`；article → `/article`。
- 复用 `ProgressBar` / `Pill` / `Icon` 原子与全套设计 token；hover 可变属性写 scoped CSS（禁 inline style 压 hover）。

## 6. 通知栏整合

> **勘误（2026-06-10 写实施计划前的实地核查）**：`useNotifications().push()` 原本全工程**零调用方**——铃铛是空壳；监测完成此前推的是 OS 级系统通知（useSystemNotify），不是铃铛。设计时「监测/批量通知已有」的假设不成立，本节修订为全量补齐四类。

- 新增通知类别 `monitor_done`（「监测任务完成」）与 `mining_done`（「引流任务完成」）到 `NOTIFICATION_CATEGORIES`（localStorage 向前兼容逻辑已有，默认开）。
- 监测 `finished` → `push(category: "monitor_done")`；`failed` → `push(category: "monitor_alert")`（用户主动取消、风控分支保持静默，沿用现有 toast 分流逻辑）。
- mining `job.finished` → `push("引流任务完成", {body: 关键词+各平台数量, tone: 全平台完成=success / 部分平台失败或部分完成=warn, category: "mining_done"})`。
- 批量 `done` → `push(category: "article_success")`；`error` → `push(category: "article_failure")`（复用既有「生成文章」类别，批量本质也是生成文章）。
- article `done` → `push(category: "article_success")`；`error` → `push(category: "article_failure")`；用户主动取消（cancelled 标记）不推。
- 效果：任务从托盘消失的瞬间铃铛红点亮起，每类可在通知设置单独开关。

## 7. 后端改动（唯一）：单篇生成取消端点

- `POST /api/generate/{job_id}/cancel`：`generate_service` 加取消标记集合 + `request_cancel(job_id)`（模式照抄 `batch_service.request_cancel`）。
- `_run_job` 在每个 stage 检查点 + 调用 LLM 前检查标记；命中则发 `error` 事件、payload 带 `{error: "cancelled", cancelled: true}` 收尾（event_bus 仅以 `done/error` 终结 stream，复用 `error` 避免动 event_bus）。
- 前端 `article.ts` 加 `cancel()` action；收到 `cancelled: true` 的 error 事件时静默回 `idle` + toast「已取消」，不弹错误。
- 对已完成/不存在的 job 返回 404/409，前端静默处理。

## 8. 边界情况

- **SSE 断线**：监测靠现有 30s hydrate 兜底；引流/批量 EventSource error 时各拉一次快照（`GET /api/mining/jobs/{id}`、`GET /api/batch/{id}`）对账。
- **sidecar 重启**（Tauri 下与 app 同生命周期）：监测 hydrate 清空 running、引流任务标 interrupted —— 托盘自然清空，不残留幽灵任务。
- **进度缺失**：progress=null 走 ProgressBar 不确定态 shimmer，不显示百分比与 ETA。
- **多类型监测并发**：每类型一张组卡，多卡并列。

## 9. 测试策略

- vitest 单测（仿 `components/home/__tests__` 范式）：
  - taskTray 聚合：喂 4 个 store 的假状态 → 断言 TrayTask[]（分组、标题、progress、state 优先级、角标数）。
  - ETA 估算器：门槛、EMA、文案。
  - 取消分发：各 kind 调到正确 action；最近完成区流转与上限。
- 后端：generate cancel 的服务层单测（按 sidecar 现有测试范式）。
- 真机：Playwright 注入 Pinia 假任务驱动角标/浮层/取消（真机验证工具箱）；`vue-tsc` 通过（事后还原 vite.config.js）。

## 10. 验收标准

1. 在任意页面发起监测 run-now / 引流 / 批量 / 单篇 → 侧栏按钮 3s 内出现角标与动效；切路由角标持续更新。
2. 浮层内进度与各任务页内进度一致（同源数据）。
3. 浮层内取消 → 任务 5s 内移入「最近完成」标 ✗，对应页面状态同步变化。
4. 百度监测等待浏览器/验证码时，托盘显示「排队中/需要人工验证」而非假「运行中」。
5. 任务完成 → 铃铛收到对应类别通知（且可在通知设置关闭该类别）。
6. sidecar 重启后 30s 内托盘清空幽灵任务。
7. 单测全绿；`vue-tsc` 无新增错误。

## 11. 实施切分（2 个 PR）

1. **PR1 前端主体（~80%）**：taskTray store + 聚合/ETA/最近完成 + TaskTrayButton/TaskTrayPanel + monitorStatus 扩展（waiting/captcha 事件）+ 任务名缓存 + 监测/引流/批量取消接通 + 通知补齐（mining_done、article_success/failure）+ 单测。单篇生成卡先显示进度、无 ✕。
2. **PR2 后端 + 收尾**：generate cancel 端点 + article store `cancel()` + 托盘接通单篇 ✕ + 服务层单测。

## 12. 已确认的决策（用户拍板，2026-06-10）

1. v1 收录四类核心任务：监测 + 引流 + 批量 + 单篇生成（查重索引、更新下载不进）。
2. 补单篇生成后端取消端点，托盘内全类型可取消。
3. 完成任务保留「最近完成」区（3 条、可清除）+ 照常进通知铃铛。
4. 入口为独立任务按钮（铃铛上方、数字角标 + 呼吸动效），不与铃铛合并；「N 个任务运行中」文字放 tooltip 与面板头部（侧栏 72px 仅容图标）。
