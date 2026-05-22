# Content SEO Maker — 设计系统

> 这份文档定义 CSM 桌面端的视觉与组件规范。**所有新增 / 重构页面必须先对齐这里的 token 与模式**，禁止在组件里硬编码颜色、字号、圆角；样式分歧统一回流到这份文档 + [frontend/src/style.css](../frontend/src/style.css)。
>
> 适用范围：`frontend/src/**`（Vue 3 + Tailwind + Tauri WebView2）。后端、老 PyQt 客户端不受约束。

---

## 1. 设计原则

1. **暖色"纸面"基调** — 整窗背景 `--bg-inner` 是米黄色，所有卡片在这层纸上漂浮，不依赖深色 / 玻璃质感。透明背景由 Tauri 的 `transparent:true` 接管。
2. **密度可调** — `body[data-density]` 三档（compact / cozy / loose）由 [SettingsView](../frontend/src/views/SettingsView.vue) 切换，组件内 padding/gap 通过 `--density-pad` / `--density-gap` 读取，**不写死像素**。
3. **圆角可调** — `body[data-radius]` 三档（tight / medium / bold），通过 `--radius-card` / `--radius-inner` / `--radius-pill` 读取。
4. **主色可调** — 用户可在设置里改 `--primary`，所以橙色相关 UI 不能硬编码 `#ee6a2a`，必须走变量。
5. **不做整页滚动** — 桌面应用，外层卡片 = 窗口，主区域 `overflow-hidden`；超出的内容由具体卡片自己 `overflow-y-auto`。
6. **暖色 blob 作为氛围** — Hero / Calendar 这类大卡用 `.blur-blob` 给一抹色感，但不是必备元素；信息密集的监测卡不加 blob。

---

## 2. 颜色 Token

全部定义在 [frontend/src/style.css](../frontend/src/style.css) `:root`，通过 [frontend/tailwind.config.js](../frontend/tailwind.config.js) 映射到 Tailwind class（`bg-card` / `text-ink-2` 等）。

### 背景 / 表面
| Token | 值 | 用途 |
|---|---|---|
| `--bg-outer` | `#d9d1bd` | 旧版桌面外层（Tauri transparent 之后基本不可见） |
| `--bg-inner` | `#f1ebde` | 主窗口背景"纸张" |
| `--card` | `#fbf7ec` | 一级卡片底色（监测卡、recent docs） |
| `--card-2` | `#f6f0e1` | 二级卡片底色（hero 卡 muted、行 item 背景） |
| `--card-white` | `#ffffff` | 输入框、行项 hover 等纯白局部 |
| `--dark` | `#1c1a17` | 深色卡（calendar 已下线，仅余 quick-tile icon 底） |
| `--dark-2` | `#2a2622` | 深色卡的次级层 |

### 文字（"ink" 阶梯，深→浅）
| Token | 值 | 用途 |
|---|---|---|
| `--ink` | `#1c1a17` | 主文本、大标题 |
| `--ink-2` | `#4d4943` | 次要文本、列表元数据 |
| `--ink-3` | `#7a7569` | 标签 / 时间戳 / 副副标 |
| `--ink-4` | `#a89f8d` | 空状态文案、disabled |

### 线条
| Token | 值 | 用途 |
|---|---|---|
| `--line` | `rgba(28,26,23,0.08)` | 卡片描边、分隔线 |
| `--line-2` | `rgba(28,26,23,0.14)` | 强分隔（如进度条底） |

### 语义色
| Token | 值 | 用途 |
|---|---|---|
| `--primary` | `#ee6a2a`（可调） | 主行动色、活跃 nav |
| `--primary-soft` | `#f7d5be` | primary chip 浅底 |
| `--primary-deep` | `#c9521f` | primary hover / 按下 |
| `--yellow` | `#f5c042` | 已完成状态、warn 中等 |
| `--yellow-soft` | `#fbe7a3` | yellow chip 浅底 |
| `--green` | `#7a9b5e` | 成功 / 已发布 |
| `--red` | `#d85a48` | 错误 / 异动下跌 |

### 派生色（用于状态 chip）
**禁止在组件里现编 hex**。这些组合在 `home/RecentDocsCard.vue` `badgeStyle` / `pillStyle` 沿用，新建状态 chip 时复用：

- 已发布 / 成功：`background:#dde7d2; color:#4d6b2f`
- 草稿 / 警告：`background:var(--yellow-soft); color:#7a5400`
- 错误 / 下跌：`background:#f3d3cd; color:#a3382a`
- 中性 / 持平：`background:rgba(28,26,23,0.06); color:var(--ink-2)`

---

## 3. 字体

| 类 | 字体栈 | 用途 |
|---|---|---|
| `.font-display` | Plus Jakarta Sans + Noto Sans SC + system | 标题、统计大数字 |
| `.font-serif-cn` | Noto Serif SC | 长文阅读区（ArticleView 正文） |
| `.font-mono` | JetBrains Mono | 数字 tabular（`tabular-nums`）、ID、命中行 |
| 默认 body | 同 display 栈 | 普通文本 |

`display` 标题统一带 `letter-spacing: -0.4px` ~ `-0.5px`，紧凑感。

### 字号阶梯（首页内常用）
| 用途 | 字号 | 字重 |
|---|---|---|
| 卡片小标（UPPERCASE） | 10.5px | 500，`tracking-[1.5px]` |
| 卡片大标 | 18px | bold |
| Hero 大标 | 22px–26px | bold |
| 副标 / 元数据 | 11px–11.5px | 500 |
| 列表行主文 | 12px–12.5px | 600 |
| 列表行副文 | 10.5px | 400 |
| 时间戳 | 10px | 400 |
| 状态 chip | 10.5px | 500 |
| 大统计数字 | 24px–30px | bold，`line-height:1` |

---

## 4. 圆角 / 间距

### 圆角
| Token | medium 默认 | 用途 |
|---|---|---|
| `--radius-card` | 22px | 一级卡片 |
| `--radius-inner` | 14px | 卡片内的子块（如 hero 内 quick tile） |
| `--radius-pill` | 999px | 胶囊按钮 / 搜索框 / chip |

行内小图标方框（24×24）走 `borderRadius: '7px'`；状态色块（28×28）走 `borderRadius: '8px'`。

### 间距
- 卡片内 padding：`--density-pad`（cozy = 22px，监测密集卡可降到 16px）
- 行间 gap：`--density-gap`（cozy = 16px）
- 首页栅格 gap：**22px**（统一）
- 行 item 之间 gap：6–8px

---

## 5. 组件契约

### 5.1 Card（[Card.vue](../frontend/src/components/ui/Card.vue)）
- 默认底色 `--card`；`muted` prop 切换 `--card-2`；`padless` 关闭默认 padding
- 圆角永远 `--radius-card`
- 描边 `1px solid var(--line)`

**新建一级卡片时禁止自己手写 `section + style`**，要么用 `<Card>`，要么至少照搬 Card 的 `border / border-radius / background` 三件套（[BaiduSeoCard 顶部](../frontend/src/components/home/BaiduSeoCard.vue) 就是手写但完全对齐的样板）。

### 5.2 标题区（home 监测卡通用）
```
┌─────────────────────────────────────────────────────┐
│ MONITOR · 百度 SEO         <--小标 10.5px uppercase  │
│ 百度关键词                  <--大标 18px bold         │
│ 排名异动 3                  <--副标 11px ink-3        │
│                                            [详情 →]  │
└─────────────────────────────────────────────────────┘
```
- 右上详情按钮：胶囊 28px 高，`background:var(--card-2)`，`border:1px solid var(--line)`，文字 11.5px

### 5.3 列表行（监测卡 / recent docs）
- 行容器：`background:var(--card-2)`，`border:1px solid var(--line)`，`border-radius:10px`，`padding:8–10px`
- 行内布局：[左 icon 方框 24/28] + [主文 + 副文] + [可选 chip] + [时间戳]
- hover：`background:var(--card-white)`（仅可点击行）

### 5.4 状态 chip
- 高 20px，圆角 999px，padding-x 8px
- 字号 10.5px，font-weight 500
- 颜色配色查 §2 "派生色"

### 5.5 胶囊输入条（hero、顶栏搜索）
- 容器：`background:var(--card-white)`，`border:1px solid var(--line)`，`border-radius:var(--radius-pill)`，左 padding 18px，右 padding 6px
- 内部从左到右：搜索 icon (16px, opacity 0.6) + input + 行动按钮（dark variant）
- input 必须 `outline:none` 防双重描边（参见 `App.vue` `.topbar-search` 注释）

### 5.6 Sparkline（[Sparkline.vue](../frontend/src/components/ui/Sparkline.vue)）
- 监测卡内默认 `:width="220" :height="28" :show-last="false" fluid`
- 趋势上行用 `var(--green)`，下行 `var(--red)`，平稳 `var(--primary)`
- 数据为空时**整段 Sparkline 不渲染**（不要画一条直线占位）

---

## 6. 首页栅格契约

[HomeView.vue](../frontend/src/views/HomeView.vue) 必须三段 flex：

```
Row 1   ─ 280px 固定，3 列 grid（左 2/3 hero + 右 1/3 shortcut column）
Row 2   ─ 280px 固定，4 列 grid（百度 / 知乎 / 评论留存 / 视频抓取）
Row 3   ─ flex-1 min-h-0，最近文档（4 列 grid，每卡 ~280×120）
gap     ─ 22px 行间 + 22px 列间
```

- HomeView 根 `h-full flex flex-col`，所有卡片 `h-full`
- 监测卡内部允许 `overflow-y-auto`，但 **不允许溢出到 HomeView 之外**
- 任何时候不允许整页滚动 — 整页滚意味着布局错了

---

## 7. 新增组件 checklist

新加一张首页卡 / 重构页面时，按这条 checklist 逐项过：

- [ ] 颜色全部走 §2 token，无 hex 字面量
- [ ] 字号 / 字重落在 §3 阶梯内
- [ ] 圆角 / padding 用 CSS var，不写死像素
- [ ] 标题区符合 §5.2 三段结构（小标 + 大标 + 副标 + 右上按钮）
- [ ] 列表行符合 §5.3 (`card-2` 底 + `line` 描边 + 10px 圆角)
- [ ] 空状态有显式文案，不留空白（仿现有"暂无 X · 接入 Y 后会自动 Z"）
- [ ] 数据未加载完毕时显示 `加载中…` 或 `<Spinner :size="14" />`
- [ ] 卡片 `h-full overflow-hidden flex flex-col`，子滚动区 `min-h-0 flex-1 overflow-y-auto`
- [ ] 不在卡内部触发整页布局变化（不要 `position:absolute` 飘出去）

---

## 8. 改动流程

1. **加新 token** → 改 [style.css](../frontend/src/style.css) `:root`，然后在 [tailwind.config.js](../frontend/tailwind.config.js) 注册映射
2. **批量改色** → 只改 `:root`，全局生效
3. **加密度档** → 同时更新 §4 与 `body[data-density="loose"]` 等选择器
4. **加新卡片** → 复制现有 home 卡作模板，跑一遍 §7 checklist
5. **重大视觉调整** → 先更新这份文档对应章节，再改代码（review 时审阅人查文档对照实现）

---

## 9. 反模式（已踩过的坑）

- ❌ 用 `min-h-full` 兜底卡片错乱 → 整页跟着滚。固定高度 + `flex-shrink-0` 才对。
- ❌ 用全局 `transition: opacity` 切路由 → Tauri WebView2 偶尔卡在 `opacity:0` 不还原（[App.vue](../frontend/src/App.vue) 注释里有详情）。
- ❌ 输入框 `:focus-visible` 直接套全局橙边 → 跟胶囊容器双重描边。input 自己关 outline，靠容器视觉聚焦。
- ❌ 空数据画空图表 → 用户不知道是"零"还是"挂了"。空状态走文案，不画 sparkline 直线。
- ❌ 在组件里硬编码 `#ee6a2a` → 用户改主色后这一处不跟着变。永远走 `var(--primary)`。

---

## 10. 文档与代码的同步责任

- 添加 / 改动 token 或组件契约时，**同一 PR 必须更新这份文档**
- Review 时如发现"代码用了未在此文档中登记的颜色 / 字号 / 间距"，作者补登或换成已有 token
- 这份文档是设计意图的"事实来源"。代码与文档冲突时，PR 决定哪边为准，不留模糊地带
