# CSM 前端 UI/UX 统一 · 设计方案

- 日期：2026-06-11
- 分支：`claude/focused-varahamihira-60097d`
- 范围：`frontend/`（Vue 3 + Tailwind 3 + Pinia + Tauri 2）
- 状态：已与用户确认，待写实现计划

## 1. 背景与现状

CSM 前端是 Vue 3 + Tailwind CSS 3 单页应用，运行在 Tauri 2 桌面壳里。通读代码后的现状：

- **颜色系统已变量化**：20+ 个设计 token 全部定义在 [`frontend/src/style.css`](../../../frontend/src/style.css) 的 `:root` 里，[`frontend/tailwind.config.js`](../../../frontend/tailwind.config.js) 把它们映射成 `bg-card` / `text-ink-2` 等 Tailwind 类。已有 `body[data-density]` / `body[data-radius]` 属性 + [`useTweaks.ts`](../../../frontend/src/composables/useTweaks.ts) 运行时切换 + localStorage(`csm.tweaks.v1`) 持久化机制。
- **暗色主题地基已就绪但未接通**：[`SettingsView.vue:956`](../../../frontend/src/views/SettingsView.vue) 已有「主题」下拉（跟随系统 / 明亮 / 暗色），但绑定的 `localUI.theme` 是一个**本地死占位**（同文件 315 行注释自述"本地占位"），不保存、不生效。全项目无 `darkMode` 配置、无 `data-theme`、无 `prefers-color-scheme` 处理。
- **shadcn 工具链已装但半套**：`package.json` 已有 `class-variance-authority` + `clsx` + `tailwind-merge`（shadcn 那套），[`lib/cn.ts`](../../../frontend/src/lib/cn.ts) 的 `cn()` 也写好了，但**全项目零引用**；只有 [`Btn.vue`](../../../frontend/src/components/ui/Btn.vue) 用了 CVA，其余 21 个 `ui/` 组件都是手写 class / inline style。无 `components.json`、无 `reka-ui`。
- **边栏比例不一致**：监测中心（导航 `monitor`，radar 图标）的左右两栏分页用 `lg:grid-cols-[1.4fr_1fr]` + `gap-6`（左列 ≈ 58%）；而 GEO 用 `340px : 1fr` + `gap 18px`（左列 ≈ 30%）。
- **存在死代码**：17 个高置信度无引用文件（首页改版遗留 + 被取代组件 + 无引用 ui 原语）。

## 2. 目标 / 非目标

### 目标
1. 监测中心所有左右两栏分页的边栏比例对齐 GEO。
2. 为应用设计明亮 + 暗色两套主题，接通已有设置入口。
3. 统一设计 token 与组件构建范式（采用 shadcn 模式，不引入 shadcn 依赖）。
4. 删除确认无用的代码文件。

### 非目标（本轮不做）
- 不重命名现有 token 为 shadcn 约定（`--background`/`--foreground` 等）—— 现有语义命名已良好且数百处在用。
- 不引入 `reka-ui` / `radix-vue` / `shadcn-vue` / `lucide` 依赖。
- 不批量补齐缺失基础件（Tabs/Switch/Popover/Checkbox…）—— 现有手写 tab 栏可用，留作"按需手写"后续项。
- 不触碰老 PyQt6 栈（`csm_gui/`、`CSM.spec`）。
- 数据中心历史页（单栏布局）不在边栏统一范围内。

## 3. 决策记录

| # | 决策 | 选定 | 理由 |
|---|------|------|------|
| Q1 | shadcn 策略 | **采用模式，不装依赖** | 暖纸暖橙身份 + 自有 120+ 图标集 + 大量定制组件，全量迁移性价比低、冲突多；工具链已在，把它用对即可。 |
| Q2 | 边栏比例 | **完全照 GEO（340px/18px）+ 保留窄屏堆叠** | 与截图一致；保留 `grid-cols-1` 兜底小窗口。 |
| Q3 | 清理范围 | **删纯死文件，保留设计系统相关** | `cn.ts`/`IconBtn`/`Select`/`Tooltip` 因半套设计系统而暂死，③ 会用到或可能复活。 |
| 主题方向 | 暗色气质 | **A · 暖咖 Espresso** | 延续亮色的暖色温度（暖灰棕底），橙色融入不刺眼，品牌同源。 |

## 4. 工作流 ① — 边栏比例统一

### 设计
新建共享布局壳 `frontend/src/components/ui/SplitPane.vue`，把 GEO 的比例固化在一处：

```
grid · 列 = 340px 1fr · gap 18px · 窄屏(< lg) 退化为 grid-cols-1 单列堆叠
```

API：具名插槽 `#left` / `#right`，各页只填内容。可选 props（如 `leftWidth`、`gap`）保留默认值，便于个别页微调，但默认即 GEO 口径。

### 替换点（监测中心两栏分页，4 文件 6 处）
- [`ZhihuMonitorModule.vue:823`](../../../frontend/src/components/monitor/ZhihuMonitorModule.vue)
- [`ZhihuSearchModule.vue:248`](../../../frontend/src/components/monitor/ZhihuSearchModule.vue) 与 `:334`（L1 任务列表 + L2 关键词结果两处）
- [`CommentMonitorModule.vue:807`](../../../frontend/src/components/monitor/CommentMonitorModule.vue)
- [`BaiduRankingPage.vue:1085`](../../../frontend/src/components/monitor/history/BaiduRankingPage.vue) 与 `:1417`（L1 + L2 两处）

[`GeoTaskModule.vue:388`](../../../frontend/src/components/monitor/geo/GeoTaskModule.vue) 同步换用 SplitPane（GEO 因此额外获得窄屏堆叠，行为更统一）。

### 不动
各面板**内部**的表格列网格（如 `1.6fr .7fr .7fr 1fr`）与边栏左右分栏无关，保持原样。

### 视觉影响（需用户知情，已确认）
知乎 / 评论 / 百度 / 知乎搜索四个分页的左侧任务列表从 ≈58% 收窄到 ≈30%，右侧详情区大幅变宽。

## 5. 工作流 ② — 明暗主题（暖咖 Espresso）

### 机制
1. **`useTweaks.ts`**：`Tweaks` 接口加 `theme: 'system' | 'light' | 'dark'`（默认 `'system'`）。`apply()` 里：
   - `theme === 'system'` → 读 `matchMedia('(prefers-color-scheme: dark)')` 决定实际明暗，并监听其 `change`。
   - 实际明暗写入 `document.body.dataset.theme`（`'light'` / `'dark'`）。
   - 复用现有 `csm.tweaks.v1` localStorage 持久化。
2. **`style.css`**：新增 `body[data-theme="dark"] { ... }` 覆盖块（见下表），并在 `:root` 为新增 token 补亮色默认值。Tailwind 配置基本不动。
3. **接通 UI**：把 [`SettingsView.vue:956`](../../../frontend/src/views/SettingsView.vue) 的 `localUI.theme` 改为读写 `useTweaks().state.theme`（移除死占位）。
4. **防 FOUC**：[`index.html`](../../../frontend/index.html) `<head>` 加极短内联脚本，首屏渲染前依据 localStorage / 系统偏好把 `data-theme` 写到 `<body>`（与现有 `data-density="cozy"` 硬编码同理，但 theme 需读存储所以用脚本）。

### 明 → 暗 token 映射（A · Espresso）

| token | 亮色 | 暗色 | 备注 |
|-------|------|------|------|
| `--bg-outer` | `#d9d1bd` | `#14110d` | 窗外框 |
| `--bg-inner` | `#f1ebde` | `#1b1713` | 页面底 |
| `--card` | `#fbf7ec` | `#262019` | 卡面 |
| `--card-2` | `#f6f0e1` | `#2f2820` | 嵌套卡 |
| `--card-white` | `#ffffff` | `#312a21` | 最高浮起面 |
| `--ink` | `#1c1a17` | `#f3ede0` | 主文字 |
| `--ink-2` | `#4d4943` | `#c9c0ad` | 次文字 |
| `--ink-3` | `#7a7569` | `#968d7b` | 三级文字 |
| `--ink-4` | `#a89f8d` | `#6e6657` | 最弱文字 |
| `--line` | `rgba(28,26,23,.08)` | `rgba(245,237,224,.10)` | 细边框 |
| `--line-2` | `rgba(28,26,23,.14)` | `rgba(245,237,224,.16)` | 强边框 |
| `--primary` | `#ee6a2a` | `#f0732f` | 主橙（略提亮） |
| `--primary-soft` | `#f7d5be` | `#3a2a1c` | 软填充底 |
| `--primary-deep` | `#c9521f` | `#f78a4f` | **语义反转**：暗色 hover 变亮 |
| `--yellow` | `#f5c042` | `#f0c14d` | 警告 |
| `--yellow-soft` | `#fbe7a3` | `#3a3320` | 警告软底 |
| `--green` | `#7a9b5e` | `#8fae6f` | 成功 |
| `--red` | `#d85a48` | `#e06a58` | 错误 |
| `--dark` | `#1c1a17` | `#f3ede0` | **反相**：重按钮/重卡底暗色变浅 |
| `--dark-2` | `#2a2622` | `#e6dccb` | `--dark` 的 hover |

### 新增 token（收编当前硬编码色；`:root` 给亮色默认 + 暗色块覆盖）

| token | 亮色默认 | 暗色 | 收编对象 |
|-------|---------|------|---------|
| `--scroll-thumb` | `rgba(28,26,23,.18)` | `rgba(245,237,224,.18)` | 全局/geo/floor 滚动条 thumb |
| `--scroll-thumb-hover` | `rgba(28,26,23,.32)` | `rgba(245,237,224,.32)` | 滚动条 hover |
| `--frosted-bg` | `rgba(255,255,255,.55)` | `rgba(38,32,25,.55)` | `.card-frosted` 背景 |
| `--frosted-border` | `rgba(255,255,255,.65)` | `rgba(245,237,224,.08)` | `.card-frosted` 边框 |
| `--green-soft` | `#dde7d2` | `#2a3320` | StatCard 上升 pill |
| `--red-soft` | `#f3d3cd` | `#3a2420` | StatCard 下降 pill |

### 需逐个改造为主题感知的硬编码点
- [`style.css`](../../../frontend/src/style.css) 内 `.card-frosted`、各 `::-webkit-scrollbar-thumb`、`.floor-scroll-*`、`.geo-scroll` 的 rgba 字面 → 改引用上表 token。
- [`StatCard.vue`](../../../frontend/src/components/home/StatCard.vue) `pillStyle()` 的 `#dde7d2` / `#f3d3cd` → `--green-soft` / `--red-soft`。
- `GeoPlatformBlock.vue` 的 rgba 色块 tint → token 化或加暗色分支。
- 平台品牌色（`PlatformChip.vue` 的 B站粉等）：保留色相，按需补暗色下的对比/边框，不强行反相。

### 已知纠结点（实现时处理）
- `--dark` / `bg-dark` / `text-dark` 全量用法需审计：多数是"重按钮/重卡"语义（反相成浅色正确），但若有"固定深色 hero"语义需保持深色，则改用一个新的 `--espresso-fixed` 之类固定 token。
- 暗色下 `:focus-visible` 橙色 outline、`.blur-blob` 发光等装饰元素需目测确认观感。

## 6. 工作流 ③ — 设计 Token 统一（采用 shadcn 模式）

1. **`cn()` 转正**：组件内条件 class 拼接统一改用 [`cn()`](../../../frontend/src/lib/cn.ts) 替代手写数组 / 三元链。
2. **CVA 系统化**：以 [`Btn.vue`](../../../frontend/src/components/ui/Btn.vue) 为范本，把有变体的原语（`Pill` 的 tone、`Card` 的 muted/dark/padless 等）改写成 cva 变体表，统一变体口径。
3. **token 命名保持现状**：不重命名。
4. **沉淀规范**：新建 `docs/design-system.md`，固化 token 清单、组件变体口径、`cn()` / CVA 用法约定，杜绝再引入新的硬编码颜色。
5. **缺失基础件**：本轮不批量补，记为后续"按需手写"项。

> 注：本工作流与 ② 的"收编硬编码色"部分天然耦合（都在动 token / 组件颜色），实现时合并在同一阶段更省返工。

## 7. 工作流 ④ — 删除无用文件

### 删除（13 个纯死文件，已逐一验证零引用）
- 旧首页卡（被 2026-06-05 首页改版取代）：`home/BaiduSeoCard.vue`、`home/GeoCard.vue`、`home/ZhihuCard.vue`、`home/ZhihuSearchCard.vue`、`home/VideoMiningCard.vue`、`home/KeywordTrendCard.vue`
- 被取代组件：`article/AssemblyTree.vue`、`monitor/geo/GeoKeywordMatrix.vue`、`templates/MultiValuePicker.vue`、`utils/saveFile.ts`
- 无引用 ui 原语：`ui/Avatar.vue`、`ui/Bars.vue`、`ui/Blob.vue`

### 保留
- `lib/cn.ts`（③ 要用）
- `ui/IconBtn.vue`、`ui/Select.vue`、`ui/Tooltip.vue`（设计系统统一时可能复活）

### .gitignore 补充
- `frontend/vite.config.js`、`frontend/vite.config.d.ts`（`vue-tsc -b` 产物，不应提交）
- `.superpowers/`（本次可视化工具的本地产物）

### 不碰
`csm_gui/`、`CSM.spec`（老 PyQt6 栈，超范围）。

### 删除前再核
实现时对每个待删文件再跑一次全仓引用确认（PascalCase / kebab-case / `ui/X` 路径 / 导出名），删完跑 `vue-tsc -b` + `vitest run` 确保零破坏。

## 8. 落地顺序（4 个独立 PR，互不阻塞）

1. **清理（④）** — 最快，先减面，降低后续改动面。
2. **Token 地基（③ + ② 的硬编码色收编）** — 为暗色铺路。
3. **暗色主题（② 余下）** — 依赖第 2 步的 token。
4. **边栏壳（①）** — 完全独立，可任意时机并入。

每个 PR 独立可 merge；按项目惯例走 PR 流程（push 分支 + `gh pr create`，停在 pending 等网页 merge）。

## 9. 测试与验证
- 每个 PR：`cd frontend && npx vue-tsc -b`（类型）+ `npx vitest run`（单测）。注意 `vue-tsc -b` 会 emit `vite.config.js` / `.d.ts`，跑完 `git checkout --` 还原（④ 已把它们加进 .gitignore）。
- 边栏（①）：真机 / dev 起应用，逐个 tab 目测左右比例 = GEO，并拖窄窗口验证堆叠。
- 主题（②③）：明 / 暗 / 跟随系统 三态切换；切换后刷新验证持久化；冷启动验证无 FOUC（首屏不闪亮色）；逐页目测暗色下文字对比、磨砂玻璃、滚动条、状态 pill、平台 chip。
- 清理（④）：删除后全量构建 + 单测通过。

## 10. 风险
- 暗色是 greenfield，硬编码色散落约 20%，易漏；以 token 收编 + 逐页目测兜底。
- `--dark` / `--primary-deep` 的语义反转若审计不全会出现"暗色里某按钮 hover 反而变暗 / 重卡变浅不符预期"，需全量 grep 用法。
- 边栏收窄后，原本依赖宽左栏的内部表格列（多列 `fr`）在 340px 下可能拥挤，需逐页目测，必要时微调内部列宽（属 ① 的收尾）。
```
