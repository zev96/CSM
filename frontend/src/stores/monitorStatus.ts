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

interface ProgressEntry {
  current: number;
  total: number;
}

export const useMonitorStatus = defineStore("monitorStatus", () => {
  const runningTaskIds = ref<Set<number>>(new Set());
  const taskProgress = ref<Record<number, ProgressEntry>>({});

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

  function markRunning(taskId: number): void {
    if (runningTaskIds.value.has(taskId)) return;
    const s = new Set(runningTaskIds.value);
    s.add(taskId);
    runningTaskIds.value = s;
  }

  function clearRunning(taskId: number): void {
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
      runningTaskIds.value = backendSet;
      // Drop progress entries for tasks no longer running on the backend
      const nextProgress: Record<number, ProgressEntry> = {};
      for (const [k, v] of Object.entries(taskProgress.value)) {
        const numK = Number(k);
        if (backendSet.has(numK)) nextProgress[numK] = v;
      }
      taskProgress.value = nextProgress;
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

  /**
   * Subscribe to SSE and start the periodic hydration poll. Idempotent —
   * safe to call multiple times. Should be invoked once at app boot
   * (App.vue onMounted after sidecar is ready).
   */
  function start(): void {
    if (started) return;
    started = true;
    stopSse = subscribe("/api/monitor/events", {
      started: (d: any) => {
        if (typeof d.task_id === "number" && d.task_id > 0) {
          markRunning(d.task_id);
        }
      },
      progress: (d: any) => {
        if (typeof d.task_id !== "number") return;
        const cur = typeof d.progress_current === "number" ? d.progress_current : 0;
        const tot = typeof d.progress_total === "number" ? d.progress_total : 0;
        setProgress(d.task_id, cur, tot);
      },
      finished: (d: any) => {
        if (typeof d.task_id === "number") clearRunning(d.task_id);
      },
      failed: (d: any) => {
        if (typeof d.task_id === "number") clearRunning(d.task_id);
      },
    });
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
    isRunning,
    progressOf,
    markRunning,
    clearRunning,
    setProgress,
    hydrate,
    cancel,
    start,
    stop,
  };
});
