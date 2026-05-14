# 平台评论 L1 批量「立刻监测」按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `MonitorView.vue` 平台评论 tab 的 L1 行（任务汇总行）加一个批量「立刻监测」按钮，一键派发该批次下所有子任务，复用现有 SSE bus 做实时反馈，避免用户为 N 个视频点 N 次。

**Architecture:** 纯前端改动，无新接口。点击 → `Promise.allSettled` 并行 POST 现有 `/api/monitor/tasks/{id}/run-now`；后端 ThreadPoolExecutor + 每平台 Semaphore（默认 2 并发）+ pacer 自动节流。按钮文案根据现有 `runningTaskIds` 字典推断「进度 N/M」，SSE `finished` 事件已经会自动刷该子任务的 snapshot，L1 行留存数字会跟着动。

**Tech Stack:** Vue 3 SFC（Composition API），Axios（`sidecar.client`），SSE bus（`startMonitorBus`）。无新依赖，无测试栈引入（仓库前端目前就没有 vitest/jest，跟现状一致；验证靠 dev 模式手动）。

**Spec:** [docs/superpowers/specs/2026-05-14-monitor-l1-batch-run-now-design.md](../specs/2026-05-14-monitor-l1-batch-run-now-design.md)

---

## File Structure

只动一个文件：

- **Modify** [frontend/src/views/MonitorView.vue](../../../frontend/src/views/MonitorView.vue)
  - Script section：新增 `runBatch(batchName: string)` 函数 + `batchRunState(batchName)` 辅助函数（在已有的 `runNow` / `markRunning` / `clearRunning` 附近）
  - Template section：在 L1 行 status 列、Pill 与编辑/删除按钮组之间，插入新的批量「立刻监测」按钮 block

---

## Task 1: 实现 runBatch + batchRunState 并接入 L1 模板

**Files:**
- Modify: [frontend/src/views/MonitorView.vue](../../../frontend/src/views/MonitorView.vue)
  - Script: 在 `runNow` 函数后（line ~911）追加两个函数
  - Template: L1 行 status 列（line ~2685-2714）的 `<div class="flex items-center gap-2">` 内插入新按钮

- [ ] **Step 1：在 `runNow` 函数后追加 `runBatch` 与 `batchRunState`**

在 MonitorView.vue 的 `runNow` 函数（line ~911 处 `}`）之后，新增如下两个函数：

```ts
// L1 批次批量派发：取该批次下所有子 task，并行 POST run-now。
// 后端有 per-platform Semaphore（默认 2 并发）+ pacer，前端一次性
// fire N 个不会冲风控；SSE finished 事件已经会对每个子任务调
// _fetchSnapshotPair，L1 行的留存/变化跟着自动刷。
async function runBatch(batchName: string) {
  const child = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  if (!child.length) return;
  // 乐观先标 —— 按钮立刻切到 disabled "监测中…"，避免连点。
  child.forEach((t) => markRunning(t.id));
  const results = await Promise.allSettled(
    child.map((t) => sidecar.client.post(`/api/monitor/tasks/${t.id}/run-now`)),
  );
  const fails = results.filter((r) => r.status === "rejected");
  if (fails.length === 0) {
    toast.info(`已派发 ${child.length} 个任务`);
  } else if (fails.length === child.length) {
    // 全部失败 —— 这些任务永远不会有 SSE 事件进来清 spinner，手动清。
    child.forEach((t) => clearRunning(t.id));
    toast.error(`派发失败：${fails.length}/${child.length}`);
  } else {
    // 部分失败：只清掉失败那部分；成功的依然依赖 SSE 自然完成。
    results.forEach((r, i) => {
      if (r.status === "rejected") clearRunning(child[i].id);
    });
    toast.warn(`派发 ${child.length - fails.length}/${child.length}，${fails.length} 失败`);
  }
}

// 批次按钮文案 / 禁用态。点击瞬间 markRunning 把所有子 task 全部
// 标为 running → 显示"监测中…"；SSE finished 逐个清除 → 数字递增
// 显示"监测中 1/5"、"监测中 2/5"…；归零后回到"立刻监测"。
function batchRunState(batchName: string): { label: string; disabled: boolean } {
  const child = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  const total = child.length;
  const runningCount = child.filter((t) => runningTaskIds.value[t.id]).length;
  if (runningCount === 0) return { label: "立刻监测", disabled: false };
  if (runningCount === total) return { label: "监测中…", disabled: true };
  return { label: `监测中 ${total - runningCount}/${total}`, disabled: true };
}
```

- [ ] **Step 2：在 L1 行 status 列插入按钮**

找到 L1 行 status 列代码块（line ~2685 起，`<div class="flex items-center gap-2">`），结构当前是：

```html
<div class="flex items-center gap-2">
  <Pill v-if="t.status === 'ok'" tone="ok">正常</Pill>
  <Pill v-else-if="t.status === 'warn'" tone="warn">关注</Pill>
  <Pill v-else tone="alert">评论丢失</Pill>
  <div v-if="!demoMode" class="ml-auto flex flex-shrink-0 items-center gap-0.5">
    <!-- 编辑按钮 + 删除按钮 -->
  </div>
</div>
```

在 Pill 三选一 block 之后、`<div v-if="!demoMode" class="ml-auto ...">` 之前，新增按钮 block。把 `ml-auto` 从内层 div 移到这个新按钮上，让按钮先靠右，编辑/删除紧贴其后（保持原有「按钮组合靠右」的视觉）：

```html
<button
  v-if="!demoMode"
  type="button"
  class="ml-auto whitespace-nowrap text-[11px]"
  :style="{
    padding: '4px 10px',
    borderRadius: '999px',
    color: batchRunState(t.id).disabled ? 'var(--ink-3)' : 'var(--primary-deep)',
    cursor: batchRunState(t.id).disabled ? 'not-allowed' : 'pointer',
  }"
  :disabled="batchRunState(t.id).disabled"
  :title="`批量派发该批次下所有视频任务（共 ${tasks.filter((x) => parseBatchName(x.name) === t.id).length} 条）`"
  @click.stop="runBatch(t.id)"
>{{ batchRunState(t.id).label }}</button>
<div v-if="!demoMode" class="flex flex-shrink-0 items-center gap-0.5">
  <!-- 编辑 / 删除按钮原样保留，但内层 div 上的 ml-auto 删掉，因为
       上面那个新按钮已经吃了 ml-auto，编辑/删除靠在它右边即可。 -->
```

注意三点：

1. 新按钮挂 `ml-auto`，从内层 edit/delete 容器上**移除** `ml-auto`（在 line ~2689 的 `<div v-if="!demoMode" class="ml-auto flex flex-shrink-0 items-center gap-0.5">` 处把 `ml-auto` 去掉）
2. button 上的 `title` 用反引号模板字符串，把 batch 的子任务总数显示在 hover tooltip 里
3. `@click.stop` 必填——L1 行本身有 click handler 进 L2，没 stop 会触发跳页

- [ ] **Step 3：手动验证 dev**

由于前端没有 vitest，验证靠 dev 模式。Vite HMR 会热更，不用重启：

1. 当前 Tauri dev 已经在跑（任务 ID `bdfipus63`，端口 2439），保持开着即可
2. 浏览器刷新或等 HMR 自动应用
3. 切到「平台评论」tab → 任一平台（B 站 / 抖音 / 快手）
4. 找一个有 2+ 子任务的批次（截图里的 0514 批次有 5 个）
5. 鼠标 hover L1 行 → 状态列从左到右应该看到：
   `<状态 pill>` → `「立刻监测」(新按钮，靠右)` → `<编辑> <删除>`
   tooltip 显示「批量派发该批次下所有视频任务（共 5 条）」
6. 点「立刻监测」→ toast 提示「已派发 5 个任务」，按钮文案立刻变「监测中…」并禁用
7. 等 SSE 事件回来 → 文案逐步变「监测中 1/5」「监测中 2/5」… 直至全部完成 → 按钮回到「立刻监测」
8. L1 行的「留存 X/N」列会跟着每个子任务 finish 同步更新
9. 不要破坏既有：
   - L2 单视频「立刻监测」按钮仍正常
   - L1 编辑批次（铅笔）仍能打开 modal
   - L1 删除批次（垃圾桶）仍能批删
   - 切平台 / 切顶级 tab 不闪动

- [ ] **Step 4：Commit**

```bash
git add frontend/src/views/MonitorView.vue \
        docs/superpowers/specs/2026-05-14-monitor-l1-batch-run-now-design.md \
        docs/superpowers/plans/2026-05-14-monitor-l1-batch-run-now.md
git commit -m "$(cat <<'EOF'
feat(monitor): L1 批次行加批量「立刻监测」按钮

之前批量重跑一个批次下的 N 个视频任务，得点进 L2 视频列表逐个
点「立刻监测」，N=5 就要 5 次点击 + N 次切换。L1 行新增批量按钮，
一键 Promise.allSettled 并行派发该批次下所有子任务；后端 per-
platform Semaphore + pacer 自动节流，前端复用现有 SSE bus 把
按钮文案做成「监测中 X/N」progress 形态，跑完自动归位。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Result

- **Spec coverage**：spec 的「按钮放置 / 文案状态机 / 派发流程 / 并发安全 / SSE 自动 reload」5 个章节全部由 Task 1 的 Step 1-2 落地；spec 的「不动的 / YAGNI」章节自然由「只动一个文件、不引入新接口」满足
- **Placeholder scan**：无 TBD / TODO / 「类似 Task N」/「适当处理错误」类糊话；所有代码块给的是可直接粘贴的完整片段
- **Type consistency**：`runBatch` / `batchRunState` 在 Step 1 定义，Step 2 模板直接调用；用到的现有符号（`tasks`、`parseBatchName`、`markRunning`、`clearRunning`、`runningTaskIds`、`sidecar.client`、`toast`、`demoMode`）全是 MonitorView.vue 已有的，可见 [MonitorView.vue:870-911](../../../frontend/src/views/MonitorView.vue:870)
- **测试缺位声明**：仓库前端没有 vitest/jest（已 grep 确认），spec 里曾草写「单元测：mock sidecar.client.post」是过度承诺；本计划改为「Step 3 手动 dev 验证清单」，与仓库前端验证现状一致
