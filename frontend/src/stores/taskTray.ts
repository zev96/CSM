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
    const job = mining.activeJob;
    if (!mining.hasRunningJob || !job) return null;
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
        parts.push(`${PLATFORM_LABEL[p] ?? p}等待验证`);
      } else if (pr.phase === "done") {
        parts.push(`${PLATFORM_LABEL[p] ?? p}已完成`);
      } else {
        parts.push(`${PLATFORM_LABEL[p] ?? p} ${pr.got ?? 0}/${pr.target ?? 0}`);
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
    const jobId = batch.jobId;
    if (batch.status !== "running" || !jobId) return null;
    const runningItem = batch.items.find((i) => i.status === "running");
    const doneCount = batch.items.filter(
      (i) => i.status === "success" || i.status === "failed" || i.status === "cancelled",
    ).length;
    const key = `batch:${jobId}`;
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
    const jobId = article.jobId;
    if (article.status !== "running" || !jobId) return null;
    const key = `article:${jobId}`;
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
        const aj = mining.activeJob;
        if (!aj || `mining:${aj.id}` !== task.key) return "done";
        const st = String(aj.status ?? "");
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
