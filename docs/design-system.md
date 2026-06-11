# CSM 前端设计系统约定

> 目的：固化设计 token 与组件构建范式，杜绝新增硬编码颜色 / 不一致的变体写法。

## 1. 颜色一律走 token

所有颜色定义在 `frontend/src/style.css` 的 `:root`，并经 `tailwind.config.js` 映射成 Tailwind 类（`bg-card` / `text-ink-2` …）。**禁止**在组件里写死 hex / rgba。

### 不透明色
用语义 token：`--bg-outer/-inner`、`--card/-2/-white`、`--ink/-2/-3/-4`、`--line/-2`、`--primary/-soft/-deep`、`--yellow/-soft/-deep`、`--green/-soft/-deep`、`--red/-soft/-deep`、`--dark/-2`。

### 半透明色（叠加 / tint / overlay）—— 用 rgb 三元
不要写 `rgba(28,26,23,.06)`，写 `rgba(var(--ink-rgb), .06)`。三元根值：
- `--ink-rgb`（墨色，边框/overlay/滚动条）
- `--green-rgb` / `--red-rgb`（状态 tint）

好处：暗色主题（工作流 ②）只在 `body[data-theme="dark"]` 翻这几个根值，所有半透明色一键全翻，无需逐处改。

### chrome token
`--scroll-thumb` / `--scroll-thumb-hover`（滚动条，借 --ink-rgb 自动随主题）、`--frosted-bg` / `--frosted-border`（磨砂玻璃）。

## 2. 组件变体用 CVA

有"变体"的组件用 `class-variance-authority` 把变体矩阵写成声明式表（范本：`ui/Btn.vue`、`ui/Pill.vue`、`ui/Card.vue`）。模板里 `:class="xxxVariants({ ... })"`。不要用 `:class="[a && '...', b && '...']"` 三元链。

## 3. cn() —— 合并外部 class 时用

`lib/cn.ts` = `twMerge(clsx(...))`。当一个组件需要接受调用方传入的 class 并与自身变体类合并（且要 Tailwind 冲突去重）时用它：`:class="cn(xxxVariants({...}), props.class)"`。目前 Btn/Pill/Card 不接受外部 class（用 cva 直出即可），cn() 留作此类"可被覆盖样式"的组件按需采用。

## 4. token 命名不重命名

不迁移到 shadcn 的 `--background/--foreground` 命名 —— 现有语义名已良好且数百处在用。我们采用 shadcn 的**模式**（cva + rgb/通道三元 + cn 助手），不引入 shadcn-vue / reka-ui 依赖。

## 5. 缺失基础件

Tabs / Switch / Popover / Checkbox 等暂未抽成统一原语，按需手写；将来要补时遵循本规范（cva 变体 + token 颜色）。
