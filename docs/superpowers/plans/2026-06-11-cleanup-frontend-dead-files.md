# Cleanup: 删除前端死文件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 13 个已验证无引用的前端死文件，并停止跟踪 `vue-tsc -b` 生成的构建产物，全程零行为变化。

**Architecture:** 纯删除 + `.gitignore`。这是工作流 ④（spec §7）。每批删除遵循「先验证零引用（删除的依据）→ 删除 → 跑类型检查 + 单测确认仍绿 → 提交」。不动任何运行时逻辑。删除分批按"死簇"组织，每批一个 commit，互相独立可回滚。

**Tech Stack:** Vue 3 + TypeScript + Vitest + vue-tsc + ripgrep(`rg`)。

**对应 spec：** [2026-06-11-frontend-ui-design-system-unification-design.md](../specs/2026-06-11-frontend-ui-design-system-unification-design.md) 工作流 ④。

**前置事实（来自死代码排查）：**
- 项目无全局组件注册（`app.component` 零命中），所以每个组件必须显式 `import` 才会被用到 —— import 图即权威。
- 13 个待删文件已逐一验证零 import；唯一约束：`home/KeywordTrendCard.vue` 仅被另外 4 张死首页卡 import，必须与首页死簇**一并删除**。
- `frontend/vite.config.js` / `frontend/vite.config.d.ts` 是 `vue-tsc -b` 的产物却被 git 跟踪，应改为忽略。

---

## File Structure

**删除（13 个，全部在 `frontend/src/` 下）：**
- 首页死簇（6）：`components/home/BaiduSeoCard.vue`、`components/home/GeoCard.vue`、`components/home/ZhihuCard.vue`、`components/home/ZhihuSearchCard.vue`、`components/home/VideoMiningCard.vue`、`components/home/KeywordTrendCard.vue`
- 被取代组件（4）：`components/article/AssemblyTree.vue`、`components/monitor/geo/GeoKeywordMatrix.vue`、`components/templates/MultiValuePicker.vue`、`utils/saveFile.ts`
- 无引用 ui 原语（3）：`components/ui/Avatar.vue`、`components/ui/Bars.vue`、`components/ui/Blob.vue`

**保留（不在本 PR 删，故意留）：** `lib/cn.ts`、`ui/IconBtn.vue`、`ui/Select.vue`、`ui/Tooltip.vue`（工作流 ③ 会用到或复活）。

**修改：** `.gitignore`（+2 行）；`git rm --cached` 两个 vite.config 产物（保留磁盘文件、停止跟踪）。

> 所有命令的工作目录默认为仓库根 `D:\CSM\.claude\worktrees\focused-varahamihira-60097d`。`rg` = ripgrep（已随仓库工具链可用）。npm 脚本需先 `cd frontend`。

---

## Task 1: 停止跟踪 vite.config 构建产物 + 建立绿色基线

**Files:**
- Modify: `.gitignore`
- Untrack: `frontend/vite.config.js`、`frontend/vite.config.d.ts`

- [ ] **Step 1: 建立删除前的绿色基线**

Run:
```bash
cd frontend
npx vue-tsc -b
npx vitest run
cd ..
```
Expected: vue-tsc 0 errors；vitest 全部通过（已存在的 home/monitor/stores spec 全绿）。
说明：这一步可能重新生成 `frontend/vite.config.js` / `.d.ts`（被跟踪）—— 正常，下面就把它们移出跟踪。

- [ ] **Step 2: 把构建产物加入 `.gitignore`**

在 `.gitignore` 末尾、`frontend/*.tsbuildinfo` 那一组附近，追加：
```gitignore
# vue-tsc -b 会 emit 的 vite.config 兄弟文件（构建产物，不应进 VCS）
frontend/vite.config.js
frontend/vite.config.d.ts
```
（`.superpowers/` 已在 `.gitignore` 内，无需再加。）

- [ ] **Step 3: 停止跟踪这两个文件（保留磁盘副本）**

Run:
```bash
git rm --cached frontend/vite.config.js frontend/vite.config.d.ts
```
Expected: 输出 `rm 'frontend/vite.config.js'` 和 `rm 'frontend/vite.config.d.ts'`；磁盘上文件仍在。

- [ ] **Step 4: 验证已被忽略**

Run:
```bash
git check-ignore frontend/vite.config.js frontend/vite.config.d.ts
```
Expected: 打印这两个路径（说明命中忽略规则）。
Run:
```bash
git status --porcelain
```
Expected: 看到 `.gitignore` 为 modified、两个 vite.config 为 deleted（从 index 移除），无其它意外改动。

- [ ] **Step 5: Commit**

`git rm --cached`（Step 3）已把两文件的"从 index 删除"暂存好了，这里只需再 stage `.gitignore`：
```bash
git add .gitignore
git commit -m "chore(frontend): 停止跟踪 vue-tsc 产物 vite.config.js/.d.ts"
```
（不要再 `git add frontend/vite.config.*` —— 它们现已被忽略，`git add` 会拒绝或需 `-f`，且删除早已暂存。）

---

## Task 2: 删除首页死簇（6 个）

被 2026-06-05 首页改版取代。`HomeView.vue` 现在只 import 6 张**不同**的卡（CreateArticleHero / StatCardLoader / SourceLeaderboardCard / CommentRetentionCard / GaugeCard / RecentDocsCard），下列 6 个无任何 live 引用。`KeywordTrendCard` 仅被同簇 4 张死卡引用，必须一并删。

**Files:**
- Delete: `frontend/src/components/home/BaiduSeoCard.vue`
- Delete: `frontend/src/components/home/GeoCard.vue`
- Delete: `frontend/src/components/home/ZhihuCard.vue`
- Delete: `frontend/src/components/home/ZhihuSearchCard.vue`
- Delete: `frontend/src/components/home/VideoMiningCard.vue`
- Delete: `frontend/src/components/home/KeywordTrendCard.vue`

- [ ] **Step 1: 验证零 live 引用（删除依据）**

Run:
```bash
rg -n "BaiduSeoCard|GeoCard|ZhihuCard|ZhihuSearchCard|VideoMiningCard|KeywordTrendCard" frontend/src
```
Expected: 命中**仅出现在这 6 个文件自身内部**（含 4 张死卡 import `KeywordTrendCard`、各文件自己的注释）。**不得**出现在 `frontend/src/views/HomeView.vue` 或任何其它文件。

再单独确认 HomeView 的导入清单不含上述任何一个：
```bash
rg -n "import .* from .*home/" frontend/src/views/HomeView.vue
```
Expected: 只列出 CreateArticleHero / StatCardLoader / SourceLeaderboardCard / CommentRetentionCard / GaugeCard / RecentDocsCard —— 没有这 6 个死卡。

- [ ] **Step 2: 删除 6 个文件**

```bash
git rm frontend/src/components/home/BaiduSeoCard.vue \
       frontend/src/components/home/GeoCard.vue \
       frontend/src/components/home/ZhihuCard.vue \
       frontend/src/components/home/ZhihuSearchCard.vue \
       frontend/src/components/home/VideoMiningCard.vue \
       frontend/src/components/home/KeywordTrendCard.vue
```
Expected: 6 行 `rm '...'`。

- [ ] **Step 3: 类型检查 + 单测确认仍绿**

```bash
cd frontend && npx vue-tsc -b && npx vitest run; cd ..
```
Expected: vue-tsc 0 errors（无"找不到模块"残留引用）；vitest 全过（首页 live 卡的 spec 不受影响）。

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(frontend): 删除首页改版遗留的 6 张死卡"
```

---

## Task 3: 删除被取代的组件（4 个）

**Files:**
- Delete: `frontend/src/components/article/AssemblyTree.vue`（ArticleView 注释自述"旧简化版已下线、本视图不再引用"；模板内 `<AssemblyTree>` 是文件自身递归）
- Delete: `frontend/src/components/monitor/geo/GeoKeywordMatrix.vue`（旧 GEO 数据中心分析视图，已被取代）
- Delete: `frontend/src/components/templates/MultiValuePicker.vue`（BlockEditor 注释自述"已下线，改用 FormSelect"）
- Delete: `frontend/src/utils/saveFile.ts`（导出 `saveUrlToFile`，无人 import）

- [ ] **Step 1: 验证零 import（删除依据）**

Run（专门查 import 语句，避开注释/自递归造成的误报）：
```bash
rg -n "import .*AssemblyTree|import .*GeoKeywordMatrix|import .*MultiValuePicker|from .*utils/saveFile|saveUrlToFile" frontend/src
```
Expected: **零命中**（`saveUrlToFile` 仅在 `saveFile.ts` 自身定义处出现，可在结果里确认它只来自该文件）。
补充宽搜，确认其余命中都是注释/自递归：
```bash
rg -n "AssemblyTree|GeoKeywordMatrix|MultiValuePicker" frontend/src
```
Expected: 仅这 3 个文件自身 + ArticleView/BlockEditor 里的"已下线"注释；无任何 live import 或 `<标签>` 使用（AssemblyTree 的 `<AssemblyTree>` 仅在其自身文件内递归）。

- [ ] **Step 2: 删除 4 个文件**

```bash
git rm frontend/src/components/article/AssemblyTree.vue \
       frontend/src/components/monitor/geo/GeoKeywordMatrix.vue \
       frontend/src/components/templates/MultiValuePicker.vue \
       frontend/src/utils/saveFile.ts
```
Expected: 4 行 `rm '...'`。

- [ ] **Step 3: 类型检查 + 单测确认仍绿**

```bash
cd frontend && npx vue-tsc -b && npx vitest run; cd ..
```
Expected: vue-tsc 0 errors；vitest 全过。

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(frontend): 删除被取代的 AssemblyTree/GeoKeywordMatrix/MultiValuePicker/saveFile"
```

---

## Task 4: 删除无引用的 ui 原语（3 个）

**Files:**
- Delete: `frontend/src/components/ui/Avatar.vue`
- Delete: `frontend/src/components/ui/Bars.vue`
- Delete: `frontend/src/components/ui/Blob.vue`

> 注意：`Avatar` / `Bars` / `Blob` 都是常见词（`Blob` 还是 JS 内建），所以用**导入路径** `ui/Xxx` 来验证，避免误报。

- [ ] **Step 1: 验证零 import（删除依据）**

Run:
```bash
rg -n "ui/Avatar|ui/Bars|ui/Blob" frontend/src
```
Expected: **零命中**（无任何文件从 `components/ui/Avatar|Bars|Blob` 导入）。
补充确认没有以组件标签形式使用：
```bash
rg -n "<Avatar|<Bars|<Blob" frontend/src
```
Expected: 仅可能命中这 3 个文件自身的模板根（自引用）；无外部使用。

- [ ] **Step 2: 删除 3 个文件**

```bash
git rm frontend/src/components/ui/Avatar.vue \
       frontend/src/components/ui/Bars.vue \
       frontend/src/components/ui/Blob.vue
```
Expected: 3 行 `rm '...'`。

- [ ] **Step 3: 类型检查 + 单测确认仍绿**

```bash
cd frontend && npx vue-tsc -b && npx vitest run; cd ..
```
Expected: vue-tsc 0 errors；vitest 全过。

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(frontend): 删除无引用 ui 原语 Avatar/Bars/Blob"
```

---

## Task 5: 收尾全量验证

- [ ] **Step 1: 确认 13 个文件都已不在工作树**

```bash
rg --files frontend/src | rg "BaiduSeoCard|GeoCard|ZhihuCard|ZhihuSearchCard|VideoMiningCard|KeywordTrendCard|AssemblyTree|GeoKeywordMatrix|MultiValuePicker|utils/saveFile|ui/Avatar|ui/Bars|ui/Blob"
```
Expected: **零命中**（13 个文件均已删除）。

- [ ] **Step 2: 确认保留文件仍在**

```bash
rg --files frontend/src | rg "lib/cn.ts|ui/IconBtn|ui/Select|ui/Tooltip"
```
Expected: 4 个文件都在（故意保留，留给工作流 ③）。

- [ ] **Step 3: 全量类型检查 + 单测 + 生产构建**

```bash
cd frontend
npx vue-tsc -b
npx vitest run
npm run build
cd ..
```
Expected: vue-tsc 0 errors；vitest 全过；`npm run build` 成功产出 `dist/`（确认无死引用导致打包失败）。
说明：`vue-tsc -b` 可能再生成被忽略的 `vite.config.js/.d.ts` —— 已在 Task 1 忽略，`git status` 不应再显示它们。

- [ ] **Step 4: 确认工作树干净**

```bash
git status --porcelain
```
Expected: 空（所有改动已在前述 commit 中；无意外残留、无 vite.config 噪音）。

---

## 收尾：开 PR

本 PR 全部为删除 + 忽略规则，零运行时改动。按项目惯例走 PR 流程：

```bash
git push -u origin claude/focused-varahamihira-60097d
gh pr create --fill --base main
```
返回 PR URL，停在 pending 等网页 merge（勿本地 merge main）。
