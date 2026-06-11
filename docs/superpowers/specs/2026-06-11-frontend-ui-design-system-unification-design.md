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
5. 清退老 PyQt6 桌面栈（`csm_gui/` 及其配套），彻底拔掉 PyQt6 依赖面。
6. 托盘右键菜单微调：去掉「Content SEO Maker」标题项与（未生效的）快捷键提示。
7. 启动时自动检查新版本，有则弹窗提醒（复用现成更新弹窗 + 流程，补启动触发）。

### 非目标（本轮不做）
- 不重命名现有 token 为 shadcn 约定（`--background`/`--foreground` 等）—— 现有语义命名已良好且数百处在用。
- 不引入 `reka-ui` / `radix-vue` / `shadcn-vue` / `lucide` 依赖。
- 不批量补齐缺失基础件（Tabs/Switch/Popover/Checkbox…）—— 现有手写 tab 栏可用，留作"按需手写"后续项。
- 数据中心历史页（单栏布局）不在边栏统一范围内。

## 3. 决策记录

| # | 决策 | 选定 | 理由 |
|---|------|------|------|
| Q1 | shadcn 策略 | **采用模式，不装依赖** | 暖纸暖橙身份 + 自有 120+ 图标集 + 大量定制组件，全量迁移性价比低、冲突多；工具链已在，把它用对即可。 |
| Q2 | 边栏比例 | **完全照 GEO（340px/18px）+ 保留窄屏堆叠** | 与截图一致；保留 `grid-cols-1` 兜底小窗口。 |
| Q3 | 清理范围 | **删纯死文件，保留设计系统相关** | `cn.ts`/`IconBtn`/`Select`/`Tooltip` 因半套设计系统而暂死，③ 会用到或可能复活。 |
| 主题方向 | 暗色气质 | **A · 暖咖 Espresso** | 延续亮色的暖色温度（暖灰棕底），橙色融入不刺眼，品牌同源。 |
| Q4 | 老 PyQt6 栈 | **完整拔除（新增工作流 ⑤）** | 排查确认：sidecar/csm_core 仅注释引用、CI 不跑 GUI 测试、发版用 build_sidecar 非 CSM.spec；唯一会断的是 `pip install -e .` 读 `csm_gui._version`，repoint 即可。即代码注释自述的 "migration stage D"。 |
| Q5 | 托盘菜单 | **去标题 + 去快捷键提示（工作流 ⑥）** | 「Content SEO Maker」标题项 + Ctrl+Shift+C / Ctrl+Q 提示；快捷键从未真正绑定（仅提示文字），删除零功能影响、反消除误导。 |
| Q6 | 启动更新提醒频率 | **支持「跳过此版本」（工作流 ⑦）** | 有新版才弹；弹窗加「跳过此版本」记住版本号，同版本不再反复弹，出更新的版本才再弹；手动检查忽略 skip。 |

## 4. 工作流 ① — 边栏对齐 GEO（比例 + 信息架构）

> **决策升级（已确认）**：不只是换比例。监测中心左栏的深层列表（L2）现在塞了 4–5 列指标，340px 下放不下；对齐 GEO 的真正含义是**连 GEO 的两栏信息架构一起搬**——左栏瘦成导航、指标移到变宽的右详情。本工作流是**每页一次小型 UX 重排**，非纯 CSS 改比例。案例对照见 `.superpowers/brainstorm/<session>/content/layout-case-study.html`。

### 4.1 共享布局壳
新建 `frontend/src/components/ui/SplitPane.vue`，把 GEO 的比例固化在一处：

```
grid · 列 = 340px 1fr · gap 18px · 窄屏(< lg) 退化为 grid-cols-1 单列堆叠
```

具名插槽 `#left` / `#right`，各页只填内容；可选 props（`leftWidth` / `gap`）默认 = GEO 口径。替换以下 6 处（含 GEO 自身换用同壳，使其也获得窄屏堆叠）：
- [`ZhihuMonitorModule.vue:823`](../../../frontend/src/components/monitor/ZhihuMonitorModule.vue)
- [`ZhihuSearchModule.vue:248`](../../../frontend/src/components/monitor/ZhihuSearchModule.vue) 与 `:334`
- [`CommentMonitorModule.vue:807`](../../../frontend/src/components/monitor/CommentMonitorModule.vue)
- [`BaiduRankingPage.vue:1085`](../../../frontend/src/components/monitor/history/BaiduRankingPage.vue) 与 `:1417`
- [`GeoTaskModule.vue:388`](../../../frontend/src/components/monitor/geo/GeoTaskModule.vue)（参考样式，统一到壳）

### 4.2 左栏：瘦成 GEO 式导航（4 页通用）
- **L1 任务列表**：瘦成 `名称(+计数·品牌副标) | 关键状态 Pill | 操作`，与 GEO 一致；去掉永远是「—」的变化列（百度 / 知乎搜索 L1）。
- **L2 列表**（问题 / 视频 / 关键词，现 4–5 列）：瘦成 `名称 + 一个关键状态 Pill + 操作` 导航行；次要指标降为名称下副标（如「1.2w 浏览」「默认2·资讯1」「卡位2·首位#1」「#3·日期」），其余（变化 / 趋势 / 平台 / 多榜）移到右栏。
- **操作列收成一个 `⋯`**：三个图标按钮（运行 / 编辑 / 删除）→ 一个 `⋯` 触发，点开弹出菜单。复用现成 [`Dropdown.vue`](../../../frontend/src/components/ui/Dropdown.vue)（`items:[{key,label,icon,tone:'danger'}]` + `@select`），删除项 `tone:'danger'`。
- **层级导航**：钻进 L2 时左栏顶部加「← 返回」面包屑（知乎已有，其余补齐）。评论页平台子页签（B站 / 抖音 / 快手）保留在左栏顶部。
- 列宽统一向 GEO 的 `1.5fr .9fr 1.1fr` 口径靠拢。

### 4.3 右栏：逐页详情设计（已逐页确认）
通则：变宽到 ~70% 后，右栏在 **L1（选中总任务）显示汇总**，钻进 **L2/L3（选中关键词/问题/视频）显示单项详情**。参考 GEO `GeoKeywordDetail`。KPI 拉成一排、趋势与列表左右并排而非堆叠。各页确认如下：

**4.3.1 知乎监测**（L1 批次 → L2 问题）
- **L1 批次汇总**：KPI 四联 = 问题数 / 目标品牌 / 命中问题数(X/Y，新增聚合) / 平均卡位(新增聚合) + 「问题概览」速览表 + 导出·定时。
- **L2 问题详情**：KPI 五联 = 当前卡位 / 较上次变化 / 最高排名 / 浏览量(迁自左栏) / **自家命中数(新增)**；下方 7 天卡位趋势(左) + 前 N 条答案列表(右，命中自家高亮)。

**4.3.2 评论监测**（L1 任务 → L2 视频列表 → L3 单视频）
- 右栏规则（[CommentMonitorModule.vue:1078](../../../frontend/src/components/monitor/CommentMonitorModule.vue)）：**未选视频 → 留存汇总**（范围随是否选中任务）；**选中视频 → 单视频详情**。
- **L1**：全部任务留存汇总 = 留存率趋势(7天) + 被删/折叠评论列表。
- **L2**：该任务留存汇总 + 启停/频率控件 + "选视频看详情"提示。
- **L3**：单视频详情 = KPI 三联(评论排名 / 状态 / 总评论数) + 我的评论原文 box + 操作(打开视频 / 立刻监测 / 补发评论)。**不加抢占者列表**（已确认去掉）。

**4.3.3 百度排名**（L1 任务 → L2 关键词）
- **L1 任务汇总**：KPI 四联 = 关键词数 / 目标品牌 / 命中关键词数(新增聚合) / 最佳排名(新增聚合) + 14 天「理想卡位关键词数」趋势 + 关键词速览 + 导出·定时。
- **L2 关键词详情**：KPI 三联 = 默认搜索卡位 / 最新资讯卡位 / 最佳排名；14 天趋势；**默认搜索排名 + 最新资讯排名两榜并排**（资讯榜蓝框，仅 news_present 时）；**风控提示保留**(riskControlMeta)。

**4.3.4 知乎搜索**（L1 任务 → L2 关键词）
- **L1 任务汇总**：KPI 四联 = 关键词数 / 目标品牌 / 命中关键词数(新增聚合) / 最佳首位(新增聚合) + 关键词速览 + 导出·定时（与知乎一致，不加趋势）。
- **L2 关键词详情**：KPI 三联 = 卡位数量 / 最高排名 / **自家命中数(新增)**；7 天卡位趋势(左) + 前 10 结果列表(右，带内容类型标记 文章/回答 + 自家高亮)；**全文需 Cookie 提示保留**(fulltextNoCookie)。

> 新增的聚合 KPI（命中数 / 平均·最佳排名）均由现有每项数据聚合得到，**不需要新后端字段**；所有「自家命中数」复用现有 `matches_brand` 计数。

### 4.4 视觉影响（已确认）
知乎 / 评论 / 百度 / 知乎搜索四页：左栏 ≈58% → ≈30% 且列表瘦身、右详情大幅变宽并重排（L2 指标列迁入右栏）。每页改动落在 4.2 + 4.3。

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

### 老 PyQt6 栈
`csm_gui/`、`CSM.spec` 等独立为**工作流 ⑤**（见下），不并入本前端清理工作流。

### 删除前再核
实现时对每个待删文件再跑一次全仓引用确认（PascalCase / kebab-case / `ui/X` 路径 / 导出名），删完跑 `vue-tsc -b` + `vitest run` 确保零破坏。

## 8. 工作流 ⑤ — 清退老 PyQt6 栈

排查结论：**运行时与发版均不依赖**老栈 —— sidecar / csm_core 对 `csm_gui` 只有注释引用（无 import），CI 不跑 Python 测试（[ci.yml:9](../../../.github/workflows/ci.yml) 明示省略 pytest job），发版走 `build_sidecar.py` 而非 `CSM.spec`。唯一会断的线：[release.yml:43](../../../.github/workflows/release.yml) 的 `pip install -e .` 经 pyproject 读 `csm_gui._version` —— **必须先 repoint**。

### 删除
- `csm_gui/`（整个目录，~70 文件的 PyQt6 GUI）
- `CSM.spec`（老 GUI 的 PyInstaller spec，发版已不用）
- `main.py`（`from csm_gui.app import run` 的老启动入口；新栈走 Tauri→sidecar）
- `tests/gui/`（~38 个测试，全 import csm_gui；CI 本就不跑）
- `scripts/clear_account.py`、`scripts/make_icon.py`（与 csm_gui 耦合）

### 改 `pyproject.toml`
- 移除 `[project.optional-dependencies] gui`（PyQt6 / PyQt6-Fluent-Widgets）
- 移除 `[project.scripts] csm-gui = "csm_gui.__main__:main"`
- `[tool.setuptools.packages.find] include`：去掉 `csm_gui*`
- 移除 `[tool.setuptools.package-data] csm_gui`
- **repoint `[tool.setuptools.dynamic] version`**：从 `csm_gui._version.__version__` 改到非老栈来源（静态值，或 `csm_core` 的版本模块）—— 必须先做，否则 `pip install -e .` 解析版本失败
- `[project.optional-dependencies] dev`：移除 `pytest-qt`（仅 GUI 测试需要）

### 顺带
`csm_core/` 内对 csm_gui 的**注释/docstring**（config.py、monitor/\_\_init\_\_.py、template/schema.py）可顺手清理表述，非必须。

### 验证
`pip install -e .` 成功（版本解析不再依赖 csm_gui）+ `python scripts/build_sidecar.py` 跑通 + sidecar smoke；全仓确认无 `from csm_gui` / `import csm_gui` 残留。

## 9. 工作流 ⑥ — 托盘右键菜单微调

[`frontend/src-tauri/src/tray.rs`](../../../frontend/src-tauri/src/tray.rs)：去掉顶部「Content SEO Maker」标题项和快捷键提示。

- 删除 disabled 的 `header` MenuItem（"Content SEO Maker"，:29-35）及其分隔符。
- 两个 accelerator 提示置空：`show_item` 的 `Some("Ctrl+Shift+C")` → `None::<&str>`，`quit_item` 的 `Some("Ctrl+Q")` → `None::<&str>`。
- **零功能影响**：这两个快捷键从未真正绑定（全仓无 `global_shortcut` 注册，仅 tray.rs 两处提示字符串，代码注释自述 "not wired yet"），删除只是去掉误导性提示文字。
- 结果菜单：`显示主窗口` ──(分隔线)── `退出 CSM`（保留一条分隔符避免误点退出）。
- 同步更新文件顶部 doc 注释（移除"brand header / accelerator hints"相关描述）。

## 10. 工作流 ⑦ — 启动时新版本弹窗提醒

现状：更新检查只有手动入口（[SettingsView.vue:578](../../../frontend/src/views/SettingsView.vue) `checkForUpdate` + 设置页按钮），**启动时不自动检查**。弹窗与下载/重启全链路现成（[useUpdateAlert.ts](../../../frontend/src/composables/useUpdateAlert.ts) + [UpdateAvailableModal.vue](../../../frontend/src/components/ui/UpdateAvailableModal.vue)），缺的只是启动自动触发。

- **抽共享流程**：把 `checkForUpdate` 里的"检查 → prompt → download(SSE) → install_and_restart"整条流程从 SettingsView 抽成共享 composable（如 `useUpdateFlow`），设置按钮与启动检查共用，避免逻辑复制。
- **启动检查**：[App.vue:67](../../../frontend/src/App.vue) `onMounted` 等 sidecar ready 之后，**静默**调 `updaterCheck()`；有新版且版本未被"跳过"才弹 prompt。
- **不打扰**：启动检查在「无更新 / 网络失败」时不弹不 toast（与手动按钮的 toast 反馈区分）；避开首启 onboarding（首次运行不弹）。
- **跳过此版本**：`UpdateAvailableModal` 的 prompt 阶段加「跳过此版本」按钮，点击记住该 version（localStorage，如 `csm.update.skip`）。下次启动检查时 `info.version === skipped` 则不弹；出更新的版本号才再弹。**手动检查（设置按钮）忽略 skip，永远显示**。
- 不改弹窗的下载/重启逻辑与视觉（视觉随 ②③ 主题统一）。

## 11. 落地顺序（7 个独立 PR，互不阻塞）

1. **清退老栈（⑤）** — 独立、纯删 + 一处 pyproject 改；先做立刻缩小 Python 侧面积。
2. **清理前端死文件（④）** — 前端减面。
3. **Token 地基（③ + ② 的硬编码色收编）** — 为暗色铺路。
4. **暗色主题（② 余下）** — 依赖第 3 步的 token。
5. **边栏对齐 GEO（①）** — 完全独立；含每页 UX 重排（左栏瘦身 + 右栏重排），是最大的一个 PR，可按页拆成 4 个子 PR（知乎 / 评论 / 百度 / 知乎搜索）分批并入。
6. **托盘菜单微调（⑥）** — 独立的小 Rust 改动，可单独小 PR 或随任一 PR 捎带。
7. **启动更新提醒（⑦）** — 独立；抽共享 composable + App.vue 启动钩子 + 弹窗加"跳过此版本"。

每个 PR 独立可 merge；按项目惯例走 PR 流程（push 分支 + `gh pr create`，停在 pending 等网页 merge）。

## 12. 测试与验证
- 前端每个 PR：`cd frontend && npx vue-tsc -b`（类型）+ `npx vitest run`（单测）。注意 `vue-tsc -b` 会 emit `vite.config.js` / `.d.ts`，跑完 `git checkout --` 还原（④ 已把它们加进 .gitignore）。
- 老栈清退（⑤）：`pip install -e .` 成功 + `python scripts/build_sidecar.py` 跑通 + 全仓无 `import csm_gui` 残留。
- 边栏（①）：真机 / dev 起应用，逐页验证 ——（a）左右比例 = GEO 且窄屏堆叠；（b）左栏瘦身后无截断 / 溢出；（c）右栏重排后从左栏迁来的指标（浏览量 / 变化 / 趋势 / 平台）完整呈现、无丢失。
- 主题（②③）：明 / 暗 / 跟随系统 三态切换；切换后刷新验证持久化；冷启动验证无 FOUC（首屏不闪亮色）；逐页目测暗色下文字对比、磨砂玻璃、滚动条、状态 pill、平台 chip。
- 清理（④）：删除后全量构建 + 单测通过。
- 托盘（⑥）：`cd frontend/src-tauri && cargo build` 通过；起应用右键托盘目测菜单只剩 显示主窗口 / 退出 CSM，无标题、无快捷键提示。
- 启动更新提醒（⑦）：mock `updaterCheck` 返回有/无更新两种 → 启动分别弹/不弹；点"跳过此版本"后重启应用不再为该版本弹、设置页手动检查仍弹；无更新 / 断网时启动静默（无弹窗、无 toast）。

## 13. 风险
- 暗色是 greenfield，硬编码色散落约 20%，易漏；以 token 收编 + 逐页目测兜底。
- `--dark` / `--primary-deep` 的语义反转若审计不全会出现"暗色里某按钮 hover 反而变暗 / 重卡变浅不符预期"，需全量 grep 用法。
- 边栏（①）已升级为每页 UX 重排：风险在于 4 页右栏各自定制的工作量、跨页视觉一致性、以及左栏指标迁右栏时不丢信息；逐页 review + 与 GEO 现状对照兜底。
- 老栈清退（⑤）：版本 repoint 必须先于删除 `csm_gui/_version.py`，否则发版 CI 的 `pip install -e .` 会炸；删除后确认无脚本/文档残留 `python main.py` 老启动方式。
- 启动更新提醒（⑦）：必须 `whenReady()`（sidecar ready）之后再查，且 try/catch 静默吞错——更新服务器不可达不能阻塞或打断启动；与首启 onboarding 的时序要避让。
