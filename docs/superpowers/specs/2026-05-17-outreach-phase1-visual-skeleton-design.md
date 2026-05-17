# Outreach 视觉骨架（Phase 1）— 设计稿

- 日期：2026-05-17
- 范围：把 `examples/CSM-RE1-handoff/csm-re1/project/src/screens/outreach.jsx`（1067 行 React 设计稿）翻译成 Vue 3 的 MiningView，**纯前端、不动后端**。
- 后续 spec（独立提）：
  - Phase 2：评论楼后台（schema v4 + video_comments 表 + API + composer 真能发评论）
  - Phase 3：AI 速览 + AI 建议（接 LLM factory）

---

## 1. 范围

### in scope

- 完全用 jsx 设计稿的 layout / 颜色 / 间距重写 `MiningView` 及其子组件
- 新建 `Avatar.vue` + `Blob.vue`（jsx 用到、ui/ 没有）
- 扩 `Icon.vue` 加约 15 个新 icon
- 新设计的 `StartJobModal`（含三平台 cookie 状态卡片、排序、时间范围、滑条、预估时间）
- 新设计的 hero card（黑底 + 双 blob glow + 4 KPI + 进度条 + 暂停/历史按钮）
- 新设计的视频卡（无封面、AI 速览占位、评论楼占位、composer 占位）
- 浮动批量操作栏（UI + checkbox 状态，按钮 disabled）

### out of scope（Phase 2/3 做）

- 评论楼真能发评论（Phase 2）
- AI 速览实际生成（Phase 3）
- AI 建议续写（Phase 3）
- 图片上传 / 素材库（Phase 2）
- 排序 / 时间范围参数实际生效（Phase 2，后端 API 要加 query 参数）
- 标记已评论 / 批量打开 / 批量导出（Phase 2）
- `done` 字段（Phase 2，DB 加列）

### 验收标准

- `MiningView` 视觉对照设计稿截图 1:1（hero 黑底 + glow blob + 4 KPI + 进度条；filter 三段 pivot；2 列视频卡 grid；视频卡含 AI 速览占位 + 评论楼占位）
- 现有 50 条 B 站视频在新 view 里正常显示
- `+ 新建抓取任务` 按钮起 mining job 仍能 work（用新 modal）
- `导出 CSV` 按钮仍能 work
- 浮动批量栏在选中视频后浮现，按钮 disabled 但能看见
- `vue-tsc -b && vite build` 零错误零警告（warning 限 pre-existing）
- 245 个 sidecar 测试仍然全过（前端改动不影响后端）

---

## 2. 文件清单

### 新建（3）

- `frontend/src/components/ui/Avatar.vue` — 首字母圆圈 avatar
- `frontend/src/components/ui/Blob.vue` — 装饰用模糊 glow blob
- `frontend/src/components/mining/PlatformPickerCard.vue` — StartJobModal 里每个平台的卡片（含 cookie 状态 indicator）

### 重写（已存在，大改）

- `frontend/src/views/MiningView.vue`（当前 114 行 → 预计 200+ 行）
- `frontend/src/components/mining/JobProgressCard.vue` → **改名为 `OutreachHero.vue`**（黑底大 hero + 4 KPI，跟现在的小进度卡完全不同）
- `frontend/src/components/mining/VideoTable.vue` → **拆成 `VideoCard.vue` 单文件**（jsx 设计里一张卡片即一个工作单元，table 概念消失）
- `frontend/src/components/mining/StartJobModal.vue`（重写为新设计：三平台卡片 + 排序 + 时间范围 + 滑条）
- `frontend/src/components/ui/Icon.vue`（**扩列**新 icon：spark / comment / copy / more / stack / eye / heart / clock / key / lock / warn / download / sort / pause / external / video / play / arrowDown）

### 删除

- `frontend/src/components/mining/PlatformLoginPanel.vue`（已废弃，cookies 走监控中心）

### 不动

- `frontend/src/stores/mining.ts`（Pinia store；Phase 1 只读现有 state，不加字段）
- `frontend/src/router/index.ts`（路由不变）
- `frontend/src/components/LeftNav.vue`（已有"引流"入口）
- 所有后端文件

---

## 3. 组件树（翻译自 jsx）

```
MiningView.vue
├── 页头
│   ├── div.eyebrow "OUTREACH · 引流"
│   ├── h1.大标题 "视频抓取"
│   ├── p.副标题
│   └── 操作 (右侧)
│       ├── <Btn variant="ghost"><Icon name="download"/> 导出 CSV</Btn>
│       └── <Btn variant="solid"><Icon name="plus"/> 新建抓取任务</Btn>
│
├── <OutreachHero/>  ← 跑任务时显示；空闲时折叠成小一点的占位
│   ├── <Blob color="#ee6a2a"/> × 2
│   ├── 左半 (1.4fr): 任务摘要 + platform chips + progress bar + 暂停/历史
│   └── 右半 (1fr): 4 个 KPI 卡片 2×2 grid
│
├── filter 条
│   ├── 状态 pivot (待评论 / 已评论 / 全部) + 各自计数
│   ├── 平台 chip (全部 / B站 / 抖音 / 快手)
│   ├── 排序 button (最新 ▾)
│   └── 搜索 input
│
├── 视频网格 grid-cols-2 gap-14
│   └── <VideoCard/> × N
│       ├── meta 行: checkbox + <PlatformChip/> + <Avatar/> + 作者 + 时间 + 状态 Pill + ⋯
│       ├── 标题行 + 视频元数据 (时长/播放/点赞/评论)
│       ├── AI 速览 黄色 box (Phase 1 占位文字)
│       ├── 评论楼 box (Phase 1 占位 "评论楼功能即将上线")
│       └── composer (Phase 1 disabled — 显示 "第二期上线" tooltip)
│
├── 浮动批量栏 (有选中时浮现)
│   └── dark pill: "已选 N 条" + 标记已评论 / 全部打开 / 导出 / ×
│
└── <StartJobModal/>
    ├── 关键词 input
    ├── 三平台 PlatformPickerCard × 3 (含 cookie 状态)
    ├── 排序 segmented
    ├── 时间范围 segmented
    ├── 数量滑条 + 数字大字
    ├── 预估时间黄色 info box
    └── footer: 取消 / 开始抓取
```

---

## 4. 数据流（用现有 store，不加字段）

`mining.ts` store 当前 state（Phase 1 直接用）：

```ts
activeJob: MiningJob | null
videos: Video[]
total: number
loading: boolean
filters: { keyword, platform, commented, q }
loginStatus: Record<Platform, boolean>
```

Phase 1 新增的本地（component-level）state：

```ts
// MiningView.vue
const tab = ref<'unread' | 'done' | 'all'>('unread')  // 待评论/已评论/全部
const platform = ref<'all' | Platform>('all')
const sortBy = ref<'最新' | '最热' | '综合'>('最新')   // UI only, not wired to backend
const selected = ref(new Set<number>())                // checkbox 选中
const showNewTask = ref(false)
```

**衍生计数（counts）** — 因为 Phase 1 没 `done` 字段：

```ts
const counts = computed(() => ({
  unread: videos.value.filter(v => !v.already_commented).length,
  done:   videos.value.filter(v =>  v.already_commented).length,
  all:    videos.value.length,
}))
```

→ 设计稿里 `待评论/已评论` 概念在 Phase 1 用 `already_commented` 字段近似（Phase 2 引入真正的 `done` 字段：用户**手动标记**完成 vs `already_commented` 是反查 monitor_tasks 自动标的）。

---

## 5. 设计稿到 Vue 的适配差异

### 5.1 Btn 组件

| jsx 写法 | Vue 改造 |
|---|---|
| `<Btn variant="primary" icon="play">开始</Btn>` | `<Btn variant="solid"><Icon name="play" :size="11"/> 开始</Btn>` |
| `<Btn variant="ghost" icon="download">导出</Btn>` | `<Btn variant="ghost"><Icon name="download" :size="12"/> 导出</Btn>` |
| `<Btn variant="plain">查看</Btn>` | `<Btn variant="ghost" small>查看</Btn>` |
| `size="md"` / `size="sm"` | `small` boolean |

### 5.2 Pill 组件

| jsx tone | Vue tone |
|---|---|
| `"green"` | `"ok"` |
| `"yellow"` | `"warn"` |
| `"primary"` | `"primary"` |
| `<Pill tone="green" icon="check">已完成</Pill>` | `<Pill tone="ok"><Icon name="check" :size="10"/> 已完成</Pill>` |

### 5.3 Icon 扩列

`Icon.vue` 当前已有：`home, edit, radar, library, settings, search, bell, sliders, wand, check, x, plus, arrowRight, arrowLeft, arrowUp, arrowDown, alert, info, windowMinimize, windowMaximize, windowRestore`

**需要补的（约 15 个）**：
- `spark` ⚡ (AI 速览 badge)
- `comment` 💬 (评论 icon)
- `copy` (图片按钮上的 icon)
- `more` ⋯ (三个点)
- `stack` ▭ (评论楼 icon)
- `eye` 👁 (播放量)
- `heart` ♡ (点赞)
- `clock` ⏱ (时长)
- `key` 🔑 (cookie footer)
- `lock` 🔒 (未登录 indicator)
- `warn` ⚠ (即将过期 indicator)
- `download` ⬇ (导出 CSV)
- `sort` ↕ (排序按钮)
- `pause` ⏸ (暂停)
- `external` (外部链接)
- `video` (空状态图标)
- `play` ▶ (开始抓取)

Icon 用 inline-SVG path strings，参考 ui.jsx 设计稿原版 path（可以从 Lucide icons 抄）。

### 5.4 Card 组件

jsx 有 `<Card dark className="pad-d">`。Vue 的 `Card.vue` 当前 API 暂时不确认 `dark` prop 支持，需要 verify。**如果没有**：在 Phase 1 任务里**也扩 Card.vue 加 `dark` boolean prop**。

---

## 6. 占位行为（Phase 1 visual only）

| 设计稿元素 | Phase 1 占位实现 |
|---|---|
| AI 速览文字 | 显示 "AI 速览生成中…" 灰色 placeholder；或者写死一句静态文字（Phase 3 接 LLM） |
| 评论楼 box | 显示 "评论楼功能即将上线（第二期）" + 看起来对的空状态 |
| composer textarea | placeholder 文字保留，但 textarea **disabled** |
| 「发布第 1 层」按钮 | disabled，tooltip "第二期上线" |
| 「图片」「AI 建议」按钮 | disabled |
| 「完成」按钮 | disabled |
| 浮动批量栏的 标记已评论 / 全部打开 / 导出 按钮 | disabled |
| 暂停 / 查看历史按钮（hero card） | 暂停可点（已经在 store 里实现）；查看历史 disabled |

---

## 7. 视频卡 mock 数据

设计稿里 jsx 用 `MOCK.VIDEOS` 喂数据。Phase 1 直接用现有 store 的 `videos[]`，**字段映射**：

| jsx 字段 | 当前 Video model 对应 |
|---|---|
| `v.title` | `v.title` ✓ |
| `v.author` | `v.author_name` ✓ |
| `v.authorColor` | **缺**，写个 helper 从 author_name 哈希出颜色 |
| `v.when` | **缺**，从 `v.first_seen_at` 算相对时间（"3 天前"）— 写个 helper |
| `v.duration` | 从 `v.duration_sec` 格式化为 "3:42" |
| `v.views` | `v.play_count`（B 站 50 条都有） |
| `v.likes` | `v.like_count` |
| `v.comments` | **缺**，显示空或 0 |
| `v.platform` | `v.platform` ✓ |
| `v.summary` | **缺**（Phase 3），显示 placeholder |
| `v.thread` | **缺**（Phase 2），显示 "评论楼功能即将上线" |
| `v.done` | Phase 1 用 `v.already_commented` 近似 |

---

## 8. 路由 & 集成

- 路由 `/mining` 已经在 `frontend/src/router/index.ts` 里，name 不变
- LeftNav 已有"引流"入口，icon 用 `search`，**可选改成 `radar` 或新 icon**（jsx 里没明示）
- Phase 1 默认沿用 `search` icon，跟 jsx 设计稿底部的 nav rail 风格一致

---

## 9. CSS / 动画

- 全部用 `style.css` 已有的 design tokens (`var(--card)`, `var(--primary)` 等)
- 动画 class `.anim-up`, `.anim-in` 已有
- `font-display`, `font-mono` 已有
- 不需要新加任何全局 CSS

---

## 10. 测试策略

Phase 1 是纯视觉重写，没新数据流，**不写单测**。验收靠：

- `pnpm --filter frontend build` 零错误
- 浏览器 dev 模式打开 `/mining` 视觉对比设计稿截图
- 跑一遍既有手测：起 mining job → 看视频卡显示 → 导出 CSV → 关弹窗

后端 `pytest sidecar/tests/` 应继续 245 全过（理论上不可能变，但跑一遍守门）。

---

## 11. 风险

| 风险 | 缓解 |
|---|---|
| Icon 扩列 path 不对（视觉跟设计稿不一致） | 参考 Lucide icons 标准 path；事后用浏览器 inspect 调 |
| Card.vue `dark` prop 不存在需要扩 | 任务里独立一个小任务先扩 Card |
| 旧 VideoTable 删了之后 import 失败 | 改造任务全部完成才删 |
| StartJobModal 重写后丢失 SSE 订阅 | Phase 1 modal 只负责收集参数，submit 后 store 处理 — 不动 store |
| 现有 50 条数据某些字段缺（如 published_at） | 视频卡上对应 chip 写 v-if="..." 条件渲染 |

---

## 12. 后续期 hook

Phase 1 不动 schema，但**视觉框架预留位置**：

| Phase 2 接入位 | Phase 1 已经在哪 |
|---|---|
| 评论楼数据展示 | `VideoCard.vue` 的"评论楼 box" div 占位 |
| composer 真能发评论 | `VideoCard.vue` 的 composer 区域 disabled，state 已经 reserve |
| 状态机 done | tab 切换 / Pill tone / 卡片状态都已经按 `already_commented` 实现，Phase 2 改成 `done` 即可 |
| 批量操作真能执行 | 浮动栏 UI 已经在，按钮绑事件即可 |

| Phase 3 接入位 | Phase 1 已经在哪 |
|---|---|
| AI 速览实际文字 | `VideoCard.vue` 的"AI 速览"box 已经占位，把 placeholder 文字换成 `v.ai_summary` 即可 |
| AI 建议续写 | composer 工具栏 "AI 建议" 按钮已经在，绑事件即可 |
