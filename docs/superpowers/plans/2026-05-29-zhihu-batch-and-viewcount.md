# 知乎批量监测 + 问题浏览量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 知乎问题任务支持「总任务（批次）→ 子任务」两层结构，并在子任务层展示每次抓取记录的问题浏览量（万单位）。

**Architecture:** 沿用评论平台的「命名约定批次」（`name = "批次名 - 问题标题"`，`parseBatchName` 分组，无新表）。浏览量走问题详情 API 存进每次结果的 `metric.question_visit_count`。先做后端浏览量（B，独立可测），再做前端批次两层 UI（A）。

**Tech Stack:** Python（curl_cffi impersonate）、pytest、Vue 3 `<script setup>` + TS、vue-tsc/vite。

---

## 测试命令（worktree 必读）

```bash
cd D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b
# 后端：csm_sidecar 走主仓 editable、csm_core 走 cwd —— 两条路径都要挂
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest <test> -v
# 前端
cd frontend && npm run build      # vue-tsc -b && vite build
```

> 知乎适配器单测位置：若已有 `sidecar/tests/test_zhihu_*.py` 则加进去；否则新建 `sidecar/tests/test_zhihu_visit_count.py`。

---

## 文件结构

| 文件 | 责任 | 改动 |
|------|------|------|
| `csm_core/monitor/platforms/zhihu_question.py` | 知乎抓取适配器 | `fetch()` 加 `question_visit_count`；新增 `_fetch_visit_count` |
| `frontend/src/utils/monitor-snapshot.ts` | result→snapshot 整形 | `TaskSnapshot` 加 `question_visit_count` + 映射 |
| `frontend/src/utils/monitor-batch.ts` | 纯工具 | 新增 `formatVisitCount` |
| `frontend/src/components/monitor/BatchImportTaskModal.vue` | 批量导入 | zhihu 分支改共享品牌词 + 批次名前缀 |
| `frontend/src/components/monitor/ZhihuMonitorModule.vue` | 知乎子模块 | 扁平列表 → 批次 L1 / 子任务 L2 两层；L2 加浏览量列 |
| `frontend/src/views/MonitorView.vue` | 父组件 | 处理 `edit-batch` 事件（批次编辑）|

---

# Phase B — 问题浏览量（后端 + 前端工具）

## Task B1: 适配器抓取问题浏览量并写入 metric

**Files:**
- Modify: `csm_core/monitor/platforms/zhihu_question.py`（`fetch()` 167-187；新增 `_fetch_visit_count`）
- Test: `sidecar/tests/test_zhihu_visit_count.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""zhihu 问题浏览量抓取测试。"""
from __future__ import annotations
import pytest
from csm_core.monitor.platforms.zhihu_question import ZhihuQuestionAdapter


class _FakeResp:
    def __init__(self, status, payload): self.status_code = status; self._p = payload
    def json(self): return self._p


def test_fetch_visit_count_parses_api(monkeypatch):
    """问题详情 API 返回 visit_count → 解析成 int。"""
    def fake_get(url, **kw):
        assert "/api/v4/questions/" in url
        return _FakeResp(200, {"visit_count": 233456, "title": "x"})
    monkeypatch.setattr("curl_cffi.requests.get", fake_get)
    a = ZhihuQuestionAdapter()
    assert a._fetch_visit_count("12345") == 233456


def test_fetch_visit_count_none_on_http_error(monkeypatch):
    monkeypatch.setattr("curl_cffi.requests.get", lambda url, **kw: _FakeResp(403, {}))
    a = ZhihuQuestionAdapter()
    assert a._fetch_visit_count("12345") is None


def test_fetch_includes_visit_count_in_metric(monkeypatch):
    """fetch() 成功路径把 question_visit_count 写进 metric。"""
    from csm_core.monitor.base import MonitorTask
    a = ZhihuQuestionAdapter()
    monkeypatch.setattr(a, "_fetch_fast", lambda qid: (
        [{"author": "u", "content": "戴森好用", "voteup_count": 1, "comment_count": 0, "url": "", "created_time": None}],
        "curl_cffi",
    ))
    monkeypatch.setattr(a, "_fetch_visit_count", lambda qid: 98765)
    task = MonitorTask(
        id=1, type="zhihu_question", name="q",
        target_url="https://www.zhihu.com/question/12345",
        config={"target_brand": "戴森", "top_n": 5},
    )
    result = a.fetch(task)
    assert result.status == "ok"
    assert result.metric["question_visit_count"] == 98765
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest sidecar/tests/test_zhihu_visit_count.py -v
```
Expected: FAIL —— `_fetch_visit_count` 不存在 / metric 无 `question_visit_count`。

- [ ] **Step 3: 新增 `_fetch_visit_count` 方法**

在 `zhihu_question.py` 的 `_fetch_fast` 方法**之后**插入（无 cookie，公开问题元数据；避免动 cookie 轮换计数器 → 不引入并发/轮换副作用）：

```python
    # ── 问题浏览量（best-effort，无 cookie）────────────────────────────────
    def _fetch_visit_count(self, qid: str) -> int | None:
        """拉问题「被浏览」数。走 /api/v4/questions/{qid}?include=visit_count。

        不取 cookie（公开元数据 + 避免动轮换计数器）。任何失败返回 None，
        UI 端显示 "—"。加 INFO raw 日志便于排查 silent failure。
        """
        try:
            from curl_cffi import requests as cc_requests
        except ImportError:
            return None
        headers = {
            "User-Agent": self._next_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"https://www.zhihu.com/question/{qid}",
            "x-requested-with": "fetch",
        }
        url = f"https://www.zhihu.com/api/v4/questions/{qid}"
        try:
            resp = cc_requests.get(
                url, headers=headers, params={"include": "visit_count"},
                impersonate="chrome120", timeout=15,
            )
        except Exception as e:
            logger.info("zhihu visit_count fetch raised: %s", e)
            return None
        if resp.status_code != 200:
            logger.info("zhihu visit_count HTTP %s (qid=%s)", resp.status_code, qid)
            return None
        try:
            payload = resp.json()
        except Exception:
            logger.info("zhihu visit_count non-JSON (qid=%s)", qid)
            return None
        vc = payload.get("visit_count") if isinstance(payload, dict) else None
        vc_int = int(vc) if isinstance(vc, (int, float)) else None
        logger.info("zhihu visit_count qid=%s -> %s", qid, vc_int)
        return vc_int
```

- [ ] **Step 4: `fetch()` 成功路径写入 metric**

`fetch()` 里 `self._breaker.record_success()` 之后、`return MonitorResult(...)` 的 metric 字典，加一行 `question_visit_count`：

```python
        self._breaker.record_success()
        first_rank, matched_ranks, snapshot = self._rank_brand(
            answers, target_brand, top_n,
        )
        visit_count = self._fetch_visit_count(qid)
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="ok",
            rank=first_rank,
            metric={
                "source": source,
                "target_brand": target_brand,
                "top_n": top_n,
                "matched_count": len(matched_ranks),
                "matched_ranks": matched_ranks,
                "answers": snapshot,
                "question_id": qid,
                "question_visit_count": visit_count,
            },
        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 2。Expected: PASS（3 个测试）。

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/platforms/zhihu_question.py sidecar/tests/test_zhihu_visit_count.py
git commit -m "feat(zhihu): 抓取问题浏览量并写入 metric.question_visit_count"
```

---

## Task B2: 前端 snapshot 透传 + `formatVisitCount` 工具

**Files:**
- Modify: `frontend/src/utils/monitor-snapshot.ts`（interface 17-37、`resultToSnapshot` 67-81）
- Modify: `frontend/src/utils/monitor-batch.ts`（追加导出）
- Test: `frontend/src/utils/__tests__/monitor-batch.test.ts`（新建；若仓库无前端单测目录，本步可改为在 B2 末尾用一个临时 node 断言验证后删除——优先建正式测试）

- [ ] **Step 1: 写 `formatVisitCount` 失败测试**

新建 `frontend/src/utils/__tests__/monitor-batch.test.ts`：

```ts
import { describe, it, expect } from "vitest";
import { formatVisitCount } from "../monitor-batch";

describe("formatVisitCount", () => {
  it("< 1万 显原数", () => expect(formatVisitCount(856)).toBe("856"));
  it("1万~1亿 显 X.X万", () => {
    expect(formatVisitCount(12000)).toBe("1.2万");
    expect(formatVisitCount(3_500_000)).toBe("350万");
  });
  it("≥ 1亿 显 X.X亿", () => expect(formatVisitCount(123_000_000)).toBe("1.2亿"));
  it("空值显 —", () => {
    expect(formatVisitCount(null)).toBe("—");
    expect(formatVisitCount(undefined)).toBe("—");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/utils/__tests__/monitor-batch.test.ts`
Expected: FAIL —— `formatVisitCount` 未导出。

- [ ] **Step 3: 实现 `formatVisitCount`**

`monitor-batch.ts` 末尾追加：

```ts
/**
 * 知乎原生「被浏览」数展示：< 1万 原数；1万~1亿 → X.X万；≥ 1亿 → X.X亿。
 * 空 / NaN → "—"。去掉 ".0" 尾巴（350.0万 → 350万）。
 */
export function formatVisitCount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n < 10000) return String(n);
  if (n < 1e8) return `${(n / 10000).toFixed(1).replace(/\.0$/, "")}万`;
  return `${(n / 1e8).toFixed(1).replace(/\.0$/, "")}亿`;
}
```

- [ ] **Step 4: snapshot 透传 `question_visit_count`**

`monitor-snapshot.ts` 的 `TaskSnapshot` interface 加字段（37 行 `target_brand` 后）：

```ts
  /** 知乎专用：问题浏览量（被浏览数）；缺失为 null */
  question_visit_count: number | null;
```

`resultToSnapshot` 的 return 对象加（`target_brand` 那行后）：

```ts
    question_visit_count:
      typeof m.question_visit_count === "number" ? m.question_visit_count : null,
```

- [ ] **Step 5: 跑测试 + 类型校验**

Run:
```bash
cd frontend && npx vitest run src/utils/__tests__/monitor-batch.test.ts && npm run build
```
Expected: vitest PASS；`npm run build` exit 0。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/utils/monitor-batch.ts frontend/src/utils/monitor-snapshot.ts frontend/src/utils/__tests__/monitor-batch.test.ts
git commit -m "feat(zhihu): 前端 formatVisitCount + snapshot 透传 question_visit_count"
```

---

# Phase A — 知乎批次两层 UI

> 批次=命名约定（`parseBatchName`）。子任务=单个 zhihu_question 任务，名为 `"批次名 - 问题标题"`。L1 不可见浏览量；L2 每行显示浏览量 + 操作。

## Task A1: 批量导入弹窗 zhihu 分支改「共享品牌词 + 批次名前缀」

**Files:**
- Modify: `frontend/src/components/monitor/BatchImportTaskModal.vue`（zhihu 行解析 + 提交段，参考 472-565、72-83）

**现状**：zhihu 每行 4 列 `问题名\tURL\t品牌\ttopN`，建 N 个**扁平**任务。**目标**：批次级共享 `品牌词` + `topN` + `批次名`；每行只填 `问题名\tURL`；任务名加 `"{批次名} - "` 前缀使其在新 UI 分组。

- [ ] **Step 1: 加「批次名」批次级字段 + 让 zhihu 复用「共享品牌词」**

BatchImportTaskModal 已有 baidu 用的「共享品牌词」(`brandWord` ref，72-83 行 `needsBrandColumn`/`isBaidu`)。改造：
- 新增 ref：`const batchName = ref("");`
- 让「共享品牌词」+「共享 topN」对 zhihu 也显示（把 `needsBrandColumn`/相关 `v-if` 的条件从「仅 baidu」放宽到「baidu 或 zhihu」）。
- zhihu 行解析从 4 列改 2 列：`问题名\tURL`（更新 81 行附近的列定义 + 776 行 placeholder 示例为 `无线吸尘器哪款好用\thttps://www.zhihu.com/question/12345`）。

- [ ] **Step 2: 提交时加批次名前缀 + 共享 config**

提交循环（≈555-565 行 zhihu/comment 分支）对 zhihu 改为：

```ts
        // zhihu 批次：name 加 "{批次名} - " 前缀让 ZhihuMonitorModule 按
        // parseBatchName 分组；config 用批次共享的 brand + topN。
        name: platform.value === "zhihu_question"
          ? `${batchName.value.trim()} - ${row.questionName}`
          : row.questionName,
        config: platform.value === "zhihu_question"
          ? { target_brand: brandWord.value.trim(), top_n: sharedTopN.value }
          : (/* 评论/百度原逻辑保持不变 */ ...),
```

> `sharedTopN` / `brandWord` 用弹窗已有的共享字段 ref（baidu 已有；zhihu 复用）。校验：zhihu 模式下 `batchName` 与 `brandWord` 非空才允许提交（加一个 `disabled` 条件 + toast 提示）。

- [ ] **Step 3: 类型校验 + 构建**

Run: `cd frontend && npm run build`。Expected: exit 0。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/monitor/BatchImportTaskModal.vue
git commit -m "feat(zhihu): 批量导入改共享品牌词 + 批次名前缀（支持批次分组）"
```

---

## Task A2: ZhihuMonitorModule 扁平列表 → 批次 L1 / 子任务 L2

**Files:**
- Modify: `frontend/src/components/monitor/ZhihuMonitorModule.vue`（script 20-41 import、新增 computed/ref；template 660-916 左卡 table 段）

**结构对照（参考评论平台 `CommentMonitorModule.vue` 的 L1↔L2 钻入做法）：** 左卡在「批次列表」与「子任务列表」间切换；右侧详情卡（920-1279）**完全不动**（仍按 `selectedTaskId` 显示单问题详情）。

- [ ] **Step 1: script —— import + 批次分组 computed + 钻入态**

`ZhihuMonitorModule.vue` `<script setup>`：
- import 追加：`import { parseBatchName, formatVisitCount } from "@/utils/monitor-batch";`
- 新增：

```ts
// 当前展开的批次名；null = 显示批次列表(L1)，非 null = 显示该批次子任务(L2)
const openBatchName = ref<string | null>(null);

interface ZhihuBatch { name: string; tasks: Task[] }
const batches = computed<ZhihuBatch[]>(() => {
  const map = new Map<string, Task[]>();
  for (const t of props.tasks) {
    const b = parseBatchName(t.name);
    (map.get(b) ?? map.set(b, []).get(b)!).push(t);
  }
  return Array.from(map, ([name, tasks]) => ({ name, tasks }));
});

// L2 当前批次的子任务；批次被删空时回退到 L1
const currentBatchTasks = computed<Task[]>(() => {
  if (openBatchName.value == null) return [];
  return batches.value.find((b) => b.name === openBatchName.value)?.tasks ?? [];
});
watch(currentBatchTasks, (list) => {
  if (openBatchName.value != null && list.length === 0) openBatchName.value = null;
});

// 子任务显示名 = 去掉 "批次名 - " 前缀
function subtaskTitle(t: Task): string {
  const prefix = `${parseBatchName(t.name)} - `;
  return t.name.startsWith(prefix) ? t.name.slice(prefix.length) : t.name;
}

// 批次操作（复用现有单任务 emit；编辑批次走新事件）
function startBatch(b: ZhihuBatch) { b.tasks.forEach((t) => emit("run-task", t.id)); }
async function deleteBatch(b: ZhihuBatch) {
  // 父组件已有删除确认；这里直接逐个 emit（父对每个 id 走既有删除流程）
  b.tasks.forEach((t) => emit("delete-task", t.id));
  if (openBatchName.value === b.name) openBatchName.value = null;
}
function editBatch(b: ZhihuBatch) { emit("edit-batch", { name: b.name, tasks: b.tasks }); }
```

- 新增 emit 声明（104-115 emits 块加一条）：

```ts
  (e: "edit-batch", payload: { name: string; tasks: Task[] }): void;
```

- [ ] **Step 2: template —— 左卡顶部按钮 + L1/L2 两态**

左卡 `<section>`（665-917）内：
- 顶部「新增任务」按钮文案改「新增批次」（仍 emit `add-task`；批量导入按钮不变）。
- header row + 数据 rows 用 `v-if="openBatchName == null"`（L1）/ `v-else`（L2）切。
- **L1 批次列表**（替换 demo/real rows 段，real 分支）：

```vue
        <!-- L1: 批次列表（openBatchName == null）-->
        <template v-if="openBatchName == null">
          <div class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
               :style="{ gridTemplateColumns: '1.7fr .6fr 1.1fr', letterSpacing:'1.2px', color:'var(--ink-3)', borderBottom:'1px solid var(--line)' }">
            <div>批次名</div><div class="text-center">问题数</div><div class="text-center">操作</div>
          </div>
          <div v-if="batches.length === 0" class="py-10 text-center text-[12.5px]" :style="{ color:'var(--ink-3)' }">
            暂无监测任务 · 点「批量导入」开始
          </div>
          <div v-for="(b, i) in batches" :key="b.name"
               class="grid cursor-pointer items-center transition"
               :style="{ gridTemplateColumns:'1.7fr .6fr 1.1fr', borderBottom: i < batches.length-1 ? '1px solid var(--line)':'none', padding:'14px 8px', borderRadius:'10px' }"
               @click="openBatchName = b.name">
            <div class="truncate text-[13px] font-medium">{{ b.name }}</div>
            <div class="text-center font-display text-[13px] font-bold">{{ b.tasks.length }}</div>
            <div class="flex items-center justify-center gap-1">
              <button type="button" class="inline-flex h-7 w-7 items-center justify-center" :style="{ borderRadius:'999px', color:'var(--primary-deep)' }" title="启动批次内所有子任务" @click.stop="startBatch(b)"><Icon name="play" :size="13" /></button>
              <button type="button" class="inline-flex h-7 w-7 items-center justify-center" :style="{ borderRadius:'999px', color:'var(--ink-3)' }" title="编辑批次共享设置" @click.stop="editBatch(b)"><Icon name="edit" :size="13" /></button>
              <button type="button" class="inline-flex h-7 w-7 items-center justify-center" :style="{ borderRadius:'999px', color:'var(--ink-3)' }" title="删除整个批次" @click.stop="deleteBatch(b)"><Icon name="trash" :size="13" /></button>
            </div>
          </div>
        </template>
```

- **L2 子任务列表**（`v-else`）：在现有 real-rows 模板基础上 —— (a) 上方加面包屑 `‹ 返回批次`（点击 `openBatchName = null`），(b) `v-for` 源从 `tasks` 换成 `currentBatchTasks`，(c) 名字用 `subtaskTitle(t)`，(d) 把「类型」列（733、765、810 行的「问题」）换成浏览量列：

```vue
            <!-- 浏览量列（替换原「类型/问题」列）-->
            <div class="text-center text-[12px]" :style="{ color:'var(--ink-2)' }">
              {{ formatVisitCount(taskSnapshots[t.id]?.latest?.question_visit_count) }}
            </div>
```

  header row 的「类型」也改成「浏览量」。操作列（▶✎🗑，860-913）原样保留（已是 run/edit/delete 单任务）。

- [ ] **Step 3: 类型校验 + 构建**

Run: `cd frontend && npm run build`。Expected: exit 0（注意 `Task` 已 import；`question_visit_count` 来自 B2 的 snapshot 字段）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/monitor/ZhihuMonitorModule.vue
git commit -m "feat(zhihu): 列表改批次 L1 / 子任务 L2 两层 + L2 显示浏览量"
```

---

## Task A3: 父组件处理 `edit-batch`

**Files:**
- Modify: `frontend/src/views/MonitorView.vue`（监听 ZhihuMonitorModule 的事件处；找 `@edit-task` / `@run-task` 绑定附近）

- [ ] **Step 1: 接 `edit-batch` → 打开批量导入弹窗的「编辑」态**

在 MonitorView 渲染 `<ZhihuMonitorModule>` 处加 `@edit-batch="onEditZhihuBatch"`，并实现：

```ts
function onEditZhihuBatch(payload: { name: string; tasks: Task[] }) {
  // MVP：用现有 BatchImportTaskModal 的编辑入口，预填批次名 + 共享品牌/topN
  // （取 payload.tasks[0].config）。若暂不做编辑弹窗，退化为逐个打开
  // 单任务编辑：先实现单任务编辑已覆盖 80% 场景。
  editBatchSeed.value = {
    name: payload.name,
    target_brand: payload.tasks[0]?.config?.target_brand ?? "",
    top_n: payload.tasks[0]?.config?.top_n ?? 10,
    taskIds: payload.tasks.map((t) => t.id),
  };
  batchEditOpen.value = true;
}
```

> 若 BatchImportTaskModal 暂不支持编辑态，本任务可缩小为：`edit-batch` 时 toast「批次编辑：请逐个用子任务 ✎ 编辑」并打开 L2 —— 把完整批次编辑弹窗列为后续增强（在计划末尾「后续」标注）。实现者按 BatchImportTaskModal 现状二选一，并在 commit message 注明。

- [ ] **Step 2: 构建**

Run: `cd frontend && npm run build`。Expected: exit 0。

- [ ] **Step 3: 手动验证（worktree dev）**

```bash
cd D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b ; ./scripts/dev.ps1
```
验证：知乎 tab → 批量导入（批次名 + 共享品牌 + 多行问题）→ 左卡显示批次行（批次名/问题数/▶✎🗑）→ 点批次进 L2 → 子任务行显示浏览量 + ▶✎🗑 → ▶ 跑一次 → 浏览量出现万单位数值 → 返回批次。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/MonitorView.vue
git commit -m "feat(zhihu): MonitorView 处理批次编辑事件"
```

---

## Self-Review 检查点（执行者跑完所有 task 后）

- [ ] 后端测试通过：
```bash
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest sidecar/tests/test_zhihu_visit_count.py -v
```
- [ ] 前端：`cd frontend && npx vitest run && npm run build` 全过。
- [ ] 手动确认 L1 批次列表 / L2 子任务（含浏览量）/ 批次与子任务的 ▶✎🗑 操作。
- [ ] `git status` 无 `vite.config.*` / `package-lock.json` 误改（被 vue-tsc/npm 改了就 `git checkout --` 还原）。

## 后续（不在本计划，YAGNI）
- 批次编辑弹窗的完整实现（若 A3 走了 toast 退化路径）。
- 浏览量 DOM 兜底抓取（fast path 失败时；当前 fast path API 已覆盖绝大多数）。
- 知乎问题标题含 `" - "` 导致分组错位（沿用评论平台同款命名约定限制）。
