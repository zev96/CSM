# 全局任务托盘（Global Task Tray）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 侧栏底部常驻任务入口 + 浮层，聚合监测/引流/批量/单篇四类长任务的进度、排队/验证码状态与取消，完成后推入通知铃铛。

**Architecture:** 纯前端聚合层（spec `docs/superpowers/specs/2026-06-10-global-task-tray-design.md` 方案 A）：新 Pinia store `taskTray` 用 computed 把 4 个既有 store（monitorStatus / mining / batch / article）投影成统一 `TrayTask[]`，**不新建任何 SSE 连接**。唯一后端改动 = 单篇生成协作式取消端点（PR2）。

**Tech Stack:** Vue 3 + Pinia（setup/options store 混用，跟随各文件现状）、vitest + @vue/test-utils、FastAPI sidecar + pytest。

**勘误（相对 spec §6）：** 实地核查发现 `useNotifications().push()` 目前全工程**零调用方**（铃铛是空壳；monitorStatus 推的是 OS 级系统通知）。因此本计划补齐全部四类完成推送，新增 `monitor_done` + `mining_done` 两个通知类别；批量/单篇复用已有 `article_success` / `article_failure`。spec 已同步修订。

---

## 环境准备（执行前必读）

- 仓库根：`D:\CSM\.claude\worktrees\sharp-chatterjee-e2792c`（分支 `claude/sharp-chatterjee-e2792c`）。
- **前端**：worktree 若无 `frontend/node_modules`，先 `cd frontend && npm install`（必须 npm，pnpm 不跑 esbuild postinstall）。测试命令一律在 `frontend/` 下执行。
- **sidecar 测试**：worktree 代码必须用 PYTHONPATH 覆盖主仓 editable 安装：
  ```powershell
  $env:PYTHONPATH = "D:\CSM\.claude\worktrees\sharp-chatterjee-e2792c;D:\CSM\.claude\worktrees\sharp-chatterjee-e2792c\sidecar"
  cd D:\CSM\.claude\worktrees\sharp-chatterjee-e2792c\sidecar
  python -m pytest tests/test_generate_cancel.py -v
  ```
  （csm_core 在仓库根、csm_sidecar 在 sidecar/，两个路径都要。`python` 用主仓 venv 的解释器，`Get-Command python` 确认。）
- `vue-tsc -b` 会 emit `vite.config.js` / `*.d.ts` 触发 vite restart —— 类型检查后 `git status` 检查并 `git checkout -- vite.config.js`（及其它新 emit 文件）还原。
- PR1 = Task 1–9（本分支直接提 PR）；PR2 = Task 10–11（PR1 merge 后从最新 main 开新分支，或经用户同意后叠在同分支同一 PR）。

## 文件结构总览

| 动作 | 文件 | 职责 |
|---|---|---|
| Create | `frontend/src/utils/trayEta.ts` | EtaEstimator：进度速率 EMA → 「约 X 分钟」 |
| Create | `frontend/src/utils/__tests__/trayEta.spec.ts` | 估算器单测 |
| Modify | `frontend/src/stores/monitorStatus.ts` | SSE 处理表提取（可测试）+ taskPhase（排队/验证码）+ lastOutcomes + 铃铛推送 |
| Create | `frontend/src/stores/__tests__/monitorStatus.spec.ts` | phase/outcome/通知 单测 |
| Modify | `frontend/src/composables/useNotifications.ts` | 新类别 `monitor_done` / `mining_done` |
| Create | `frontend/src/composables/__tests__/notifications.spec.ts` | 类别注册 + 向前兼容默认开 |
| Modify | `frontend/src/stores/mining.ts` | job.finished 铃铛推送 + SSE 断线快照对账 |
| Modify | `frontend/src/stores/batch.ts` | done/error 铃铛推送 + SSE 断线快照对账 |
| Modify | `frontend/src/stores/article.ts` | done/error 铃铛推送（含 cancelled 静默分支）；PR2 加 `cancelJob()` |
| Modify | `frontend/src/api/client.ts` | `subscribe()` 增加可选 onError |
| Create | `frontend/src/stores/taskTray.ts` | 聚合 store：TrayTask 投影 + 元数据缓存 + 取消分发 + 最近完成 |
| Create | `frontend/src/stores/__tests__/taskTray.spec.ts` | 聚合/取消/最近完成 单测 |
| Create | `frontend/src/components/ui/TaskTrayPanel.vue` | 浮层（复刻 NotificationDropdown 定位范式） |
| Create | `frontend/src/components/ui/__tests__/TaskTrayPanel.spec.ts` | 冒烟测试 |
| Modify | `frontend/src/components/LeftNav.vue` | 任务按钮 + 数字角标 + 呼吸动效 + 与铃铛互斥 |
| Modify | `sidecar/csm_sidecar/services/generate_service.py` | （PR2）协作式取消：_live/_cancelled + checkpoint |
| Modify | `sidecar/csm_sidecar/routes/generate.py` | （PR2）`POST /api/generate/{job_id}/cancel` |
| Create | `sidecar/tests/test_generate_cancel.py` | （PR2）取消端点/服务单测 |

通用测试 mock 组（vitest，下文简称「标准 mocks」——凡 import 链碰到 sidecar/Tauri 的 spec 文件开头都要）：

```ts
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("@/composables/useSystemNotify", () => ({
  useSystemNotify: () => ({ notify: vi.fn().mockResolvedValue(undefined) }),
}));
vi.mock("@/api/client", () => ({ subscribe: vi.fn(() => () => {}) }));
```

---

### Task 1: EtaEstimator（`utils/trayEta.ts`）

**Files:**
- Create: `frontend/src/utils/trayEta.ts`
- Test: `frontend/src/utils/__tests__/trayEta.spec.ts`

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/utils/__tests__/trayEta.spec.ts
import { describe, it, expect } from "vitest";

import { EtaEstimator } from "@/utils/trayEta";

describe("EtaEstimator", () => {
  it("首个样本与进度 <5% 时不出 ETA", () => {
    const e = new EtaEstimator();
    expect(e.observe("k", 0.02, 0)).toBeNull();
    expect(e.observe("k", 0.04, 60_000)).toBeNull(); // 有速率但 p < 0.05
  });

  it("稳定速率 → 约 X 分钟", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.1, 0);
    // 60s 走了 10% → 剩 80% ≈ 8 分钟
    expect(e.observe("k", 0.2, 60_000)).toBe("约 8 分钟");
  });

  it("剩余 <60s → 不到 1 分钟", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.5, 0);
    expect(e.observe("k", 0.98, 60_000)).toBe("不到 1 分钟");
  });

  it("进度回退（同 key 复用于新一轮任务）→ 重置不出脏 ETA", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.5, 0);
    e.observe("k", 0.9, 10_000);
    expect(e.observe("k", 0.1, 20_000)).toBeNull();
  });

  it("EMA 平滑：速率突变不会让 ETA 跳变到瞬时值", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.1, 0);
    e.observe("k", 0.2, 60_000);          // rate=0.1/min
    const text = e.observe("k", 0.21, 120_000); // 瞬时掉到 0.01/min
    // EMA(α=0.3)=0.3*0.01+0.7*0.1=0.037/min → 剩 0.79/0.037≈21.4min
    expect(text).toBe("约 21 分钟");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/utils/__tests__/trayEta.spec.ts`
Expected: FAIL —— `Cannot find module '@/utils/trayEta'`

- [ ] **Step 3: 实现**

```ts
// frontend/src/utils/trayEta.ts
/**
 * 进度 → 剩余时间估算（纯前端，后端不发 ETA）。
 *
 * 每个 key（托盘卡片）维护一条进度速率的 EMA（α=0.3）；
 * eta = (1 - p) / rate。显示门槛：≥2 个样本且 p ≥ 5%，
 * 否则返回 null（UI 不显示，避免冷启动数字乱跳）。
 * 进度回退视为同 key 被新一轮任务复用 → 重置。
 *
 * `now` 由调用方传入（生产传 Date.now()），测试可注入假时钟。
 */
const EMA_ALPHA = 0.3;
const MIN_PROGRESS = 0.05;

interface Sample {
  p: number;
  t: number;
  rate: number | null; // progress per ms
  n: number;
}

export class EtaEstimator {
  private samples = new Map<string, Sample>();

  observe(key: string, p: number, now: number): string | null {
    const prev = this.samples.get(key);
    if (!prev || p < prev.p) {
      this.samples.set(key, { p, t: now, rate: null, n: 1 });
      return null;
    }
    if (p > prev.p && now > prev.t) {
      const inst = (p - prev.p) / (now - prev.t);
      const rate = prev.rate == null ? inst : EMA_ALPHA * inst + (1 - EMA_ALPHA) * prev.rate;
      this.samples.set(key, { p, t: now, rate, n: prev.n + 1 });
    }
    const cur = this.samples.get(key)!;
    if (cur.n < 2 || cur.rate == null || cur.rate <= 0 || p < MIN_PROGRESS) return null;
    const remainMs = (1 - p) / cur.rate;
    if (remainMs < 60_000) return "不到 1 分钟";
    return `约 ${Math.round(remainMs / 60_000)} 分钟`;
  }

  /** 任务结束后释放，防 Map 无界增长。 */
  drop(key: string): void {
    this.samples.delete(key);
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/utils/__tests__/trayEta.spec.ts`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/trayEta.ts frontend/src/utils/__tests__/trayEta.spec.ts
git commit -m "feat(tray): ETA 估算器（进度速率 EMA）"
```

---

### Task 2: monitorStatus 扩展 — SSE 处理表提取 + 排队/验证码 phase + 终态记录

**Files:**
- Modify: `frontend/src/stores/monitorStatus.ts`
- Test: `frontend/src/stores/__tests__/monitorStatus.spec.ts`（新建）

后端 `/api/monitor/events` 早就在广播 `waiting_chrome_close / chrome_closed / captcha_required / captcha_resolved / captcha_timeout`（见 `sidecar/csm_sidecar/services/monitor_loop.py:56-63`，payload 是 MonitorEvent dataclass，带 `task_id`），前端一直没接。本任务把内联 SSE handler 提取成命名表（`_dispatchSse` 测试钩子），并新增两块状态。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/stores/__tests__/monitorStatus.spec.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const getMock = vi.fn();
const postMock = vi.fn();
// 标准 mocks（见计划开头）
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("@/composables/useSystemNotify", () => ({
  useSystemNotify: () => ({ notify: vi.fn().mockResolvedValue(undefined) }),
}));
vi.mock("@/api/client", () => ({ subscribe: vi.fn(() => () => {}) }));

import { useMonitorStatus } from "@/stores/monitorStatus";

describe("monitorStatus — phase / outcome", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset();
    postMock.mockReset();
  });

  it("waiting_chrome_close → phaseOf=waiting_chrome；chrome_closed 清除", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("waiting_chrome_close", { task_id: 7, remaining_s: 60 });
    expect(m.phaseOf(7)).toBe("waiting_chrome");
    m._dispatchSse("chrome_closed", { task_id: 7 });
    expect(m.phaseOf(7)).toBeNull();
  });

  it("captcha_required → phase=captcha；started 清 phase", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("captcha_required", { task_id: 7 });
    expect(m.phaseOf(7)).toBe("captcha");
    m._dispatchSse("started", { task_id: 7 });
    expect(m.phaseOf(7)).toBeNull();
  });

  it("finished → 记 outcome=done、清 running/phase", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("waiting_chrome_close", { task_id: 7 });
    m._dispatchSse("finished", { task_id: 7, progress_total: 10 });
    expect(m.isRunning(7)).toBe(false);
    expect(m.phaseOf(7)).toBeNull();
    expect(m.lastOutcomes[7]).toBe("done");
  });

  it("failed(cancelled by user) → outcome=cancelled；其他 failed → failed", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("failed", { task_id: 7, error: "cancelled by user" });
    expect(m.lastOutcomes[7]).toBe("cancelled");
    m.markRunning(8);
    m._dispatchSse("failed", { task_id: 8, error: "boom" });
    expect(m.lastOutcomes[8]).toBe("failed");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/monitorStatus.spec.ts`
Expected: FAIL —— `m._dispatchSse is not a function`

- [ ] **Step 3: 实现（monitorStatus.ts 改动）**

3a. 文件顶部 `interface ProgressEntry` 后加导出类型：

```ts
export type MonitorTaskPhase = "waiting_chrome" | "captcha";
```

3b. store 内 `taskProgress` 声明后加状态与助手：

```ts
  // 任务特殊阶段（百度原生 Chrome：排队等浏览器空闲 / 等人工验证码）。
  // 由 waiting_chrome_close / captcha_* SSE 事件驱动；started/finished/
  // failed/hydrate 时清理。托盘用它区分「排队中/需人工验证」与真「运行中」。
  const taskPhase = ref<Record<number, MonitorTaskPhase>>({});
  // 最近一次终态 —— 托盘「最近完成」区推断 ✓/✗ 用。只增不删（数量级 = 任务数）。
  const lastOutcomes = ref<Record<number, "done" | "failed" | "cancelled">>({});

  function phaseOf(taskId: number): MonitorTaskPhase | null {
    return taskPhase.value[taskId] ?? null;
  }

  function _setPhase(taskId: number, phase: MonitorTaskPhase | null): void {
    const has = taskId in taskPhase.value;
    if (phase == null && !has) return;
    const next = { ...taskPhase.value };
    if (phase == null) delete next[taskId];
    else next[taskId] = phase;
    taskPhase.value = next;
  }
```

3c. `clearRunning` 函数体第一行加：`_setPhase(taskId, null);`

3d. `hydrate()` 里 `taskProgress.value = nextProgress;` 之后加同款 phase 清理：

```ts
      const nextPhase: Record<number, MonitorTaskPhase> = {};
      for (const [k, v] of Object.entries(taskPhase.value)) {
        const numK = Number(k);
        if (next.has(numK)) nextPhase[numK] = v;
      }
      taskPhase.value = nextPhase;
```

3e. 把 `start()` 里传给 `subscribe(...)` 的内联对象整体提取为 store 工厂内的命名表（放在 `start()` 之前），并加新事件。**搬移时保留原 handler 逻辑不变**，只在标注处新增：

```ts
  // SSE 处理表 —— 提取成命名对象让单测能经 _dispatchSse 直接驱动，
  // 不需要真 EventSource。start() 把同一张表绑给 subscribe。
  const _sseHandlers: Record<string, (d: any) => void> = {
    started: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) {
        markRunning(d.task_id);
        _setPhase(d.task_id, null); // 新增：真正开跑，清掉排队/验证码态
        _optimisticMarkedAt.delete(d.task_id);
      }
    },
    progress: (d: any) => {
      if (typeof d.task_id !== "number") return;
      const cur = typeof d.progress_current === "number" ? d.progress_current : 0;
      const tot = typeof d.progress_total === "number" ? d.progress_total : 0;
      setProgress(d.task_id, cur, tot);
    },
    needs_captcha: (d: any) => {
      const kw = typeof d.keyword === "string" ? d.keyword : "";
      void _notify?.("CSM 百度监控", `需要人工解验证码（关键词：${kw}），点击浏览器窗口`);
    },
    waiting_chrome_close: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) _setPhase(d.task_id, "waiting_chrome");
    },
    chrome_closed: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) _setPhase(d.task_id, null);
    },
    captcha_required: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) _setPhase(d.task_id, "captcha");
    },
    captcha_resolved: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) _setPhase(d.task_id, null);
    },
    captcha_timeout: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) _setPhase(d.task_id, null);
    },
    finished: (d: any) => {
      if (typeof d.task_id === "number") {
        clearRunning(d.task_id);
        lastOutcomes.value = { ...lastOutcomes.value, [d.task_id]: "done" }; // 新增
        const total = typeof d.progress_total === "number" ? String(d.progress_total) : "?";
        void _notify?.("CSM 百度监控", `监控完成，已抓 ${total} 词`);
      }
    },
    failed: (d: any) => {
      if (typeof d.task_id !== "number") return;
      clearRunning(d.task_id);
      const err = String(d.error ?? "");
      lastOutcomes.value = {                                            // 新增
        ...lastOutcomes.value,
        [d.task_id]: err.includes("cancelled by user") ? "cancelled" : "failed",
      };
      if (err.includes("cancelled by user")) return;
      if (err.startsWith("风控拦截") || err.includes("captcha")) return;
      const reason = err.includes("timeout waiting for platform slot")
        ? "队列繁忙，请稍后重试或减少同时运行的任务"
        : (err.split("\n")[0] || "未知原因");
      toast.error(`监测任务 #${d.task_id} 失败：${reason}`);
    },
  };

  /** 测试钩子：把一条 SSE 事件喂给处理表。生产路径 subscribe 绑同一张表。 */
  function _dispatchSse(kind: string, d: any): void {
    _sseHandlers[kind]?.(d);
  }
```

`start()` 简化为：

```ts
    stopSse = subscribe("/api/monitor/events", _sseHandlers);
```

3f. store return 对象追加：`taskPhase, lastOutcomes, phaseOf, _dispatchSse,`

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/stores/__tests__/monitorStatus.spec.ts`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/monitorStatus.ts frontend/src/stores/__tests__/monitorStatus.spec.ts
git commit -m "feat(tray): monitorStatus 接 waiting/captcha 事件 + 终态记录（SSE 处理表可测试化）"
```

---

### Task 3: 通知类别 + 四类任务完成推送进铃铛

**Files:**
- Modify: `frontend/src/composables/useNotifications.ts`
- Modify: `frontend/src/stores/monitorStatus.ts`（finished/failed 推铃铛）
- Modify: `frontend/src/stores/mining.ts`（job.finished 推铃铛）
- Modify: `frontend/src/stores/batch.ts`（done/error 推铃铛）
- Modify: `frontend/src/stores/article.ts`（done/error 推铃铛 + cancelled 静默分支）
- Test: `frontend/src/composables/__tests__/notifications.spec.ts`（新建）、`frontend/src/stores/__tests__/monitorStatus.spec.ts`（追加）

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/composables/__tests__/notifications.spec.ts
import { describe, it, expect, beforeEach, vi } from "vitest";

import {
  NOTIFICATION_CATEGORIES,
  useNotifications,
} from "@/composables/useNotifications";

describe("notification categories — 任务托盘新增", () => {
  beforeEach(() => {
    localStorage.clear();
    const n = useNotifications();
    n.clear();
    n.setEnabled(true);
  });

  it("注册了 monitor_done / mining_done 两个类别", () => {
    const keys = NOTIFICATION_CATEGORIES.map((c) => c.key);
    expect(keys).toContain("monitor_done");
    expect(keys).toContain("mining_done");
  });

  it("旧 localStorage 没有新类别 key 时默认放行（向前兼容）", async () => {
    // loadCategories 在模块加载时执行一次 —— 必须 resetModules + 动态
    // import 才能让它对着「旧版本写的 blob」重跑。
    localStorage.setItem(
      "csm.notify.categories.v1",
      JSON.stringify({ system: true }), // 旧 blob，缺 mining_done key
    );
    vi.resetModules();
    const mod = await import("@/composables/useNotifications");
    const n = mod.useNotifications();
    n.clear();
    n.setEnabled(true);
    const id = n.push("引流任务完成", { category: "mining_done" });
    expect(id).not.toBeNull();
  });
});
```

monitorStatus.spec.ts 追加（同一 describe 文件里新增一个 describe 块）：

```ts
import { useNotifications } from "@/composables/useNotifications";

describe("monitorStatus — 铃铛通知", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    const n = useNotifications();
    n.clear();
    n.setEnabled(true);
  });

  it("finished → 推 monitor_done 铃铛通知", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("finished", { task_id: 7, progress_total: 10 });
    const n = useNotifications();
    expect(n.items.value[0]?.category).toBe("monitor_done");
    expect(n.items.value[0]?.tone).toBe("success");
  });

  it("failed(cancelled by user) → 不推铃铛；普通 failed → 推 monitor_alert", () => {
    const m = useMonitorStatus();
    const n = useNotifications();
    m.markRunning(7);
    m._dispatchSse("failed", { task_id: 7, error: "cancelled by user" });
    expect(n.items.value.length).toBe(0);
    m.markRunning(8);
    m._dispatchSse("failed", { task_id: 8, error: "boom" });
    expect(n.items.value[0]?.category).toBe("monitor_alert");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/composables/__tests__/notifications.spec.ts src/stores/__tests__/monitorStatus.spec.ts`
Expected: FAIL —— 类别不存在 / items 为空

- [ ] **Step 3: 实现**

3a. `useNotifications.ts`：`NotificationCategory` union 追加两行：

```ts
  | "monitor_done"
  | "mining_done"
```

`NOTIFICATION_CATEGORIES` 数组在 `monitor_alert` 条目后插入：

```ts
  {
    key: "monitor_done",
    label: "监测任务完成",
    hint: "「立刻监测」任务跑完一轮时推送",
  },
  {
    key: "mining_done",
    label: "引流任务完成",
    hint: "视频抓取任务结束（含部分完成）时推送",
  },
```

3b. `monitorStatus.ts`：imports 加 `import { useNotifications } from "@/composables/useNotifications";`；store 工厂里 `const toast = useToast();` 旁加 `const bell = useNotifications();`。

`_sseHandlers.finished` 的 `void _notify?.(...)` 之后加：

```ts
        bell.push("监测任务完成", {
          body: `任务 #${d.task_id} · 共 ${total} 项`,
          tone: "success",
          category: "monitor_done",
        });
```

`_sseHandlers.failed` 的 `toast.error(...)` 之后加：

```ts
      bell.push(`监测任务 #${d.task_id} 失败`, {
        body: reason,
        tone: "error",
        category: "monitor_alert",
      });
```

（cancelled-by-user / 风控分支保持提前 return，不推铃铛。）

3c. `mining.ts`：imports 加 `import { useNotifications } from "@/composables/useNotifications";`；store 工厂顶部（`const activeJob = ...` 附近）加 `const bell = useNotifications()`。`subscribeToJob` 的 `"job.finished"` handler 在 `_patchJobInList(...)` 之后、`if (stopSse)` 之前加：

```ts
        const st = String(d.summary?.status ?? "")
        const ok = st === "done" || st === "completed"
        const kw = activeJob.value?.id === d.job_id
          ? activeJob.value.keyword
          : (jobs.value.find(j => j.id === d.job_id)?.keyword ?? "")
        bell.push("引流任务完成", {
          body: `「${kw}」${ok ? "全部平台完成" : "部分平台未完成"}`,
          tone: ok ? "success" : "warn",
          category: "mining_done",
        })
```

3d. `batch.ts`：imports 加 `import { useNotifications } from "@/composables/useNotifications";`。`done` handler 在 `this._teardown();` 之前加：

```ts
          const failedCount = Number((d.by_status ?? {}).failed ?? 0);
          useNotifications().push("批量生成完成", {
            body: `共 ${this.total} 篇 · 成功 ${Number((d.by_status ?? {}).success ?? 0)}${failedCount ? ` · 失败 ${failedCount}` : ""}`,
            tone: failedCount ? "warn" : "success",
            category: "article_success",
          });
```

`error` handler 在 `this._teardown();` 之前加：

```ts
          useNotifications().push("批量生成失败", {
            body: this.error ?? "",
            tone: "error",
            category: "article_failure",
          });
```

3e. `article.ts`：imports 加 `import { useNotifications } from "@/composables/useNotifications";`。`done` handler 在 `this._teardown();` 之前加：

```ts
          useNotifications().push("文章生成完成", {
            body: this.title,
            tone: "success",
            category: "article_success",
          });
```

`error` handler 整体替换为（cancelled 分支是 PR2 取消端点的前向兼容，PR1 阶段 `d.cancelled` 恒为 undefined、无副作用）：

```ts
        error: (d: any) => {
          if (d?.cancelled) {
            // 用户主动取消（/api/generate/{id}/cancel）—— 静默回 idle，不算失败
            this.status = "idle";
            this.error = null;
            this._teardown();
            return;
          }
          this.error = d.error ?? "unknown error";
          this.status = "error";
          useNotifications().push("文章生成失败", {
            body: this.error ?? "",
            tone: "error",
            category: "article_failure",
          });
          this._teardown();
        },
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/composables/__tests__/notifications.spec.ts src/stores/__tests__/monitorStatus.spec.ts`
Expected: PASS

注：mining/batch/article 的推送代码位于 SSE 订阅闭包内，无法低成本单测（subscribe 已被 mock）；由 Task 9 的真机验证覆盖。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useNotifications.ts frontend/src/composables/__tests__/notifications.spec.ts frontend/src/stores/monitorStatus.ts frontend/src/stores/__tests__/monitorStatus.spec.ts frontend/src/stores/mining.ts frontend/src/stores/batch.ts frontend/src/stores/article.ts
git commit -m "feat(tray): 四类任务完成/失败推送进通知铃铛（新增 monitor_done/mining_done 类别）"
```

---

### Task 4: taskTray store — 监测分组聚合 + 任务名缓存

**Files:**
- Create: `frontend/src/stores/taskTray.ts`
- Test: `frontend/src/stores/__tests__/taskTray.spec.ts`

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/stores/__tests__/taskTray.spec.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { nextTick } from "vue";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("@/composables/useSystemNotify", () => ({
  useSystemNotify: () => ({ notify: vi.fn().mockResolvedValue(undefined) }),
}));
vi.mock("@/api/client", () => ({ subscribe: vi.fn(() => () => {}) }));

import { useTaskTray } from "@/stores/taskTray";
import { useMonitorStatus } from "@/stores/monitorStatus";

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  getMock.mockReset().mockResolvedValue({
    data: {
      tasks: [
        { id: 11, name: "扫地机器人怎么选", type: "zhihu_question" },
        { id: 12, name: "吸尘器推荐", type: "zhihu_question" },
        { id: 31, name: "宠物吸尘器", type: "baidu_keyword" },
      ],
    },
  });
  postMock.mockReset().mockResolvedValue({ data: { cancelled: true } });
});

describe("taskTray — 监测聚合", () => {
  it("running 任务按显示组聚合成卡，count=底层任务数", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    monitor.markRunning(31);
    await flushPromises(); // 元数据懒加载落地
    await nextTick();

    expect(tray.runningTasks.length).toBe(2);
    const zhihu = tray.runningTasks.find((t) => t.title.includes("知乎问题监测"))!;
    expect(zhihu.title).toBe("知乎问题监测 · 2 个任务");
    expect(zhihu.subtitle).toContain("扫地机器人怎么选");
    expect(zhihu.count).toBe(2);
    expect(zhihu.memberIds).toEqual([11, 12]);
    expect(tray.runningCount).toBe(3);
  });

  it("组内进度 Σcurrent/Σtotal；全组无进度 → null（不确定态）", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    monitor.markRunning(31);
    await flushPromises();
    monitor.setProgress(11, 3, 10);
    monitor.setProgress(12, 1, 10);
    await nextTick();

    const zhihu = tray.runningTasks.find((t) => t.title.includes("知乎问题监测"))!;
    expect(zhihu.progress).toBeCloseTo(0.2);
    const baidu = tray.runningTasks.find((t) => t.title.includes("百度排名监测"))!;
    expect(baidu.progress).toBeNull();
  });

  it("waiting_chrome phase → state=waiting + 排队文案；captcha 优先级更高", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(31);
    await flushPromises();
    monitor._dispatchSse("waiting_chrome_close", { task_id: 31 });
    await nextTick();
    let baidu = tray.runningTasks.find((t) => t.title.includes("百度排名监测"))!;
    expect(baidu.state).toBe("waiting");
    expect(baidu.subtitle).toContain("等待浏览器空闲");

    monitor._dispatchSse("captcha_required", { task_id: 31 });
    await nextTick();
    baidu = tray.runningTasks.find((t) => t.title.includes("百度排名监测"))!;
    expect(baidu.state).toBe("captcha");
  });

  it("元数据缓存未命中 → 标题退化为「监测任务」、子标题「任务 #id」", async () => {
    getMock.mockResolvedValue({ data: { tasks: [] } });
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(99);
    await flushPromises();
    await nextTick();
    expect(tray.runningTasks[0].title).toBe("监测任务");
    expect(tray.runningTasks[0].subtitle).toContain("任务 #99");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/taskTray.spec.ts`
Expected: FAIL —— `Cannot find module '@/stores/taskTray'`

- [ ] **Step 3: 实现 taskTray.ts（本任务先落监测部分，mining/batch/article 的 computed 返回 null 占位由 Task 5 填充——文件一次写全也可以，则 Task 5 Step 2 直接绿）**

完整文件（含 Task 5/6 会用到的全部内容，一次写全）：

```ts
// frontend/src/stores/taskTray.ts
/**
 * TaskTray — 全局任务托盘聚合层（spec: 2026-06-10-global-task-tray-design）。
 *
 * 纯前端：把 4 个既有 store（monitorStatus / mining / batch / article）的
 * 运行态用 computed 投影成统一 TrayTask[]，给 LeftNav 任务按钮 + 浮层渲染。
 * 不新建任何 SSE 连接 —— 事件流由各源 store 自己持有；本 store 只做投影
 * 与「最近完成」转移登记。将来若上后端统一任务注册表，只换这里的数据源，
 * TrayTask 接口与 UI 不动。
 */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import type { RouteLocationRaw } from "vue-router";

import { useArticle } from "@/stores/article";
import { useBatch } from "@/stores/batch";
import { useMiningStore, type Platform, type PlatformProgress } from "@/stores/mining";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { useSidecar } from "@/stores/sidecar";
import { EtaEstimator } from "@/utils/trayEta";

export type TrayKind = "monitor" | "mining" | "batch" | "article";
export type TrayRunState = "running" | "waiting" | "captcha";
export type TrayOutcome = "done" | "failed" | "cancelled";

export interface TrayTask {
  /** "monitor:<显示组>" | "mining:<id>" | "batch:<uuid>" | "article:<uuid>" */
  key: string;
  kind: TrayKind;
  icon: string;
  title: string;
  subtitle: string;
  /** 0~1；null = 不确定态（ProgressBar shimmer） */
  progress: number | null;
  state: TrayRunState;
  etaText: string | null;
  cancellable: boolean;
  route: RouteLocationRaw;
  /** 该卡片代表的底层任务数（侧栏角标累加用） */
  count: number;
  /** 监测组卡专用：组内 task_id 列表（取消分发 / 终态推断用） */
  memberIds?: number[];
}

export interface TrayFinished {
  key: string;
  kind: TrayKind;
  icon: string;
  title: string;
  outcome: TrayOutcome;
  finishedAt: number;
  route: RouteLocationRaw;
}

/**
 * 监测 type → 显示组（卡片标题）/ 监测中心 tab。type 枚举与
 * csm_core/monitor/base.py 的 TaskType 一一对应；三个评论平台归并为
 * 一张「评论留存监测」卡（同 tab 同语义，3 张同名卡只会更吵）。
 */
export const MONITOR_TYPE_META: Record<string, { group: string; tab: string }> = {
  zhihu_question: { group: "知乎问题监测", tab: "zhihu" },
  zhihu_search: { group: "知乎搜索监测", tab: "zhihu_search" },
  bilibili_comment: { group: "评论留存监测", tab: "comment" },
  douyin_comment: { group: "评论留存监测", tab: "comment" },
  kuaishou_comment: { group: "评论留存监测", tab: "comment" },
  baidu_keyword: { group: "百度排名监测", tab: "baidu" },
  geo_query: { group: "AI 卡位监测", tab: "geo" },
};

const KIND_ICON: Record<TrayKind, string> = {
  monitor: "radar",
  mining: "video",
  batch: "stack",
  article: "edit",
};

const PLATFORM_LABEL: Record<Platform, string> = {
  douyin: "抖音",
  bilibili: "B站",
  kuaishou: "快手",
};

const MAX_FINISHED = 3;

export const useTaskTray = defineStore("taskTray", () => {
  const monitor = useMonitorStatus();
  const mining = useMiningStore();
  const batch = useBatch();
  const article = useArticle();

  const eta = new EtaEstimator();

  // ── 监测任务元数据缓存（id → {name,type}）──────────────────────────
  // 懒加载：running 集合出现缓存未命中的 id 时拉一次全量
  // GET /api/monitor/tasks（type 参数可选，不传=全量）。
  const monitorTaskMeta = ref<Record<number, { name: string; type: string }>>({});
  let _metaInFlight = false;
  async function ensureMonitorMeta(force = false): Promise<void> {
    if (_metaInFlight) return;
    if (!force && Object.keys(monitorTaskMeta.value).length > 0) return;
    _metaInFlight = true;
    try {
      const r = await useSidecar().client.get("/api/monitor/tasks");
      const tasks: Array<{ id: number; name: string; type: string }> =
        Array.isArray(r.data?.tasks) ? r.data.tasks : [];
      const next: Record<number, { name: string; type: string }> = {};
      for (const t of tasks) next[t.id] = { name: t.name, type: t.type };
      monitorTaskMeta.value = next;
    } catch {
      /* 拉不到先显示「任务 #id」；running 集合下次变化会再试 */
    } finally {
      _metaInFlight = false;
    }
  }

  watch(
    () => Array.from(monitor.runningTaskIds),
    (ids) => {
      if (ids.length === 0) return;
      const missing = ids.some((id) => !(id in monitorTaskMeta.value));
      void ensureMonitorMeta(missing);
    },
    { immediate: true },
  );

  // ── 监测：按显示组聚合 ────────────────────────────────────────────
  const monitorCards = computed<TrayTask[]>(() => {
    const groups = new Map<string, { ids: number[]; tab: string }>();
    for (const id of monitor.runningTaskIds) {
      const meta = monitorTaskMeta.value[id];
      const tm = meta ? MONITOR_TYPE_META[meta.type] : undefined;
      const groupName = tm?.group ?? "监测任务";
      const entry = groups.get(groupName) ?? { ids: [], tab: tm?.tab ?? "zhihu" };
      entry.ids.push(id);
      groups.set(groupName, entry);
    }
    const out: TrayTask[] = [];
    for (const [groupName, g] of groups) {
      let cur = 0;
      let tot = 0;
      for (const id of g.ids) {
        const p = monitor.progressOf(id);
        if (p && p.total > 0) {
          cur += p.current;
          tot += p.total;
        }
      }
      const progress = tot > 0 ? Math.min(1, cur / tot) : null;
      // 状态优先级：captcha > waiting > running
      let state: TrayRunState = "running";
      for (const id of g.ids) {
        const ph = monitor.phaseOf(id);
        if (ph === "captcha") {
          state = "captcha";
          break;
        }
        if (ph === "waiting_chrome") state = "waiting";
      }
      const firstName = monitorTaskMeta.value[g.ids[0]]?.name ?? `任务 #${g.ids[0]}`;
      const key = `monitor:${groupName}`;
      out.push({
        key,
        kind: "monitor",
        icon: KIND_ICON.monitor,
        title: g.ids.length > 1 ? `${groupName} · ${g.ids.length} 个任务` : groupName,
        subtitle:
          state === "waiting"
            ? "排队中 · 等待浏览器空闲"
            : state === "captcha"
              ? `需要人工验证 ·「${firstName}」`
              : `正在检查「${firstName}」`,
        progress,
        state,
        etaText: progress == null ? null : eta.observe(key, progress, Date.now()),
        cancellable: true,
        route: { name: "monitor", query: { tab: g.tab } },
        count: g.ids.length,
        memberIds: g.ids.slice(),
      });
    }
    return out;
  });

  // ── 引流（单活跃 job）────────────────────────────────────────────
  const miningCard = computed<TrayTask | null>(() => {
    if (!mining.hasRunningJob || !mining.activeJob) return null;
    const job = mining.activeJob;
    const entries = Object.entries(job.progress ?? {}) as [Platform, PlatformProgress][];
    let got = 0;
    let target = 0;
    let captcha = false;
    const parts: string[] = [];
    for (const [p, pr] of entries) {
      if (!pr) continue;
      got += pr.got ?? 0;
      target += pr.target ?? 0;
      if (pr.phase === "captcha_waiting") {
        captcha = true;
        parts.push(`${PLATFORM_LABEL[p]}等待验证`);
      } else if (pr.phase === "done") {
        parts.push(`${PLATFORM_LABEL[p]}已完成`);
      } else {
        parts.push(`${PLATFORM_LABEL[p]} ${pr.got ?? 0}/${pr.target ?? 0}`);
      }
    }
    const key = `mining:${job.id}`;
    const progress = target > 0 ? Math.min(1, got / target) : null;
    return {
      key,
      kind: "mining",
      icon: KIND_ICON.mining,
      title: `引流抓取 ·「${job.keyword}」`,
      subtitle: parts.join(" · ") || "准备中…",
      progress,
      state: captcha ? "captcha" : "running",
      etaText: progress == null ? null : eta.observe(key, progress, Date.now()),
      cancellable: true,
      route: { name: "mining" },
      count: 1,
    };
  });

  // ── 批量生成 ─────────────────────────────────────────────────────
  const batchCard = computed<TrayTask | null>(() => {
    if (batch.status !== "running") return null;
    const runningItem = batch.items.find((i) => i.status === "running");
    const doneCount = batch.items.filter(
      (i) => i.status === "success" || i.status === "failed" || i.status === "cancelled",
    ).length;
    const key = `batch:${batch.jobId ?? "pending"}`;
    const progress = batch.total > 0 ? batch.progress : null;
    return {
      key,
      kind: "batch",
      icon: KIND_ICON.batch,
      title: `批量生成 · ${batch.total} 篇`,
      subtitle: runningItem
        ? `第 ${doneCount + 1}/${batch.total} 篇 ·「${runningItem.keyword}」`
        : `已完成 ${doneCount}/${batch.total} 篇`,
      progress,
      state: "running",
      etaText: progress == null ? null : eta.observe(key, progress, Date.now()),
      cancellable: true,
      route: { name: "batch" },
      count: 1,
    };
  });

  // ── 单篇生成 ─────────────────────────────────────────────────────
  const articleCard = computed<TrayTask | null>(() => {
    if (article.status !== "running") return null;
    const key = `article:${article.jobId ?? "pending"}`;
    const progress = article.stageIndex >= 0 ? article.progress : null;
    return {
      key,
      kind: "article",
      icon: KIND_ICON.article,
      title: `单篇生成 ·「${article.title || article.lastRequest?.keyword || ""}」`,
      subtitle: article.currentStage
        ? `${article.currentStage}（${article.stageIndex + 1}/${article.stages.length}）`
        : "准备中…",
      progress,
      state: "running",
      etaText: progress == null ? null : eta.observe(key, progress, Date.now()),
      cancellable: false, // PR2 接通 /api/generate/{id}/cancel 后翻 true
      route: { name: "article" },
      count: 1,
    };
  });

  const runningTasks = computed<TrayTask[]>(() => {
    const out: TrayTask[] = [...monitorCards.value];
    if (miningCard.value) out.push(miningCard.value);
    if (batchCard.value) out.push(batchCard.value);
    if (articleCard.value) out.push(articleCard.value);
    return out;
  });

  const runningCount = computed(() =>
    runningTasks.value.reduce((n, t) => n + t.count, 0),
  );

  // ── 最近完成区（内存，最多 MAX_FINISHED 条）──────────────────────
  const recentFinished = ref<TrayFinished[]>([]);

  function _outcomeFor(task: TrayTask): TrayOutcome {
    switch (task.kind) {
      case "mining": {
        const st = String(mining.activeJob?.status ?? "");
        if (st.includes("fail")) return "failed";
        if (st === "cancelled" || st === "interrupted") return "cancelled";
        return "done"; // done / completed / partial_done
      }
      case "batch": {
        if (batch.status === "error") return "failed";
        if (batch.status === "cancelled") return "cancelled";
        return "done";
      }
      case "article": {
        if (article.status === "error") return "failed";
        if (article.status === "idle") return "cancelled"; // 运行中只会因取消回 idle
        return "done";
      }
      case "monitor": {
        let outcome: TrayOutcome = "done";
        for (const id of task.memberIds ?? []) {
          const o = monitor.lastOutcomes[id];
          if (o === "failed") return "failed";
          if (o === "cancelled") outcome = "cancelled";
        }
        // 注：sidecar 重启被 hydrate 清掉的任务没有终态记录 → 按 done 处理，
        // 已知的轻微误差（任务确实结束了，只是非正常结束）。
        return outcome;
      }
    }
  }

  watch(runningTasks, (now, prev) => {
    if (!prev) return;
    const nowKeys = new Set(now.map((t) => t.key));
    for (const t of prev) {
      if (nowKeys.has(t.key)) continue;
      eta.drop(t.key);
      recentFinished.value = recentFinished.value.filter((f) => f.key !== t.key);
      recentFinished.value.unshift({
        key: t.key,
        kind: t.kind,
        icon: t.icon,
        title: t.title,
        outcome: _outcomeFor(t),
        finishedAt: Date.now(),
        route: t.route,
      });
    }
    if (recentFinished.value.length > MAX_FINISHED) {
      recentFinished.value.splice(MAX_FINISHED);
    }
  });

  function clearFinished(): void {
    recentFinished.value = [];
  }

  // ── 取消分发（✕ 按钮，不弹确认框）────────────────────────────────
  async function cancelTask(task: TrayTask): Promise<void> {
    switch (task.kind) {
      case "monitor":
        await Promise.allSettled(
          (task.memberIds ?? []).map((id) => monitor.cancel(id)),
        );
        return;
      case "mining":
        await mining.cancelActive();
        return;
      case "batch":
        await batch.cancel();
        return;
      case "article":
        // PR2: await article.cancelJob();
        return;
    }
  }

  return {
    runningTasks,
    runningCount,
    recentFinished,
    monitorTaskMeta,
    ensureMonitorMeta,
    cancelTask,
    clearFinished,
  };
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/stores/__tests__/taskTray.spec.ts`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/taskTray.ts frontend/src/stores/__tests__/taskTray.spec.ts
git commit -m "feat(tray): taskTray 聚合 store（监测分组 + 任务名缓存）"
```

---

### Task 5: taskTray — 引流/批量/单篇卡片

**Files:**
- Modify: `frontend/src/stores/taskTray.ts`（Task 4 已一次写全则只补测试）
- Test: `frontend/src/stores/__tests__/taskTray.spec.ts`（追加 describe）

- [ ] **Step 1: 追加测试**

```ts
import { useMiningStore } from "@/stores/mining";
import { useBatch } from "@/stores/batch";
import { useArticle } from "@/stores/article";

describe("taskTray — 引流/批量/单篇卡片", () => {
  it("mining activeJob → 卡片：平台分项 subtitle + Σgot/Σtarget", async () => {
    const mining = useMiningStore();
    const tray = useTaskTray();
    mining.activeJob = {
      id: 3,
      keyword: "宠物吸尘器",
      platforms: ["kuaishou", "douyin"],
      target_per_platform: 50,
      status: "running",
      progress: {
        kuaishou: { got: 31, target: 50, phase: "fetching" },
        douyin: { got: 50, target: 50, phase: "done" },
      } as any,
      error_message: "",
      created_at: "",
      started_at: null,
      finished_at: null,
    };
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "mining")!;
    expect(card.title).toContain("宠物吸尘器");
    expect(card.subtitle).toContain("快手 31/50");
    expect(card.subtitle).toContain("抖音已完成");
    expect(card.progress).toBeCloseTo(81 / 100);
    expect(card.cancellable).toBe(true);
  });

  it("batch running → 第 i/N 篇 subtitle + progress getter", async () => {
    const batch = useBatch();
    const tray = useTaskTray();
    batch.$patch({
      status: "running",
      jobId: "u1",
      total: 5,
      items: [
        { index: 1, keyword: "a", status: "success", duration_seconds: 1, document: null, error_type: null, error_message: null },
        { index: 2, keyword: "b", status: "success", duration_seconds: 1, document: null, error_type: null, error_message: null },
        { index: 3, keyword: "c", status: "running", duration_seconds: 0, document: null, error_type: null, error_message: null },
        { index: 4, keyword: "d", status: "queued", duration_seconds: 0, document: null, error_type: null, error_message: null },
        { index: 5, keyword: "e", status: "queued", duration_seconds: 0, document: null, error_type: null, error_message: null },
      ],
    });
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "batch")!;
    expect(card.title).toBe("批量生成 · 5 篇");
    expect(card.subtitle).toContain("第 3/5 篇");
    expect(card.subtitle).toContain("c");
    expect(card.progress).toBeCloseTo(0.4);
  });

  it("article running → 阶段 subtitle，PR1 不可取消", async () => {
    const article = useArticle();
    const tray = useTaskTray();
    article.$patch({
      status: "running",
      jobId: "g1",
      title: "无线吸尘器",
      currentStage: "调用 LLM",
      stageIndex: 4,
    });
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "article")!;
    expect(card.title).toContain("无线吸尘器");
    expect(card.subtitle).toBe("调用 LLM（5/6）");
    expect(card.progress).toBeCloseTo(5 / 6);
    expect(card.cancellable).toBe(false);
  });

  it("runningCount = 监测底层任务数 + 其余卡各 1", async () => {
    const monitor = useMonitorStatus();
    const article = useArticle();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    article.$patch({ status: "running", jobId: "g1", title: "kw", currentStage: "导出", stageIndex: 5 });
    await flushPromises();
    await nextTick();
    expect(tray.runningCount).toBe(3);
  });
});
```

- [ ] **Step 2: 跑测试**

Run: `cd frontend && npx vitest run src/stores/__tests__/taskTray.spec.ts`
Expected: PASS（Task 4 已写全实现；若有红，修 taskTray.ts 直到绿）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/__tests__/taskTray.spec.ts
git commit -m "test(tray): 引流/批量/单篇卡片聚合用例"
```

---

### Task 6: taskTray — 取消分发 + 最近完成区

**Files:**
- Modify: `frontend/src/stores/taskTray.ts`（实现已在 Task 4 落盘，红则修）
- Test: `frontend/src/stores/__tests__/taskTray.spec.ts`（追加 describe）

- [ ] **Step 1: 追加测试**

```ts
describe("taskTray — 取消分发 + 最近完成", () => {
  it("监测组卡取消 → 对组内每个 id POST cancel", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    await flushPromises();
    await nextTick();
    const zhihu = tray.runningTasks.find((t) => t.kind === "monitor")!;
    await tray.cancelTask(zhihu);
    expect(postMock).toHaveBeenCalledWith("/api/monitor/tasks/11/cancel");
    expect(postMock).toHaveBeenCalledWith("/api/monitor/tasks/12/cancel");
  });

  it("mining 取消 → POST /api/mining/jobs/{id}/cancel", async () => {
    const mining = useMiningStore();
    const tray = useTaskTray();
    mining.activeJob = {
      id: 3, keyword: "k", platforms: ["douyin"], target_per_platform: 50,
      status: "running", progress: {} as any, error_message: "",
      created_at: "", started_at: null, finished_at: null,
    };
    await nextTick();
    await tray.cancelTask(tray.runningTasks.find((t) => t.kind === "mining")!);
    expect(postMock).toHaveBeenCalledWith("/api/mining/jobs/3/cancel");
  });

  it("任务从 running 消失 → 进最近完成区（mining completed → done）并上限 3 条", async () => {
    const mining = useMiningStore();
    const tray = useTaskTray();
    mining.activeJob = {
      id: 3, keyword: "k", platforms: ["douyin"], target_per_platform: 50,
      status: "running", progress: {} as any, error_message: "",
      created_at: "", started_at: null, finished_at: null,
    };
    await nextTick();
    expect(tray.runningTasks.length).toBe(1);

    mining.activeJob = { ...mining.activeJob!, status: "completed" };
    await nextTick();
    expect(tray.runningTasks.length).toBe(0);
    expect(tray.recentFinished.length).toBe(1);
    expect(tray.recentFinished[0].outcome).toBe("done");
    expect(tray.recentFinished[0].title).toContain("k");

    tray.clearFinished();
    expect(tray.recentFinished.length).toBe(0);
  });

  it("batch error → 最近完成 outcome=failed", async () => {
    const batch = useBatch();
    const tray = useTaskTray();
    batch.$patch({ status: "running", jobId: "u1", total: 1, items: [] });
    await nextTick();
    batch.$patch({ status: "error", error: "boom" });
    await nextTick();
    expect(tray.recentFinished[0]?.outcome).toBe("failed");
  });
});
```

- [ ] **Step 2: 跑测试**

Run: `cd frontend && npx vitest run src/stores/__tests__/taskTray.spec.ts`
Expected: PASS（全部 describe 绿）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/__tests__/taskTray.spec.ts
git commit -m "test(tray): 取消分发 + 最近完成区用例"
```

---

### Task 7: SSE 断线对账（subscribe onError + 引流/批量快照刷新）

**Files:**
- Modify: `frontend/src/api/client.ts:130-146`（subscribe 加可选 onError）
- Modify: `frontend/src/stores/mining.ts`（subscribeToJob 传 onError → 拉 `GET /api/mining/jobs/{id}`）
- Modify: `frontend/src/stores/batch.ts`（subscribe 传 onError → `refreshSnapshot()`）

监测已有 30s hydrate 兜底，不动。EventSource 自带断线重连，onError 只做一次轻量快照对账（错过的事件靠快照补），**不**主动 close。

- [ ] **Step 1: client.ts — subscribe 签名扩展**

```ts
export interface SSEOptions {
  /** EventSource onerror 时回调（连接会自动重连；用于触发一次快照对账）。 */
  onError?: () => void;
}

export function subscribe(
  path: string,
  handlers: SSEHandlers,
  opts: SSEOptions = {},
): () => void {
  const url = useSidecar().sseURL(path);
  const es = new EventSource(url);
  for (const [event, handler] of Object.entries(handlers)) {
    es.addEventListener(event, (e) => {
      const me = e as MessageEvent;
      let data: unknown = me.data;
      try {
        data = JSON.parse(me.data);
      } catch {
        /* leave as raw string */
      }
      handler(data);
    });
  }
  if (opts.onError) {
    es.onerror = () => opts.onError!();
  }
  return () => es.close();
}
```

- [ ] **Step 2: mining.ts — 断线快照对账**

`subscribeToJob` 末尾的 `subscribe(...)` 调用补第三参（在 handlers 对象之后）：

```ts
    }, {
      onError: () => { void _refreshActiveJobSnapshot() },
    })
```

并在 `cancelActive` 之前新增函数：

```ts
  /**
   * SSE 断线时的快照对账：拉一次 GET /api/mining/jobs/{id}（routes/mining.py
   * get_job 直接返回 job dict），把断线期间错过的 progress/status 补回来。
   * 任务已终态则顺手收掉流。
   */
  async function _refreshActiveJobSnapshot() {
    const job = activeJob.value
    if (!job) return
    try {
      const resp = await api().get<MiningJob>(`/api/mining/jobs/${job.id}`)
      const fresh = resp.data
      if (!fresh || typeof fresh.id !== "number") return
      activeJob.value = fresh
      _patchJobInList(fresh.id, () => fresh)
      if (!["pending", "running"].includes(fresh.status) && stopSse) {
        stopSse()
        stopSse = null
      }
    } catch {
      /* 瞬时网络问题 —— EventSource 自己会重连，下次事件兜底 */
    }
  }
```

- [ ] **Step 3: batch.ts — 断线快照对账**

`submit` 里 `this.stop = subscribe(...)` 调用补第三参：

```ts
      }, {
        onError: () => { void this.refreshSnapshot(); },
      });
```

- [ ] **Step 4: 类型回归**

Run: `cd frontend && npx vitest run src/stores/__tests__/taskTray.spec.ts src/stores/__tests__/monitorStatus.spec.ts`
Expected: PASS（subscribe mock 兼容新第三参——mock 是 `vi.fn(() => () => {})`，多收一个参数无影响）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/stores/mining.ts frontend/src/stores/batch.ts
git commit -m "feat(tray): SSE 断线快照对账（subscribe onError + mining/batch 对账）"
```

---

### Task 8: TaskTrayPanel.vue 浮层

**Files:**
- Create: `frontend/src/components/ui/TaskTrayPanel.vue`
- Test: `frontend/src/components/ui/__tests__/TaskTrayPanel.spec.ts`

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/components/ui/__tests__/TaskTrayPanel.spec.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("@/composables/useSystemNotify", () => ({
  useSystemNotify: () => ({ notify: vi.fn().mockResolvedValue(undefined) }),
}));
vi.mock("@/api/client", () => ({ subscribe: vi.fn(() => () => {}) }));
vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined) }),
}));

import TaskTrayPanel from "@/components/ui/TaskTrayPanel.vue";
import { useMonitorStatus } from "@/stores/monitorStatus";

describe("TaskTrayPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    getMock.mockReset().mockResolvedValue({ data: { tasks: [] } });
    postMock.mockReset().mockResolvedValue({ data: {} });
  });

  it("open=false 不渲染", () => {
    const w = mount(TaskTrayPanel, { props: { open: false } });
    expect(w.find("div").exists()).toBe(false);
  });

  it("空态显示「暂无后台任务」+ footer 文案", () => {
    const w = mount(TaskTrayPanel, { props: { open: true } });
    expect(w.text()).toContain("暂无后台任务");
    expect(w.text()).toContain("切到任何页面任务都继续跑");
  });

  it("有任务时渲染卡片 + 计数 + 取消按钮", async () => {
    const monitor = useMonitorStatus();
    monitor.markRunning(99);
    const w = mount(TaskTrayPanel, { props: { open: true } });
    await flushPromises();
    expect(w.text()).toContain("后台任务");
    expect(w.text()).toContain("任务 #99");
    expect(w.find("button[title='停止任务']").exists()).toBe(true);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/ui/__tests__/TaskTrayPanel.spec.ts`
Expected: FAIL —— 找不到组件

- [ ] **Step 3: 实现组件**

```vue
<!-- frontend/src/components/ui/TaskTrayPanel.vue -->
<script setup lang="ts">
/**
 * 全局任务托盘浮层 —— 定位/视觉范式复刻 NotificationDropdown（侧栏底部
 * 锚定、向 nav 右侧弹出、不 Teleport）。数据全部来自 useTaskTray()，
 * 本组件零拉取、零 SSE。
 */
import { useRouter } from "vue-router";

import Icon from "./Icon.vue";
import ProgressBar from "./ProgressBar.vue";
import { useToast } from "@/composables/useToast";
import { useTaskTray, type TrayFinished, type TrayTask } from "@/stores/taskTray";

defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "close"): void }>();

const router = useRouter();
const tray = useTaskTray();
const toast = useToast();

function gotoTask(t: TrayTask | TrayFinished) {
  emit("close");
  router.push(t.route).catch(() => {});
}

async function onCancel(t: TrayTask) {
  try {
    await tray.cancelTask(t);
    toast.info(`已请求停止 ${t.title}`);
  } catch {
    toast.error("取消失败，请稍后重试");
  }
}

function pct(p: number | null): string {
  return p == null ? "" : `${Math.round(p * 100)}%`;
}

function metaText(t: TrayTask): string {
  if (t.state === "waiting") return "排队中";
  return [pct(t.progress), t.etaText].filter(Boolean).join(" · ");
}

function outcomeMeta(o: TrayFinished["outcome"]): { icon: string; color: string; label: string } {
  if (o === "done") return { icon: "check", color: "var(--green)", label: "已完成" };
  if (o === "cancelled") return { icon: "x", color: "var(--ink-3)", label: "已取消" };
  return { icon: "alert", color: "var(--red)", label: "失败" };
}
</script>

<template>
  <div
    v-if="open"
    class="absolute z-50"
    :style="{
      bottom: '0',
      left: '52px',
      width: '340px',
      maxHeight: '480px',
      background: 'var(--bg-inner)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-card)',
      boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
    }"
    @click.stop
  >
    <!-- Header -->
    <div
      class="flex items-center justify-between px-4"
      :style="{ height: '40px', borderBottom: '1px solid var(--line)' }"
    >
      <div class="font-display text-[13px] font-semibold">
        后台任务<span v-if="tray.runningCount > 0" :style="{ color: 'var(--ink-3)' }">
          · {{ tray.runningCount }}</span>
      </div>
      <button
        v-if="tray.recentFinished.length > 0"
        type="button"
        class="hover:underline text-[11.5px]"
        :style="{ color: 'var(--ink-3)' }"
        @click="tray.clearFinished()"
      >
        清除已完成
      </button>
    </div>

    <!-- Body -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-if="tray.runningTasks.length === 0 && tray.recentFinished.length === 0"
        class="flex flex-col items-center justify-center py-10 text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        <Icon name="zap" :size="22" />
        <div class="mt-2">暂无后台任务</div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          监测 / 引流 / 生成任务运行时会出现在这里
        </div>
      </div>

      <ul v-else class="flex flex-col">
        <!-- 运行中 -->
        <li
          v-for="t in tray.runningTasks"
          :key="t.key"
          class="px-4 py-3 hover:bg-[rgba(28,26,23,0.04)]"
          :style="{ borderBottom: '1px solid var(--line)' }"
        >
          <div class="flex items-start gap-2.5">
            <span
              class="mt-0.5 flex-shrink-0"
              :style="{ color: t.state === 'captcha' ? 'var(--red)' : 'var(--primary)' }"
            >
              <Icon :name="t.icon" :size="15" />
            </span>
            <div class="min-w-0 flex-1 cursor-pointer" @click="gotoTask(t)">
              <div class="truncate text-[12.5px] font-medium leading-tight">{{ t.title }}</div>
              <div
                class="mt-0.5 truncate text-[11.5px]"
                :style="{ color: t.state === 'captcha' ? 'var(--red)' : 'var(--ink-3)' }"
              >
                {{ t.subtitle }}
              </div>
            </div>
            <button
              v-if="t.cancellable"
              type="button"
              title="停止任务"
              class="tray-cancel inline-flex flex-shrink-0 items-center justify-center"
              @click.stop="onCancel(t)"
            >
              <Icon name="x" :size="13" />
            </button>
          </div>
          <div class="mt-2 flex items-center gap-2">
            <div class="flex-1">
              <ProgressBar
                :value="t.state === 'waiting' ? 0 : t.progress"
                :height="5"
                :tone="t.state === 'captcha' ? 'red' : 'primary'"
              />
            </div>
            <div class="flex-shrink-0 text-[10.5px]" :style="{ color: 'var(--ink-4)' }">
              {{ metaText(t) }}
            </div>
          </div>
        </li>

        <!-- 最近完成 -->
        <li
          v-if="tray.recentFinished.length > 0"
          class="px-4 pb-1 pt-2.5 text-[10.5px]"
          :style="{ color: 'var(--ink-4)' }"
        >
          最近完成
        </li>
        <li
          v-for="f in tray.recentFinished"
          :key="`fin-${f.key}-${f.finishedAt}`"
          class="flex cursor-pointer items-center gap-2.5 px-4 py-2.5 hover:bg-[rgba(28,26,23,0.04)]"
          :style="{ borderBottom: '1px solid var(--line)', opacity: 0.75 }"
          @click="gotoTask(f)"
        >
          <span class="flex-shrink-0" :style="{ color: outcomeMeta(f.outcome).color }">
            <Icon :name="outcomeMeta(f.outcome).icon" :size="14" />
          </span>
          <div class="min-w-0 flex-1 truncate text-[12px]">{{ f.title }}</div>
          <div class="flex-shrink-0 text-[10.5px]" :style="{ color: 'var(--ink-4)' }">
            {{ outcomeMeta(f.outcome).label }}
          </div>
        </li>
      </ul>
    </div>

    <!-- Footer -->
    <div
      class="flex items-center justify-center text-[10.5px]"
      :style="{ height: '32px', borderTop: '1px solid var(--line)', color: 'var(--ink-4)' }"
    >
      切到任何页面任务都继续跑 · 完成后通知
    </div>
  </div>
</template>

<style scoped>
/* 可被 hover 改的属性必须放 scoped CSS（inline style 会压死 :hover）。 */
.tray-cancel {
  width: 22px;
  height: 22px;
  border-radius: 8px;
  color: var(--ink-3);
  transition: background 0.15s ease, color 0.15s ease;
}
.tray-cancel:hover {
  background: rgba(28, 26, 23, 0.06);
  color: var(--red);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/ui/__tests__/TaskTrayPanel.spec.ts`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/TaskTrayPanel.vue frontend/src/components/ui/__tests__/TaskTrayPanel.spec.ts
git commit -m "feat(tray): TaskTrayPanel 浮层（运行中 + 最近完成 + 取消）"
```

---

### Task 9: LeftNav 集成 + PR1 收尾

**Files:**
- Modify: `frontend/src/components/LeftNav.vue`

- [ ] **Step 1: script 部分改动**

imports 加：

```ts
import TaskTrayPanel from "./ui/TaskTrayPanel.vue";
import { useTaskTray } from "@/stores/taskTray";
```

把现有的 `const notify = useNotifications(); ... function toggleNotif() {...}` 整块替换为下面这段（refs 先声明、函数后定义，托盘与铃铛互斥）：

```ts
// 通知铃铛 + 任务托盘：两个浮层互斥（同时只开一个）。
// 任务托盘挂在 LeftNav（常驻组件）上，让 useTaskTray() 的 watcher
// （最近完成登记、元数据懒加载）从 app 启动起就活着，而不是等浮层首开。
const notify = useNotifications();
const tray = useTaskTray();
const notifOpen = ref(false);
const trayOpen = ref(false);

// 通知铃铛：点击 toggle 下拉面板。打开瞬间标全部已读 ——
// "打开 = 看过" 比强迫逐条点合理。
function toggleNotif() {
  notifOpen.value = !notifOpen.value;
  if (notifOpen.value) {
    trayOpen.value = false;
    notify.markAllRead();
  }
}

function toggleTray() {
  trayOpen.value = !trayOpen.value;
  if (trayOpen.value) {
    notifOpen.value = false;
    void tray.ensureMonitorMeta(true); // 打开时强刷一次任务名缓存
  }
}

const trayBadge = computed(() =>
  tray.runningCount > 9 ? "9+" : String(tray.runningCount),
);
```

- [ ] **Step 2: template 改动 —— 通知 bell 的 `<div class="relative">` 之前插入**

```vue
      <!--
        任务托盘按钮 —— 铃铛正上方。有任务时数字角标 + 呼吸光圈；
        浮层从 nav 右侧弹出（同 NotificationDropdown 范式）。
      -->
      <div class="relative">
        <button
          title="后台任务"
          type="button"
          class="relative inline-flex items-center justify-center transition"
          :class="{ 'tray-btn-active': tray.runningCount > 0 }"
          :style="{
            width: '44px',
            height: '44px',
            borderRadius: '14px',
            color: tray.runningCount > 0 ? 'var(--primary)' : 'var(--ink-2)',
            background: trayOpen ? 'rgba(28,26,23,0.05)' : 'transparent',
          }"
          @mouseenter="(e) => { if (!trayOpen) (e.currentTarget as HTMLElement).style.background = 'rgba(28,26,23,0.05)' }"
          @mouseleave="(e) => { if (!trayOpen) (e.currentTarget as HTMLElement).style.background = 'transparent' }"
          @click="toggleTray"
        >
          <Icon name="zap" :size="18" />
          <span v-if="tray.runningCount > 0" class="tray-badge absolute">{{ trayBadge }}</span>
        </button>
        <TaskTrayPanel :open="trayOpen" @close="trayOpen = false" />
      </div>
```

- [ ] **Step 3: 文件尾部新增 scoped 样式块（LeftNav 目前没有 style 块；角标定位与呼吸动效都是会变化/动画属性，放 scoped CSS）**

```vue
<style scoped>
.tray-badge {
  top: 5px;
  right: 5px;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 9.5px;
  font-weight: 700;
  line-height: 15px;
  text-align: center;
  box-shadow: 0 0 0 2px var(--bg-inner);
}
@keyframes trayPulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(238, 106, 42, 0.35);
  }
  50% {
    box-shadow: 0 0 0 7px rgba(238, 106, 42, 0);
  }
}
.tray-btn-active {
  animation: trayPulse 2.2s ease-in-out infinite;
}
</style>
```

- [ ] **Step 4: 全量回归 + 类型检查**

```powershell
cd frontend
npx vitest run
npx vue-tsc -b
git status   # vue-tsc 会 emit vite.config.js / *.d.ts
git checkout -- vite.config.js
# 若 git status 还有其它 vue-tsc emit 出来的 .d.ts/.js，一并 checkout 还原
```
Expected: vitest 全绿；vue-tsc 无错误。

- [ ] **Step 5: Commit + 提 PR1**

```bash
git add frontend/src/components/LeftNav.vue
git commit -m "feat(tray): 侧栏任务托盘入口（数字角标 + 呼吸动效 + 与铃铛互斥）"
git push -u origin claude/sharp-chatterjee-e2792c
gh pr create --title "feat(tray): 全局任务托盘（侧栏常驻入口 + 浮层 + 完成通知）" --body "spec: docs/superpowers/specs/2026-06-10-global-task-tray-design.md（PR1：纯前端聚合 + 通知补齐；PR2 单篇取消端点另提）"
```

返回 PR URL 给用户，停在 pending 等网页 merge（不要本地 merge）。

---

### Task 10（PR2）: 单篇生成协作式取消 — sidecar

**前置：PR1 已 merge；从最新 main 开新分支（或经用户同意叠加在原分支）。**

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py`
- Modify: `sidecar/csm_sidecar/routes/generate.py`
- Test: `sidecar/tests/test_generate_cancel.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# sidecar/tests/test_generate_cancel.py
"""Cooperative-cancel wiring for /api/generate jobs.

完整 happy-path（真 vault + LLM）太重；这里测线路：
request_cancel 的 live 语义、checkpoint 抛取消、路由返回值。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from csm_sidecar.services import generate_service


@pytest.fixture(autouse=True)
def _clean_cancel_state():
    yield
    with generate_service._state_lock:
        generate_service._live.clear()
        generate_service._cancelled.clear()


def test_cancel_unknown_job_returns_ok_false(client: TestClient):
    resp = client.post("/api/generate/no-such-job/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "no-such-job", "ok": False}


def test_request_cancel_lifecycle():
    jid = "job-under-test"
    assert generate_service.request_cancel(jid) is False  # not live
    with generate_service._state_lock:
        generate_service._live.add(jid)
    assert generate_service.request_cancel(jid) is True   # newly marked
    assert generate_service.request_cancel(jid) is False  # already marked


def test_checkpoint_raises_only_when_cancelled():
    jid = "job-checkpoint"
    with generate_service._state_lock:
        generate_service._live.add(jid)
    generate_service._checkpoint(jid)  # 未取消 → 不抛
    generate_service.request_cancel(jid)
    with pytest.raises(generate_service._CancelledGenerate):
        generate_service._checkpoint(jid)
```

- [ ] **Step 2: 跑测试确认失败**

Run:（PYTHONPATH 见「环境准备」）`cd sidecar && python -m pytest tests/test_generate_cancel.py -v`
Expected: FAIL —— `AttributeError: ... has no attribute '_state_lock'`

- [ ] **Step 3: 实现 generate_service.py**

3a. `_executor` / `_lock` 声明之后新增：

```python
# ── 协作式取消 ───────────────────────────────────────────────────────
# request_cancel 只对仍在 _live 里的 job 生效；_run_job 在各 stage 检查点
# （含调用 LLM 前）调 _checkpoint，命中则以 error 事件收尾（EventBus 只认
# done/error 终结流），payload 带 cancelled=True 让前端静默处理。
# LLM 调用本身不可中断；「导出」阶段不设检查点 —— LLM 已经花了钱，
# 落盘比丢弃好。与 batch/monitor 的协作式语义一致。
_live: set[str] = set()
_cancelled: set[str] = set()
_state_lock = threading.Lock()


class _CancelledGenerate(Exception):
    """Raised at a checkpoint when the user requested cancel."""


def request_cancel(job_id: str) -> bool:
    """Return True if the job is live and was newly marked for cancel."""
    with _state_lock:
        if job_id not in _live or job_id in _cancelled:
            return False
        _cancelled.add(job_id)
    bus.publish(job_id, "cancel_requested")
    return True


def _checkpoint(job_id: str) -> None:
    with _state_lock:
        hit = job_id in _cancelled
    if hit:
        raise _CancelledGenerate()
```

3b. `submit()` 改为：

```python
def submit(req: GenerateRequest) -> str:
    """Kick off a job, return the ``job_id`` to subscribe via SSE."""
    job_id = bus.create_job()
    with _state_lock:
        _live.add(job_id)
    _get_executor().submit(_run_job, job_id, req)
    return job_id
```

3c. `_run_job()`：在以下 5 处 `bus.publish(job_id, "stage", ...)` 语句**之前**各插入一行 `_checkpoint(job_id)`：扫描资料库（index=0）、加载模板（index=1）、采样 blocks（index=2）、组装 prompt（index=3）、调用 LLM（index=4）。「导出」（index=5）前**不**插。

末尾 except/finally 改为：

```python
    except _CancelledGenerate:
        logger.info("generate job %s cancelled by user", job_id)
        bus.fail(job_id, error="cancelled", cancelled=True)
    except Exception as e:
        logger.exception("generate job %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    finally:
        with _state_lock:
            _live.discard(job_id)
            _cancelled.discard(job_id)
```

- [ ] **Step 4: 实现 routes/generate.py —— 文件末尾追加**

```python
@router.post("/api/generate/{job_id}/cancel")
def cancel_generate(job_id: str) -> dict:
    """Cooperatively cancel a running generate job.

    Already-finished / unknown job is a no-op (``ok=False``). The job
    terminates via an ``error`` SSE event carrying ``cancelled: true``.
    """
    ok = generate_service.request_cancel(job_id)
    return {"job_id": job_id, "ok": ok}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd sidecar && python -m pytest tests/test_generate_cancel.py tests/test_generate_routes.py -v`
Expected: PASS（新 3 条 + 原 4 条都绿）

- [ ] **Step 6: Commit**

```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/csm_sidecar/routes/generate.py sidecar/tests/test_generate_cancel.py
git commit -m "feat(generate): 单篇生成协作式取消端点 POST /api/generate/{job_id}/cancel"
```

---

### Task 11（PR2）: article store cancelJob + 托盘接通 + PR2 收尾

**Files:**
- Modify: `frontend/src/stores/article.ts`
- Modify: `frontend/src/stores/taskTray.ts`
- Test: `frontend/src/stores/__tests__/taskTray.spec.ts`（追加）

- [ ] **Step 1: 追加失败测试**

```ts
describe("taskTray — 单篇取消（PR2）", () => {
  it("article 卡 cancellable=true 且取消调 /api/generate/{id}/cancel", async () => {
    const article = useArticle();
    const tray = useTaskTray();
    article.$patch({
      status: "running", jobId: "g1", title: "kw",
      currentStage: "调用 LLM", stageIndex: 4,
    });
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "article")!;
    expect(card.cancellable).toBe(true);
    await tray.cancelTask(card);
    expect(postMock).toHaveBeenCalledWith("/api/generate/g1/cancel");
  });
});
```

同时把 Task 5 中 article 用例的 `expect(card.cancellable).toBe(false);` 改为 `toBe(true)`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/taskTray.spec.ts`
Expected: FAIL —— cancellable 仍为 false

- [ ] **Step 3: 实现**

3a. `article.ts` 的 `cancel()` action 之后新增：

```ts
    /** 请求后端协作式取消（POST /api/generate/{id}/cancel）。
     * 后端命中检查点后会推 error 事件（cancelled: true），由 SSE handler
     * 静默回 idle；这里不直接动 status，避免和事件流赛跑。
     * 已结束 / 未知 job 的 404、409 静默吞掉。 */
    async cancelJob(): Promise<void> {
      if (!this.jobId) {
        this.cancel();
        return;
      }
      const sidecar = useSidecar();
      try {
        await sidecar.client.post(`/api/generate/${this.jobId}/cancel`);
      } catch {
        /* job 已经结束 —— 事件流自会收尾 */
      }
    },
```

3b. `taskTray.ts`：articleCard 的 `cancellable: false, // PR2 ...` 改为 `cancellable: true,`；`cancelTask` 的 article 分支改为：

```ts
      case "article":
        await article.cancelJob();
        return;
```

- [ ] **Step 4: 跑全量测试 + 类型检查**

```powershell
cd frontend
npx vitest run
npx vue-tsc -b
git checkout -- vite.config.js
```
Expected: 全绿。

- [ ] **Step 5: Commit + 提 PR2**

```bash
git add frontend/src/stores/article.ts frontend/src/stores/taskTray.ts frontend/src/stores/__tests__/taskTray.spec.ts
git commit -m "feat(tray): 单篇生成接通托盘取消（cancelJob + cancellable）"
git push -u origin <pr2-branch>
gh pr create --title "feat(generate): 单篇生成取消端点 + 托盘接通" --body "spec: docs/superpowers/specs/2026-06-10-global-task-tray-design.md（PR2）"
```

---

## 真机验收（PR merge 后，对照 spec §10）

dev 服务由用户自行启动（agent 起的 GUI 进程树会被回收——见既有教训），或打包后验证：

1. 任意页面发起监测 run-now / 引流 / 批量 / 单篇 → 侧栏 zap 按钮 3s 内出现角标 + 呼吸动效；切路由持续更新。
2. 浮层进度与任务页内一致；百度原生模式等浏览器时显示「排队中 · 等待浏览器空闲」。
3. 浮层取消 → 5s 内移入「最近完成」标 ✗/已取消，任务页状态同步。
4. 完成后铃铛出现对应类别通知；在通知设置关掉「引流任务完成」后不再推。
5. 杀掉 sidecar 进程 → 30s 内托盘清空。

## Self-review 记录

- spec §4.1「按 type 分组」在实现中细化为「按显示组分组」（三个 *_comment type 合并为一张「评论留存监测」卡）——已在 MONITOR_TYPE_META 注释与 spec 修订说明。
- spec §5.1 的 `TaskTrayButton` 独立组件在实现中按 LeftNav 铃铛先例**内联**进 LeftNav.vue（44×44 按钮本体 ~20 行，单抽组件反而要把 trayOpen/互斥状态来回传）；浮层 TaskTrayPanel 仍是独立组件。
- spec §6 的「监测/批量通知已有」勘误为「铃铛零调用方，本计划全量补齐」——见计划头部勘误段，spec 已同步修订。
- ETA / 取消不弹确认框 / 最近完成上限 3 条等口径与 spec §4.2-4.4 一致。
