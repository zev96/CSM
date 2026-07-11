/**
 * MonitorStatus — single source of truth for "which monitor tasks are
 * currently running" across the whole app.
 *
 * Why a store and not per-page state:
 *   - SSE subscription is bound to a component lifecycle. When the user
 *     navigates away from BaiduRankingPage / MonitorView, the component
 *     unmounts → SSE disconnects → `started` events fired while it was
 *     unmounted are lost. When the user comes back the local
 *     `runningTaskIds` Set is empty even though a worker thread is still
 *     scraping in the sidecar. Result: the «立刻监测» button enables and
 *     a second dispatch races the first one (or just shows wrong state).
 *
 *   - This store subscribes to SSE once at app boot and holds state for
 *     the app lifetime. It also hydrates from GET /api/monitor/running
 *     on start + every 30 s as a safety net (catches sidecar restarts).
 *
 *   - Components read `isRunning(id)` / `progress(id)` from the store
 *     instead of maintaining their own copy. They still subscribe to SSE
 *     for *page-specific* reactions (e.g. reload history on `finished`).
 *
 * Cancellation: POST /api/monitor/tasks/{id}/cancel. Backend signals
 * the worker via `threading.Event`; baidu adapter polls it between
 * keywords. Other adapters ignore it (single-shot fetches that can't be
 * interrupted cleanly).
 */
import { defineStore } from "pinia";
import { ref } from "vue";

import { subscribe } from "@/api/client";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { useSystemNotify } from "@/composables/useSystemNotify";
import { useNotifications } from "@/composables/useNotifications";

interface ProgressEntry {
  current: number;
  total: number;
}

export type MonitorTaskPhase = "waiting_chrome" | "captcha";

// Module-level notify singleton — store is created once per app lifetime,
// so this is effectively module-level. Must be called inside the store
// factory (after Pinia is active) to satisfy Tauri plugin constraints.
let _notify: ((title: string, body: string) => Promise<void>) | null = null;

// Grace window for the markRunning → backend-enroll race.
//
// `run_task_now` POST returns 200 the moment the task is submitted to the
// sidecar's ThreadPoolExecutor, but the worker thread may sit in the
// platform slot semaphore for up to 120 s before publishing `started`
// and calling `_track_active`. If the user navigates away and back
// during that window, BaiduRankingPage's onMounted triggers
// `hydrate()` → GET /api/monitor/running → empty Set → clobbers the
// optimistic mark. The backend now pre-registers in run_task_now (so
// /running is honest), but we keep this client-side grace as
// defense-in-depth in case the optimistic mark beats the POST round-trip.
const _OPTIMISTIC_GRACE_MS = 5000;
const _optimisticMarkedAt = new Map<number, number>();

export const useMonitorStatus = defineStore("monitorStatus", () => {
  const runningTaskIds = ref<Set<number>>(new Set());
  const taskProgress = ref<Record<number, ProgressEntry>>({});
  // 任务特殊阶段（百度原生 Chrome：排队等浏览器空闲 / 等人工验证码）。
  // 由 waiting_chrome_close / captcha_* SSE 事件驱动；started/finished/
  // failed/hydrate 时清理。托盘用它区分「排队中/需人工验证」与真「运行中」。
  const taskPhase = ref<Record<number, MonitorTaskPhase>>({});
  // 最近一次终态 —— 托盘「最近完成」区推断 ✓/✗ 用。只增不删（数量级 = 任务数）。
  const lastOutcomes = ref<Record<number, "done" | "failed" | "cancelled">>({});
  const toast = useToast();
  const bell = useNotifications();
  // Lazy-initialise the notify singleton the first time the store is created.
  if (!_notify) {
    const { notify } = useSystemNotify();
    _notify = notify;
  }
  // Bumped after any task create / update / batch-import to fan out "go
  // reload your tasks list" signals across mounted monitor pages without
  // relying on template ref chains. BaiduRankingPage / MonitorView watch
  // this nonce in setup. The original baiduPageRef.value?.reload?.()
  // path silently no-ops if the ref hasn't been wired by the time a
  // batch-import emit fires (HMR re-mount race, or modal lifecycle
  // ordering), which is why batch-import wasn't refreshing the baidu
  // tab even though @imported was bound. Nonce-based fanout doesn't
  // care about ref order.
  const taskMutationNonce = ref(0);
  function bumpTaskMutation(): void {
    taskMutationNonce.value += 1;
  }

  // Internal singletons — store is created once per app, so these are
  // effectively module-level.
  let stopSse: (() => void) | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let started = false;

  function isRunning(taskId: number): boolean {
    return runningTaskIds.value.has(taskId);
  }

  function progressOf(taskId: number): ProgressEntry | null {
    return taskProgress.value[taskId] ?? null;
  }

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

  function markRunning(taskId: number): void {
    // Stamp the optimistic-mark time so hydrate() can ride out the race
    // where /api/monitor/running hasn't enrolled this task yet (slot
    // wait / executor queue). Always update — even if already running —
    // so a re-dispatched task gets a fresh grace window.
    _optimisticMarkedAt.set(taskId, Date.now());
    if (runningTaskIds.value.has(taskId)) return;
    const s = new Set(runningTaskIds.value);
    s.add(taskId);
    runningTaskIds.value = s;
  }

  function clearRunning(taskId: number): void {
    _setPhase(taskId, null);
    // Clear the optimistic ledger entry regardless of whether the task
    // was in runningTaskIds — callers that clear after a failed POST
    // need this too.
    _optimisticMarkedAt.delete(taskId);
    if (!runningTaskIds.value.has(taskId)) {
      // Even if not in the set, drop any stale progress entry.
      if (taskId in taskProgress.value) {
        const next = { ...taskProgress.value };
        delete next[taskId];
        taskProgress.value = next;
      }
      return;
    }
    const s = new Set(runningTaskIds.value);
    s.delete(taskId);
    runningTaskIds.value = s;
    if (taskId in taskProgress.value) {
      const next = { ...taskProgress.value };
      delete next[taskId];
      taskProgress.value = next;
    }
  }

  function setProgress(taskId: number, current: number, total: number): void {
    if (total <= 0) return;
    taskProgress.value = {
      ...taskProgress.value,
      [taskId]: { current, total },
    };
    // Defensive: progress implies running. If `started` event was lost
    // (e.g. SSE reconnect race), this is how we recover.
    markRunning(taskId);
  }

  /**
   * Pull the truth from /api/monitor/running and reconcile. Tasks that
   * the backend reports running but the store doesn't know about are
   * added; tasks the store thinks are running but aren't actually
   * (sidecar restarted, task finished while page was gone) are cleared.
   */
  async function hydrate(): Promise<void> {
    const sidecar = useSidecar();
    const { whenReady } = useSidecarReady();
    try {
      await whenReady();
      const r = await sidecar.client.get("/api/monitor/running");
      const ids: number[] = Array.isArray(r.data?.running_task_ids)
        ? r.data.running_task_ids
        : [];
      const backendSet = new Set(ids);
      // Merge instead of overwrite: tasks the user just optimistically
      // marked (within _OPTIMISTIC_GRACE_MS) but the backend hasn't
      // enrolled in /running yet should survive this hydrate. Without
      // this, navigating away+back right after clicking 立刻监测 would
      // clobber the optimistic mark.
      const now = Date.now();
      const next = new Set<number>(backendSet);
      for (const id of runningTaskIds.value) {
        if (backendSet.has(id)) continue;
        const at = _optimisticMarkedAt.get(id);
        if (at !== undefined && now - at < _OPTIMISTIC_GRACE_MS) next.add(id);
      }
      runningTaskIds.value = next;
      // Prune optimistic timestamps: backend confirmed OR grace expired.
      // The expired ones get dropped from runningTaskIds above as a
      // side-effect (they're not added to `next`), so this is just
      // ledger maintenance.
      for (const id of Array.from(_optimisticMarkedAt.keys())) {
        const at = _optimisticMarkedAt.get(id);
        if (backendSet.has(id) || at === undefined || now - at >= _OPTIMISTIC_GRACE_MS) {
          _optimisticMarkedAt.delete(id);
        }
      }
      // Drop progress entries for tasks no longer running per the merged set
      const nextProgress: Record<number, ProgressEntry> = {};
      for (const [k, v] of Object.entries(taskProgress.value)) {
        const numK = Number(k);
        if (next.has(numK)) nextProgress[numK] = v;
      }
      taskProgress.value = nextProgress;
      const nextPhase: Record<number, MonitorTaskPhase> = {};
      for (const [k, v] of Object.entries(taskPhase.value)) {
        const numK = Number(k);
        if (next.has(numK)) nextPhase[numK] = v;
      }
      taskPhase.value = nextPhase;
    } catch {
      // Silently ignore — caller will retry on next poll.
    }
  }

  /**
   * Ask the sidecar to cancel a running task. Cooperative — the worker
   * checks its cancel flag at the next checkpoint (e.g. between
   * keywords for baidu). The SSE `failed` event clears local state.
   *
   * Returns the backend's `cancelled` flag: true if the signal was
   * delivered to a live worker, false otherwise (task wasn't running).
   */
  async function cancel(taskId: number): Promise<boolean> {
    const sidecar = useSidecar();
    const { whenReady } = useSidecarReady();
    try {
      await whenReady();
      const r = await sidecar.client.post(
        `/api/monitor/tasks/${taskId}/cancel`,
      );
      return Boolean(r.data?.cancelled);
    } catch {
      return false;
    }
  }

  // SSE 处理表 —— 提取成命名对象让单测能经 _dispatchSse 直接驱动，
  // 不需要真 EventSource。start() 把同一张表绑给 subscribe。
  const _sseHandlers: Record<string, (d: any) => void> = {
    started: (d: any) => {
      if (typeof d.task_id === "number" && d.task_id > 0) {
        markRunning(d.task_id);
        _setPhase(d.task_id, null); // 新增：真正开跑，清掉排队/验证码态
        // Backend has now confirmed the task is running; the optimistic
        // grace window is no longer needed.
        _optimisticMarkedAt.delete(d.task_id);
        // 重跑会产生新一轮终态 —— 把上一轮的记录清掉，避免 hydrate 兜底
        // 清场时托盘把旧 outcome 错按到新一轮头上。
        if (d.task_id in lastOutcomes.value) {
          const next = { ...lastOutcomes.value };
          delete next[d.task_id];
          lastOutcomes.value = next;
        }
      }
    },
    progress: (d: any) => {
      if (typeof d.task_id !== "number") return;
      const cur = typeof d.progress_current === "number" ? d.progress_current : 0;
      const tot = typeof d.progress_total === "number" ? d.progress_total : 0;
      setProgress(d.task_id, cur, tot);
      // progress = 正在抓取 —— 清掉可能因丢事件卡住的排队/验证码 phase（恢复路径：
      // 两种等待场景都不发 progress，所以不存在误清窗口）。
      _setPhase(d.task_id, null);
    },
    // ── Native-Chrome mode events ──────────────────────────────────
    needs_captcha: (d: any) => {
      // 真任务验证码事件。task_id=0 从来不是任务验证码（历史上登录窗口
      // 曾借用此事件 → 弹「需要人工解验证码（副本登录态已保存）」的错误提示，
      // 现已改用专用 baidu_login_saved 事件）。三连通知必须整体 gate 在
      // task_id>0，否则任何 task_id=0 事件都会误弹验证码通知。
      if (!(typeof d.task_id === "number" && d.task_id > 0)) return;
      _setPhase(d.task_id, "captcha");
      const kw = typeof d.keyword === "string" ? d.keyword : "";
      // ① 系统桌面通知
      void _notify?.("CSM 百度监控", `需要人工解验证码（关键词：${kw}），浏览器已弹出`);
      // ② app 内醒目提醒（sticky，等用户处理；toast 已在 store init）
      toast.warn(`需要人工解验证码（${kw}）—— 浏览器已弹到屏幕中央，请去操作`, { ttl: 0 });
      // ③ 任务栏闪 + 尽力前置 app（best-effort，非 Tauri 环境静默跳过）
      void import("@tauri-apps/api/core")
        .then(({ invoke }) => invoke("request_window_attention"))
        .catch(() => {});
    },
    // 副本登录窗口关闭后的专用完成信号（task_id 恒 0）。error 为空=BDUSS
    // 已落盘登录成功；有值=没检测到登录态。绝不弹验证码通知。
    baidu_login_saved: (d: any) => {
      const errMsg = typeof d.error === "string" ? d.error : "";
      if (errMsg) {
        toast.warn(`副本登录未完成：${errMsg}`, { ttl: 0 });
        bell.push("副本登录未完成", {
          body: errMsg,
          tone: "warn",
          category: "system",
        });
      } else {
        toast.success("副本登录态已保存，可以开始百度监测了");
        bell.push("副本登录态已保存", {
          body: "已检测到百度登录 Cookie，副本可用于监测",
          tone: "success",
          category: "system",
        });
      }
      // 通知设置页刷新「上次登录」显示（解耦：设置页 addEventListener）。
      try {
        window.dispatchEvent(
          new CustomEvent("csm:baidu-login-saved", { detail: { ok: !errMsg } }),
        );
      } catch {
        /* 非浏览器环境静默 */
      }
    },
    risk_control: (d: any) => {
      // 风控中断：任务已在后端存了断点（last_resumed_keyword）。之前前端
      // 没有这个处理器 → failed 处理器又特意「留给 risk_control 事件处理」→
      // 整个风控中断全程静默、任务卡在「监测中」。这里补上：停 running +
      // 明确通知用户可从断点续跑。
      if (typeof d.task_id !== "number") return;
      clearRunning(d.task_id);
      lastOutcomes.value = { ...lastOutcomes.value, [d.task_id]: "failed" };
      const done =
        typeof d.last_resumed_keyword === "number" ? d.last_resumed_keyword : null;
      const total = typeof d.total_keywords === "number" ? d.total_keywords : null;
      const progressText =
        done != null && total != null ? `已抓 ${done} / 共 ${total} 词，` : "";
      const body = `任务 #${d.task_id} 被百度风控中断，${progressText}可在详情页点「从断点继续」`;
      void _notify?.("CSM 百度监控", body);
      toast.warn(body, { ttl: 0 });
      bell.push(`监测任务 #${d.task_id} 被风控中断`, {
        body,
        tone: "warn",
        category: "monitor_alert",
      });
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
    // ── End native-Chrome mode events ─────────────────────────────
    finished: (d: any) => {
      if (typeof d.task_id === "number") {
        // 后端 finished 事件不带 progress_total（只有 progress 事件带），
        // 先从 store 里最后一次 progress 抢救 total（clearRunning 会清掉它）。
        const knownTotal =
          progressOf(d.task_id)?.total ??
          (typeof d.progress_total === "number" ? d.progress_total : null);
        clearRunning(d.task_id);
        lastOutcomes.value = { ...lastOutcomes.value, [d.task_id]: "done" };
        void _notify?.(
          "CSM 百度监控",
          knownTotal != null ? `监控完成，已抓 ${knownTotal} 词` : "监控完成",
        );
        bell.push("监测任务完成", {
          body: knownTotal != null ? `任务 #${d.task_id} · 共 ${knownTotal} 项` : `任务 #${d.task_id}`,
          tone: "success",
          category: "monitor_done",
        });
      }
    },
    failed: (d: any) => {
      if (typeof d.task_id !== "number") return;
      clearRunning(d.task_id);
      const err = String(d.error ?? "");
      lastOutcomes.value = {
        ...lastOutcomes.value,
        [d.task_id]: err.includes("cancelled by user") ? "cancelled" : "failed",
      };
      // Triage the failure reason so the user gets a useful toast.
      // - cancelled by user: they clicked 停止, no surprise — stay silent
      // - risk control: a separate SSE `risk_control` event carries the
      //   recovery UI (resume from breakpoint), no toast from here to
      //   avoid double-notifying
      // - slot timeout: friendly hint about queue saturation
      // - everything else: surface the first line so failures during
      //   navigated-away periods don't vanish silently
      if (err.includes("cancelled by user")) return;
      if (err.startsWith("风控拦截") || err.includes("captcha")) return;
      const reason = err.includes("timeout waiting for platform slot")
        ? "队列繁忙，请稍后重试或减少同时运行的任务"
        : (err.split("\n")[0] || "未知原因");
      toast.error(`监测任务 #${d.task_id} 失败：${reason}`);
      bell.push(`监测任务 #${d.task_id} 失败`, {
        body: reason,
        tone: "error",
        category: "monitor_alert",
      });
    },
  };

  /** 测试钩子：把一条 SSE 事件喂给处理表。生产路径 subscribe 绑同一张表。 */
  function _dispatchSse(kind: string, d: any): void {
    _sseHandlers[kind]?.(d);
  }

  /**
   * Subscribe to SSE and start the periodic hydration poll. Idempotent —
   * safe to call multiple times. Should be invoked once at app boot
   * (App.vue onMounted after sidecar is ready).
   */
  function start(): void {
    if (started) return;
    started = true;
    stopSse = subscribe("/api/monitor/events", _sseHandlers);
    // Initial sync + periodic safety net. 30 s is conservative — covers
    // sidecar restarts and any race where SSE drops/reconnects without
    // replaying the event we missed.
    void hydrate();
    pollTimer = setInterval(() => void hydrate(), 30000);
  }

  function stop(): void {
    if (stopSse) {
      stopSse();
      stopSse = null;
    }
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    started = false;
  }

  return {
    runningTaskIds,
    taskProgress,
    taskPhase,
    lastOutcomes,
    isRunning,
    progressOf,
    phaseOf,
    markRunning,
    clearRunning,
    setProgress,
    hydrate,
    cancel,
    start,
    stop,
    taskMutationNonce,
    bumpTaskMutation,
    _dispatchSse,
  };
});
