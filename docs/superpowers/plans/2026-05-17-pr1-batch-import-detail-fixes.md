# PR 1：百度批量导入 UX 修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 2 个挂在百度批量导入流程上的前端 bug——弹窗不关闭、列表不刷新、任务详情只显 1 关键词。

**Architecture:** 三处独立的前端修补，不动后端不动数据库。模块 1（弹窗+列表）改 `BatchImportTaskModal.vue` 的 `submitAll()` + `MonitorView.vue` 的 tab→type 映射；模块 2（详情）把 `BaiduRankingPage.vue` 的双分支渲染合并成一个 `keywordRows` 计算属性。

**Tech Stack:** Vue 3.5 (Composition API + `<script setup>`) / TypeScript / Vite + vue-tsc 做构建期类型检查。前端**没有测试框架**（无 vitest / playwright / jest），因此每个 task 用 `pnpm --filter csm-frontend build` 做类型检查 + 手动 dev server 验证。

**Spec：** [docs/superpowers/specs/2026-05-17-mining-monitor-fixes-design.md](../specs/2026-05-17-mining-monitor-fixes-design.md) §2-§3

---

## File Map

| 文件 | 责任 | 改动量 |
|------|------|--------|
| `frontend/src/components/monitor/BatchImportTaskModal.vue` | 批量导入弹窗，提交后必须真关闭 | ~3 行 |
| `frontend/src/views/MonitorView.vue` | 顶层视图，模板里抽 `currentTaskType` computed 让 modal 和 reload handler 共用 | ~15 行 |
| `frontend/src/components/monitor/history/BaiduRankingPage.vue` | 百度任务详情，关键词表合并渲染源 | ~50 行（含模板替换） |

---

## Task 1：修 `BatchImportTaskModal.vue` 弹窗 close() 早退

**Files:**
- Modify: `frontend/src/components/monitor/BatchImportTaskModal.vue:529-540`

**根因复述：** `close()` 函数（line 320）开头 `if (submitting.value) return;` 早退。`submitAll()` 在 `try` 块里调 `close()`（line 534）时 `submitting.value` 仍为 `true`，要到 `finally` 块（line 539）才置 `false`，所以 `close()` 等于没调。

修复策略：在 `try` 块调 `close()` **之前**显式 `submitting.value = false;`。`finally` 里的同名赋值**保留**——异常路径（POST 失败）仍要靠它复位。

---

- [ ] **Step 1: Read 当前上下文，确认行号 529-540 的内容跟 spec 一致**

```bash
sed -n '529,540p' frontend/src/components/monitor/BatchImportTaskModal.vue
```

Expected output（确认上下文匹配）：
```
      await sidecar.client.post("/api/monitor/tasks", body);
      progress.value.done = 1;
      toast.success(`已批量导入 ${keywords.length} 个关键词到任务「${taskName}」`);
      emit("imported", 1);
      close();
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? e?.message ?? e;
      toast.error(`批量导入失败：${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    } finally {
      submitting.value = false;
    }
    return;
```

如果不匹配，停下来检查仓库版本。

---

- [ ] **Step 2: 用 Edit 工具改 `submitAll()` 百度路径**

把 `try` 块尾段：
```ts
      await sidecar.client.post("/api/monitor/tasks", body);
      progress.value.done = 1;
      toast.success(`已批量导入 ${keywords.length} 个关键词到任务「${taskName}」`);
      emit("imported", 1);
      close();
```

改成：
```ts
      await sidecar.client.post("/api/monitor/tasks", body);
      progress.value.done = 1;
      toast.success(`已批量导入 ${keywords.length} 个关键词到任务「${taskName}」`);
      emit("imported", 1);
      // submitting=false 必须在 close() 之前——close() 开头有 if (submitting.value) return 早退守卫。
      // finally 里的同名赋值保留：异常路径（POST 失败）仍要靠它复位。
      submitting.value = false;
      close();
```

---

- [ ] **Step 3: 同样修非百度（其它平台）路径——它有相同的 bug 隐患**

非百度路径在 [line 573-577](frontend/src/components/monitor/BatchImportTaskModal.vue:573)。当前代码：
```ts
  submitting.value = false;
  if (failures.length === 0) {
    toast.success(`已批量创建 ${okCount} 个任务`);
    emit("imported", okCount);
    close();
  } else {
```

这一路径已经在 `close()` 之前把 `submitting.value = false`（line 573），**所以非百度路径不需要改**。Step 3 是确认——跑下面命令验证：

```bash
sed -n '573,578p' frontend/src/components/monitor/BatchImportTaskModal.vue
```
Expected：`submitting.value = false;` 出现在 `close()` 之前的几行内。如果不是这样，按相同模式调整。

---

- [ ] **Step 4: 类型检查通过**

```bash
cd frontend && pnpm vue-tsc -b
```

Expected: 无错误退出码 0。

---

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/monitor/BatchImportTaskModal.vue
git commit -m "$(cat <<'EOF'
fix(monitor): 批量导入弹窗百度路径调 close() 前先置 submitting=false

close() 开头守卫 if (submitting.value) return 在 submitAll() try 块里
立即调用时还是 true（finally 才置 false），等于空跑。在调 close()
前显式 submitting.value = false；finally 保留给异常路径复位。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2：`MonitorView.vue` 抽 `currentTaskType` computed，覆盖 baidu 分支

**Files:**
- Modify: `frontend/src/views/MonitorView.vue:73-81`（在 `PLATFORM_TYPE` 后插入 computed）
- Modify: `frontend/src/views/MonitorView.vue:3261-3275`（替换 `<BatchImportTaskModal>` 上的两处 tab→type 表达式）

**根因复述：** [MonitorView.vue:3274](frontend/src/views/MonitorView.vue:3274) `@imported` handler 表达式只覆盖 `zhihu` 和评论三平台，没 `baidu` 分支：
```vue
@imported="loadTasks(activeTab === 'zhihu' ? 'zhihu_question' : PLATFORM_TYPE[commentSubtab])"
```
导致 baidu tab 批量导入后刷的是评论 tab 的任务列表，baidu 列表不动。`:default-type` 表达式（line 3263-3272）已经正确覆盖了 baidu——但它和 `@imported` 重复了一份相似但不一致的逻辑，是 bug 来源。

修复策略：抽一个 `currentTaskType` computed，让 `:default-type` 和 `@imported` 共用同一份映射。

---

- [ ] **Step 1: Read 现有的 `PLATFORM_TYPE` + tab 状态定义（line 57-81）**

```bash
sed -n '57,81p' frontend/src/views/MonitorView.vue
```

Expected output（确认上下文）：
```ts
type Tab = "zhihu" | "comment" | "baidu" | "report";
type CommentPlatform = "bilibili" | "douyin" | "kuaishou";
... (省略)
const PLATFORM_TYPE: Record<CommentPlatform, string> = {
  bilibili: "bilibili_comment",
  douyin: "douyin_comment",
  kuaishou: "kuaishou_comment",
};
const commentSubtab = ref<CommentPlatform>("bilibili");

type HistorySubtab = "retention" | "zhihu" | "baidu";
const historySubtab = ref<HistorySubtab>("retention");
```

---

- [ ] **Step 2: 在 `historySubtab` 声明后追加 `currentTaskType` computed**

在 `const historySubtab = ref<HistorySubtab>("retention");` 这一行之后插入：

```ts
// 当前 tab 对应的任务 type——modal 的 :default-type 和 @imported reload 共用，
// 避免两处分别 inline 维护出现错位（baidu 分支原本只在 :default-type 里有，
// @imported 漏了，导致百度批量导入后刷错 tab 的列表）。
const currentTaskType = computed<string>(() => {
  if (activeTab.value === "zhihu") return "zhihu_question";
  if (activeTab.value === "baidu") return "baidu_keyword";
  if (activeTab.value === "report" && historySubtab.value === "baidu") return "baidu_keyword";
  return PLATFORM_TYPE[commentSubtab.value];
});
```

**注意：** `computed` 已经在 line 24 的 import 列表里，不用再加 import。

---

- [ ] **Step 3: 替换 `<BatchImportTaskModal>` 的两处 tab→type 表达式**

定位 line 3261-3275，当前代码：
```vue
    <BatchImportTaskModal
      v-model:open="showBatchImport"
      :default-type="
        activeTab === 'zhihu'
          ? 'zhihu_question'
          : activeTab === 'baidu' || (activeTab === 'report' && historySubtab === 'baidu')
            ? 'baidu_keyword'
            : commentSubtab === 'bilibili'
              ? 'bilibili_comment'
              : commentSubtab === 'douyin'
                ? 'douyin_comment'
                : 'kuaishou_comment'
      "
      @imported="loadTasks(activeTab === 'zhihu' ? 'zhihu_question' : PLATFORM_TYPE[commentSubtab])"
    />
```

替换成：
```vue
    <BatchImportTaskModal
      v-model:open="showBatchImport"
      :default-type="currentTaskType"
      @imported="loadTasks(currentTaskType)"
    />
```

---

- [ ] **Step 4: 类型检查通过**

```bash
cd frontend && pnpm vue-tsc -b
```

Expected: 无错误退出码 0。如果 vue-tsc 报 `currentTaskType` 跟 `BatchImportTaskModal` props 的类型不匹配，把 computed 的 `<string>` 改为该 props 实际定义的 union type（参考 `BatchImportTaskModal.vue` 顶部 `defineProps`）。

---

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/MonitorView.vue
git commit -m "$(cat <<'EOF'
fix(monitor): 批量导入后按当前 tab 刷新列表，含 baidu 分支

@imported handler 原本只覆盖 zhihu 和评论三平台，baidu tab 批量导入
后 loadTasks 拿到的是评论平台 type，刷错 tab。抽 currentTaskType
computed 让 :default-type 和 @imported 共用同一份映射，根除错位。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3：`BaiduRankingPage.vue` 合并关键词渲染源为 `keywordRows`

**Files:**
- Modify: `frontend/src/components/monitor/history/BaiduRankingPage.vue:426-432`（在 `latestMetric` computed 之后追加 `keywordRows` computed）
- Modify: `frontend/src/components/monitor/history/BaiduRankingPage.vue:1383-1511`（模板双分支替换为单一 v-for）

**根因复述：** [BaiduRankingPage.vue:1384-1453](frontend/src/components/monitor/history/BaiduRankingPage.vue:1384) 详情页关键词表两个分支——`!latestMetric` 渲染 `config.search_keywords`（93 行），`latestMetric` 存在则渲染 `latestMetric.keywords`。检测进行到中途时 `latestMetric` 已被赋值但只含已检关键词（如 1 个），分支切到第二条，前端就只看到 1 行。等检测全跑完才看到 93 行。

修复策略（spec §3 方案 A）：删除双分支，改成单一 v-for 源 `keywordRows`——以 `config.search_keywords` 为基准的 93 行不变，按 keyword 名字从 `latestMetric.keywords` map 里查结果填充每行；查不到则 "未跑" Pill。

---

- [ ] **Step 1: Read `latestMetric` computed 的位置（line 422-432）**

```bash
sed -n '422,432p' frontend/src/components/monitor/history/BaiduRankingPage.vue
```

Expected output：
```ts
const latestResult = computed(() =>
  history.value.length > 0 ? history.value[0] : null,
);

const latestMetric = computed<BaiduMetric | null>(
  () => latestResult.value?.metric ?? null,
);

const prevMetric = computed<BaiduMetric | null>(
  () => (history.value.length > 1 ? history.value[1]?.metric ?? null : null),
);
```

---

- [ ] **Step 2: 找到 `BaiduMetric.keywords` 元素的类型名**

```bash
grep -n "BaiduMetric\|BaiduKeywordMetric" frontend/src/components/monitor/history/BaiduRankingPage.vue | head -20
```

记下元素类型名（很可能是 `BaiduKeywordMetric` 或类似——下面 Step 3 的 `KeywordRow` 类型需要用它）。如果类型不是从该文件 import 进来的，到 `frontend/src/api/types.ts` 或 `frontend/src/stores/` 下确认。

---

- [ ] **Step 3: 在 `prevMetric` computed 后追加 `keywordRows` computed**

在 `const prevMetric = computed<BaiduMetric | null>(...)` 那一段之后插入：

```ts
// 关键词渲染源——以 config.search_keywords 为基准（93 行始终不变），
// 用 latestMetric.keywords 按 keyword 名 dict 查找填充每行结果。
// 这样检测中途（latestMetric 已存在但只含部分 keyword）也能正常显示
// "未跑/已检"占位，而不是只渲染已检完的几个。
// 修复 bug: 详情页只显示 1 条关键词，等检测完才显示 93 条。
const keywordRows = computed(() => {
  const base = (selectedTask.value?.config as any)?.search_keywords as string[] | undefined;
  if (!base || base.length === 0) return [];
  const map = new Map(
    (latestMetric.value?.keywords ?? []).map((k) => [k.keyword, k]),
  );
  return base.map((name) => ({
    keyword: name,
    result: map.get(name) ?? null,
  }));
});
```

**注意：** `selectedTask.value?.config` 的类型是 `any`（来自 Task 接口）；用 `(... as any)?.search_keywords` 兜底，跟 line 467 `(selectedTask.value?.config as any)?.ideal_rank` 同款写法。

---

- [ ] **Step 4: 替换模板的关键词表区段（line 1383-1511）**

定位 line 1383-1511 的两个 `<template>` 分支（`v-if="!latestMetric"` 和 `<template v-else>`），整段替换为单一 v-for 源。

**保留的部分**：Header row（"关键词 / 默认卡位 / 资讯卡位 / 状态" 列头）只保留一份。

替换前结构（line 1383-1511）：
```vue
<!-- No history: 显示配置里的关键词列表，每条状态「未跑」 -->
<template v-if="!latestMetric">
  <!-- Header row -->
  <div ... 4 列头></div>
  <!-- 用 config.search_keywords 占位 -->
  <div v-for="(kw, i) in (selectedTask?.config?.search_keywords ?? [])" ...>
    <div>{{ kw }}</div>
    <div>—</div>
    <div>—</div>
    <div><Pill tone="info">未跑</Pill></div>
  </div>
  <div v-if="(selectedTask?.config?.search_keywords?.length ?? 0) === 0" ...>
    此任务未配置搜索关键词
  </div>
</template>

<template v-else>
  <!-- Header row（重复一份） -->
  <div ... 4 列头></div>
  <!-- Keyword rows -->
  <div v-for="(kw, i) in latestMetric.keywords" ...>
    <div>{{ kw.keyword }}</div>
    <div>{{ kw.default_matched_count }}</div>
    <div>{{ kw.news_present ? kw.news_results.filter(...).length : '无' }}</div>
    <div>
      <Pill v-if="kw.fetch_error" tone="alert">抓取失败</Pill>
      <Pill v-else :tone="...达到 idealRank">理想/未理想</Pill>
    </div>
  </div>
</template>
```

替换后结构（合并成一个分支）：
```vue
<!-- 关键词表：单一渲染源 keywordRows，以 config.search_keywords 为基准的 93 行，
     按 keyword 名从 latestMetric.keywords 查结果填充；未匹配的渲染「未跑」。 -->
<template>
  <!-- Header row -->
  <div
    class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
    :style="{
      gridTemplateColumns: '1.6fr .5fr .5fr .5fr',
      letterSpacing: '1.2px',
      color: 'var(--ink-3)',
      borderBottom: '1px solid var(--line)',
    }"
  >
    <div>关键词</div>
    <div>默认卡位</div>
    <div>资讯卡位</div>
    <div>状态</div>
  </div>

  <!-- Empty state -->
  <div
    v-if="keywordRows.length === 0"
    class="py-10 text-center text-[12px]"
    :style="{ color: 'var(--ink-3)' }"
  >
    此任务未配置搜索关键词
  </div>

  <!-- Keyword rows -->
  <div
    v-for="(row, i) in keywordRows"
    :key="row.keyword + '-' + i"
    class="grid items-center cursor-pointer transition"
    :style="{
      gridTemplateColumns: '1.6fr .5fr .5fr .5fr',
      borderBottom: i < keywordRows.length - 1 ? '1px solid var(--line)' : 'none',
      padding: '12px 8px',
      background: selectedKeywordIdx === i ? 'var(--card-2)' : 'transparent',
    }"
    @click="selectedKeywordIdx = i"
    @mouseenter="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
    @mouseleave="(e) => { if (selectedKeywordIdx !== i) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
  >
    <!-- 关键词 -->
    <div class="min-w-0">
      <div
        class="truncate text-[12.5px] font-medium"
        :style="{ color: 'var(--ink)' }"
      >{{ row.keyword }}</div>
    </div>

    <!-- 默认卡位 -->
    <div>
      <template v-if="row.result">
        <div
          class="font-display text-[13px] font-bold"
          :style="{ color: row.result.default_matched_count > 0 ? 'var(--primary-deep)' : 'var(--ink-3)' }"
        >
          {{ row.result.default_matched_count }}
        </div>
      </template>
      <div v-else :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>
    </div>

    <!-- 资讯卡位 -->
    <div>
      <template v-if="row.result && row.result.news_present">
        <div
          class="font-display text-[13px] font-bold"
          :style="{ color: row.result.news_results.filter(r => r.matches_brand).length > 0 ? '#4f7cff' : 'var(--ink-3)' }"
        >
          {{ row.result.news_results.filter(r => r.matches_brand).length }}
        </div>
      </template>
      <div v-else-if="row.result && !row.result.news_present" class="font-display text-[13px] font-bold" :style="{ color: 'var(--ink-3)' }">无</div>
      <div v-else :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</div>
    </div>

    <!-- 状态 -->
    <div>
      <template v-if="!row.result">
        <Pill tone="info">未跑</Pill>
      </template>
      <template v-else-if="row.result.fetch_error">
        <Pill tone="alert">抓取失败</Pill>
      </template>
      <template v-else>
        <Pill
          :tone="(row.result.default_matched_count + (row.result.news_present ? row.result.news_results.filter(r => r.matches_brand).length : 0)) >= idealRank ? 'ok' : 'warn'"
        >{{ (row.result.default_matched_count + (row.result.news_present ? row.result.news_results.filter(r => r.matches_brand).length : 0)) >= idealRank ? '理想' : '未理想' }}</Pill>
      </template>
    </div>
  </div>
</template>
```

**注意点**：
1. `currentKeyword` computed（line 502）依赖 `selectedKeywordIdx` 取 `latestMetric.keywords[idx]`——它的语义需要相应调整，否则点击"未跑"的关键词会取错。继续看 Step 5。
2. `selectedKeywordIdx` 是相对 keywordRows 的索引，不再是 `latestMetric.keywords` 的索引。

---

- [ ] **Step 5: 调整 `currentKeyword` computed 的索引来源**

定位 line 502-503：
```ts
const currentKeyword = computed(() => {
  if (!latestMetric.value || selectedKeywordIdx.value === null) return null;
  return latestMetric.value.keywords[selectedKeywordIdx.value] ?? null;
});
```

改成（按 keywordRows 索引取，未跑行返回 null 而不是越界）：
```ts
// selectedKeywordIdx 现在指向 keywordRows（合并源）的索引——未跑的关键词
// row.result 是 null，KPI 卡也跟着显示 0/选择关键词，跟原"未选中"语义一致。
const currentKeyword = computed(() => {
  if (selectedKeywordIdx.value === null) return null;
  const row = keywordRows.value[selectedKeywordIdx.value];
  return row?.result ?? null;
});
```

---

- [ ] **Step 6: 删除模板里残留的 `<template v-if="!latestMetric">` 和 `<template v-else>` 标签**

确认替换后 Step 4 的结构里，关键词表外面不再有 `v-if="!latestMetric"` / `v-else` 这两个壳子。如果替换时还留着 `loadingHistory` loading 状态，那部分保留（它是另一个 `v-if`，跟我们的合并无关）。

```bash
sed -n '1378,1390p' frontend/src/components/monitor/history/BaiduRankingPage.vue
```
Expected output：开头有一个 `v-if="loadingHistory"` 的 spinner 块，然后直接是新的 `<!-- Header row -->`，**不**再出现 `v-if="!latestMetric"` 这类分支判断。

---

- [ ] **Step 7: 类型检查通过**

```bash
cd frontend && pnpm vue-tsc -b
```

Expected: 无错误退出码 0。如果 `row.result.news_results` 之类报"可能为 undefined"，加 `?.` 链；如果 `keywordRows` 的元素类型推断不对，给 computed 加显式返回类型 `Array<{ keyword: string; result: BaiduKeywordMetric | null }>`。

---

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components/monitor/history/BaiduRankingPage.vue
git commit -m "$(cat <<'EOF'
fix(monitor): 任务详情关键词表始终显示全部，未跑行用占位 Pill

原双分支（latestMetric 有/无）在检测中途切到"已跑"分支后只能渲染
已检关键词，导致 93 关键词的任务在检测刚开始时只显示 1 行。改成
单一 v-for 源 keywordRows：以 config.search_keywords 为基准 93 行
不变，按 keyword 名 dict 查 latestMetric 填充每行；未匹配渲染"未跑"。
currentKeyword computed 跟着调整索引来源到 keywordRows。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4：端到端手动验证 + 全量构建

**Files:** 无修改，只跑命令 + 浏览器验证。

---

- [ ] **Step 1: 整仓构建通过**

```bash
cd frontend && pnpm build
```

Expected: `vue-tsc -b` 通过 + `vite build` 出 dist，无 type error / build error。

---

- [ ] **Step 2: 启动 dev server**

```bash
cd frontend && pnpm dev
```

应在 `http://localhost:5173`（或 vite 默认端口）开启。打开浏览器导航到「监控中心」。

---

- [ ] **Step 3: 验证模块 1（弹窗 + 列表刷新）—— baidu tab**

操作步骤：
1. 切到 **「百度排名」tab**
2. 点「批量导入」按钮
3. 粘贴 5 个测试关键词（每行一个），填任务名 + 品牌词
4. 点「批量提交」

期望行为：
- ✅ 弹窗**自动关闭**（不需要手动 X 退出）
- ✅ 「百度排名」tab 任务列表立刻多出 1 个新任务（不需要切 tab 再切回来）

如果失败：检查浏览器 console 是否有报错；确认 `submitting.value = false` 在 `close()` 之前；确认 `currentTaskType` computed 在 baidu 分支返回 `'baidu_keyword'`。

---

- [ ] **Step 4: 验证模块 1（弹窗 + 列表刷新）—— 评论三平台不回退**

操作步骤：
1. 切到 **「平台评论」tab**，子 tab 切到「抖音」
2. 点「批量导入」按钮
3. 粘贴 3 行抖音视频信息（按导入要求格式）
4. 提交

期望：弹窗关闭 + 抖音子 tab 列表立刻多出新任务。

如果失败：核对 `currentTaskType` computed 在 `commentSubtab` 走 `PLATFORM_TYPE` 分支返回正确 type。

---

- [ ] **Step 5: 验证模块 2（详情关键词渲染）—— 未检测状态**

操作步骤：
1. 在 baidu tab 创建一个新任务，包含 10 个测试关键词（不要点"立即跑"）
2. 任务列表里点击这个新任务，进入详情页

期望：
- ✅ 关键词表显示 **10 行**
- ✅ 每行的「默认卡位 / 资讯卡位」显示 "—"
- ✅ 每行的「状态」显示 `<Pill tone="info">未跑</Pill>`

---

- [ ] **Step 6: 验证模块 2 —— 检测中途状态**

操作步骤：
1. 触发该任务的「立即跑」（确保 5 个关键词都能跑——可以用通用词如 "苹果" / "华为" 避免被风控）
2. 在检测跑到第 2-3 个关键词时刷新详情页

期望：
- ✅ 关键词表仍显示 **全部 10 行**（不是只显示已检的 2-3 行）
- ✅ 已检关键词显示真实卡位数 + 「理想/未理想」Pill
- ✅ 未检关键词仍显示 "—" + 「未跑」Pill

如果失败：检查 `keywordRows` computed 的 `base = config.search_keywords` 是不是真的拿到 10 个；浏览器 devtools 看 vue inspector 里 `keywordRows.value` 的长度。

---

- [ ] **Step 7: 验证模块 2 —— 全部检测完状态**

等检测全部跑完，刷新页面。

期望：10 行全部显示真实卡位 + 状态 Pill；点击任意行，右侧 KPI 卡显示对应关键词的「默认搜索卡位 / 最新资讯卡位」数据。

点击一个未跑行（如果在 Step 6 截图时有未跑行）：右侧 KPI 卡显示 0 / "选择左侧关键词查看"（不是越界报错）。

---

- [ ] **Step 8: 全部通过 → 验证完成**

无须提交（Task 1/2/3 已分别 commit）。如果发现 bug，回到对应 Task 修补，再来一遍。

---

## Self-Review 清单（写完后过一遍）

**Spec coverage:**
- ✅ Spec §2 模块 1a (close 早退) → Task 1
- ✅ Spec §2 模块 1b (@imported baidu 分支) → Task 2
- ✅ Spec §3 模块 2 (合并渲染源 keywordRows) → Task 3
- ✅ Spec §2 验证标准 (弹窗关 + 列表立刻刷新) → Task 4 Step 3
- ✅ Spec §3 验证标准 (10 行未跑 / 中途部分检 / 全部检完三态) → Task 4 Step 5-7

**Placeholder scan:** 无 TODO / TBD / "如需" 留尾。每步都给了完整代码片段。

**Type consistency:**
- `currentTaskType` 在 Task 2 是 `computed<string>`，使用方 `<BatchImportTaskModal :default-type="currentTaskType">` 要求其 props 类型兼容 string（具体类型在 Modal 内部，Step 4 vue-tsc 会校）。
- `keywordRows` 在 Task 3 元素是 `{ keyword: string; result: BaiduKeywordMetric | null }`；`currentKeyword` 在 Step 5 改成读 `row?.result`，类型一致。
- 模板里 `row.result.default_matched_count` 等只在 `v-if="row.result"` 分支内访问，TS 应能识别 narrowing；如失败则在 v-if 改成 `v-if="row.result !== null"` 显式更明确。

**未覆盖但有意省略：**
- 自动化测试（前端无框架，spec §6 已说明只做手动验证）
- 后端改动（PR 1 全前端）

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-pr1-batch-import-detail-fixes.md`.

执行选项：

**1. Subagent-Driven (推荐)** — 每个 Task 派 fresh subagent 实施，Task 间我做 review，迭代快

**2. Inline Execution** — 在本会话直接做，executing-plans 批量执行带 checkpoints

哪种？
