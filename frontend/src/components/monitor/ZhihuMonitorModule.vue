<script setup lang="ts">
/**
 * 知乎问题 tab —— 监测中心的"知乎排名"子模块。
 *
 * 从 MonitorView.vue（约 786 行的知乎 tab 整段）拆出来，独立维护：
 *   - 任务列表（demo / 真实数据双源 unify 由父组件 props.tasks 提供）
 *   - zhihuAlerts hero 卡片堆叠 + chevron 翻页
 *   - 详情卡：KPI 二联 / 14 天卡位趋势 sparkline / 前 N 条答案列表
 *   - 演示模式下的启停 + 频率设置（zhihuMonitorState 本地 ref）
 *
 * 父组件 MonitorView 通过 props 注入 tasks / taskSnapshots / runningTaskIds
 * 等"跨 tab 共享"状态；跨域操作（打开 modal / 触发告警详情 / 翻页计数 /
 * 派发立刻监测 / 删除任务）由模块 emit 给父组件兜底，保持单一 modal 树。
 *
 * 拆分前后零行为改动：template 一字不改，computed / function 体内的
 * 逻辑原样保留；只是把 watch / loadResults / openZhihuAlert 流程的入口
 * 改成 defineExpose 让父组件的 goToZhihuTask 仍能从模块外驱动选中态，
 * 以及让父组件的 SSE finished 事件回调能通知模块刷新 taskResults。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import SplitPane from "@/components/ui/SplitPane.vue";
import Dropdown from "@/components/ui/Dropdown.vue";
// Sparkline 已下线 —— 统一改用 LineChart 跟 BaiduRankingPage 总任务图一致。
import LineChart from "./history/LineChart.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";
import {
  formatTimelineTime,
  formatRelativeTime,
  parseBatchName,
  formatVisitCount,
} from "@/utils/monitor-batch";
import {
  type TaskSnapshotPair,
} from "@/utils/monitor-snapshot";
import { batchZhihuKpis } from "@/utils/monitor-zhihu-kpi";
import {
  type Task,
  type HeroAlert,
  type MonitorState,
  SCHEDULE_OPTIONS,
  scheduleLabel,
} from "@/utils/monitor-types";

const props = defineProps<{
  tasks: Task[];
  taskSnapshots: Record<number, TaskSnapshotPair>;
  loading: boolean;
  failed: boolean;
  runningTaskIds: Record<number, true>;
  demoMode: boolean;
  activeTab: string;
}>();

// ── Sample fallbacks (V1 设计稿) ────────────────────────────────────────
interface SampleZhihu {
  id: string;
  kw: string;
  type: string;
  lastRank: number | null;
  prevRank: number;
  lastCheck: string;
  status: "ok" | "warn" | "alert";
  delta: number;
  /** 知乎问题原 URL，详情卡的「问题链接」按钮跳到这里。 */
  targetUrl: string;
}
// V1 设计稿示例数据，发布前清空保留空状态 —— 首次启动监测中心应显示
// 「暂无监测任务」而不是假的产品/排名/抢占者数据。
const SAMPLE_ZHIHU: SampleZhihu[] = [];

const SAMPLE_TOP3: Array<{ who: string; title: string; rank: number }> = [];

// SAMPLE_SPARK_RANK 已下线 —— sparkBuckets 改用 calendar scaffold，demo
// 模式 = 14 个 null bucket，不再需要单独的样本数据。

// 告警详情 modal 用的真实数据。openZhihuAlert 时同步算好后通过 emit
// 给父组件，父组件持有单一 modal 树。Null = 没数据，模态展示空态。
interface AlertTimelineItem {
  t: string;       // 时间显示
  rank: string;    // "#3" / "—"
  text: string;
  level: "alert" | "warn" | "info";
}
interface AlertGrabber {
  rank: number;
  who: string;
  title: string;
  voteup?: number;
  matchesBrand?: boolean;  // 是不是自家（高亮用）
}
export interface ZhihuAlertData {
  title: string;
  subtitle: string;
  matchedCount: number;       // 本次命中数
  matchedCountPrev: number | null;  // 上次命中数；null = 无历史
  alertTopN: number;
  firstRank: number;          // 首条命中位置；-1 表示无命中
  scheduleLabel: string;
  sparkPoints: number[];      // 历次首条命中排名（无则 0）
  sparkAxis: string[];
  timeline: AlertTimelineItem[];
  topAnswers: AlertGrabber[];
}

const emit = defineEmits<{
  (e: "add-task"): void;
  (e: "import-batch"): void;
  (e: "cookie-mgr"): void;
  (e: "edit-task", task: Task): void;
  (e: "edit-batch", payload: { name: string; tasks: Task[] }): void;
  (e: "delete-task", taskId: number): void;
  (e: "run-task", taskId: number): void;
  // 批次级单事件 —— 复用父组件 runBatch/deleteBatch（一次确认 + Promise.all
  // + 一条聚合 toast），跟 CommentMonitorModule 的 run-batch/delete-batch 同签名。
  (e: "run-batch", batchName: string): void;
  (e: "delete-batch", batchName: string): void;
  (e: "cancel-task", taskId: number): void;
  (e: "alert-action", action: string): void;
  (e: "open-alert", payload: { kind: "zhihu_alert"; data: ZhihuAlertData | null }): void;
  (e: "cycle-alert", dir: 1 | -1): void;
}>();

const sidecar = useSidecar();
const toast = useToast();
const router = useRouter();

// ── 当前选中任务 ───────────────────────────────────────────────────────
// 详情卡跟着 selectedTaskId 切。父组件 goToZhihuTask 通过 defineExpose
// 的 selectTask 写入；模块内部点击任务行也写它。loadTasksAndSnapshotsAtomic
// 完成后，若当前选中已不在 tasks 中，自动 fallback 到第一条任务。
const selectedTaskId = ref<number | null>(null);
const taskResults = ref<Array<{ checked_at: string; status: string; rank: number; metric: any }>>([]);

// ── 批次两层钻入（L1 批次列表 ↔ L2 子任务）─────────────────────────────
// 沿用评论平台「命名约定批次」：task.name = "批次名 - 问题标题"，
// parseBatchName 按最后一个 " - " 分组。openBatchName == null 显示批次
// 列表(L1)；非 null 显示该批次的子任务(L2)。右侧详情卡不受影响，仍按
// selectedTaskId 走（L2 点子任务行时写入）。
const openBatchName = ref<string | null>(null);

// L1 右侧详情面板选中的批次 —— 点批次「行」（不是批次名链接）选中它，
// 批次名链接负责钻入 L2（openBatchName）。跟 BaiduRankingPage 的 previewId
// 同语义：行点击只把右卡详情定位到这条批次，不导航。默认 fallback 第一条
// 批次（下方 watch 接管），保证 L1 右卡不空。
const selectedBatchName = ref<string | null>(null);

interface ZhihuBatch {
  name: string;
  tasks: Task[];
}
const batches = computed<ZhihuBatch[]>(() => {
  const map = new Map<string, Task[]>();
  for (const t of props.tasks) {
    const b = parseBatchName(t.name);
    const arr = map.get(b);
    if (arr) arr.push(t);
    else map.set(b, [t]);
  }
  return Array.from(map, ([name, tasks]) => ({ name, tasks }));
});

// L1 右卡详情：选中的批次（previewId fallback 到第一条）。批次被删/改名
// 后若选中已不在列表里，自动回落第一条，跟 BaiduRankingPage.previewTask
// 同套兜底逻辑。
const selectedBatch = computed<ZhihuBatch | null>(() => {
  if (batches.value.length === 0) return null;
  if (selectedBatchName.value != null) {
    const hit = batches.value.find((b) => b.name === selectedBatchName.value);
    if (hit) return hit;
  }
  return batches.value[0];
});

// 选中批次共享的目标品牌 —— 取该批次第一条子任务的 config.target_brand
// （知乎批次内所有子任务共用同一个品牌词，导入时统一写入）。config 即便
// 没跑过监测也存在，比从 snapshot.target_brand 取更稳。
const selectedBatchBrand = computed<string>(() => {
  const first = selectedBatch.value?.tasks[0];
  const brand = first?.config?.target_brand;
  return typeof brand === "string" && brand.trim() ? brand : "";
});

// L1 右卡 KPI 汇总 —— 由批次所有子任务的最新快照聚合，纯客户端。
const selectedBatchKpis = computed(() => {
  const b = selectedBatch.value;
  if (!b) return null;
  const snaps = b.tasks
    .map((t) => props.taskSnapshots[t.id]?.latest)
    .filter((s): s is NonNullable<typeof s> => !!s)
    .map((s) => ({ matched_count: s.matched_count ?? 0, rank: s.rank ?? -1 }));
  return batchZhihuKpis(snaps);
});

// 批次列表变化时把 selectedBatchName 收敛到一个有效值（默认第一条）——
// 跟 selectedTaskId 的 fallback watch 同模式，保证 L1 右卡详情面板不空。
watch(
  batches,
  (list) => {
    if (list.length === 0) {
      selectedBatchName.value = null;
    } else if (
      selectedBatchName.value == null ||
      !list.find((b) => b.name === selectedBatchName.value)
    ) {
      selectedBatchName.value = list[0].name;
    }
  },
  { immediate: true },
);

// L2 当前批次的子任务；批次被删空（或批次名消失）时回退到 L1。
const currentBatchTasks = computed<Task[]>(() => {
  if (openBatchName.value == null) return [];
  return batches.value.find((b) => b.name === openBatchName.value)?.tasks ?? [];
});
watch(currentBatchTasks, (list) => {
  if (openBatchName.value != null && list.length === 0) openBatchName.value = null;
});

// 子任务显示名 = 去掉 "批次名 - " 前缀（单条直接用原名）。
function subtaskTitle(t: Task): string {
  const prefix = `${parseBatchName(t.name)} - `;
  return t.name.startsWith(prefix) ? t.name.slice(prefix.length) : t.name;
}

// 批次操作 —— 走批次级单事件，复用父组件 runBatch/deleteBatch（按
// parseBatchName 拢子任务，一次确认 + Promise.all + 一条聚合 toast），
// 跟 CommentMonitorModule 完全一致。不再逐个 emit run-task/delete-task：
// 那会让删除 N 题批次弹 N 次确认 / N 次 toast / N 次 reload。
// deleteBatch 不在这里清 openBatchName —— 等删除真的生效、currentBatchTasks
// 空了，下方 watch 自动回退到 L1（跟评论模块靠父回调收敛同理）。
function startBatch(b: ZhihuBatch) {
  emit("run-batch", b.name);
}
function deleteBatch(b: ZhihuBatch) {
  emit("delete-batch", b.name);
}
function editBatch(b: ZhihuBatch) {
  // 同时本地钻入该批次 L2 —— 父组件目前走「逐个用子任务 ✎ 编辑」的退化
  // 路径（无批次编辑弹窗），先把 L2 打开让用户直接看到可编辑的子任务行。
  openBatchName.value = b.name;
  emit("edit-batch", { name: b.name, tasks: b.tasks });
}

// ── L1 批次详情面板的「导出数据 / 定时监测」──────────────────────────
//
// 复用 BaiduRankingPage 同款能力，无需后端：
//   导出数据 = 纯前端 CSV blob 下载（列：问题名字 / 卡位数量 / 最高排名）；
//     数据源是每条子任务最近一次 snapshot（taskSnapshots[id].latest）。
//   定时监测 = 复用现有 edit-task emit 打开 AddTaskModal，让用户在里面改
//     schedule_cron（知乎无「批次级定时」后端，退化为编辑批次首条子任务，
//     跟 baidu openScheduleEditor 走 edit-task 同路径）。
function exportBatchCsv(b: ZhihuBatch): void {
  const rows: string[] = ["问题名字,卡位数量,最高排名"];
  let withData = 0;
  for (const t of b.tasks) {
    const snap = props.taskSnapshots[t.id]?.latest;
    const name = subtaskTitle(t);
    const safeName = `"${name.replace(/"/g, '""')}"`;
    if (snap) {
      const placed = snap.matched_count;
      const best = snap.rank > 0 ? `第 ${snap.rank} 名` : "未上榜";
      rows.push(`${safeName},${placed},"${best}"`);
      withData += 1;
    } else {
      rows.push(`${safeName},—,—`);
    }
  }
  if (withData === 0) {
    toast.warn("该批次还没有可导出的监测结果，请先运行一次监测");
    return;
  }
  // BOM 让 Excel 正确识别 UTF-8
  const blob = new Blob(["﻿" + rows.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const ts = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `${b.name}-卡位-${ts}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast.success(`已导出 ${b.tasks.length} 个问题`);
}

function scheduleBatch(b: ZhihuBatch): void {
  const first = b.tasks[0];
  if (!first) {
    toast.warn("该批次没有可设置的子任务");
    return;
  }
  emit("edit-task", first);
}

async function loadResults(taskId: number) {
  try {
    // 用户要求：趋势窗口从 14 天缩到 7 天。limit 拉 7 条够 sparkBuckets
    // 填满 7 个 calendar bucket（同一天多次跑只取最新，理论上不会满）。
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 7 },
    });
    taskResults.value = r.data.results ?? [];
  } catch {
    taskResults.value = [];
  }
}

// daysAgoLabels / ZHIHU_SPARK_LABELS 已下线 —— 趋势图改用 LineChart，
// 横轴 label 由 sparkChartLabels 从 taskResults.checked_at 派生（1:1 对齐
// 数据点），不再需要预先生成的 5-anchor 抽稀 label。

// 监测启停 + 频率 —— 演示模式下保存在本地 ref 里，真实模式改 PATCH
// /api/monitor/tasks/{id}。每个任务一份独立设置，切任务不会丢状态。
// 初始默认 enabled=false：第一眼看到的是橙色 CTA「启动监测」，邀请用户
// 主动点一下确认开启；点完才翻到灰色「监测进行中」状态。这是用户明确
// 要求的交互方向 —— 不要一进来就显示一个已勾选的 disabled-looking 按钮。
const zhihuMonitorState = ref<Record<string, MonitorState>>({
  "s-z1": { enabled: false, schedule: "hourly-6" },
  "s-z2": { enabled: false, schedule: "daily-09:00" },
  "s-z3": { enabled: false, schedule: "hourly-6" },
  "s-z4": { enabled: false, schedule: "manual" },
  "s-z5": { enabled: false, schedule: "daily-09:00" },
  "s-z6": { enabled: false, schedule: "daily-09:00" },
});

function ensureZhihuState(id: string): MonitorState {
  if (!zhihuMonitorState.value[id]) {
    zhihuMonitorState.value[id] = { enabled: false, schedule: "daily-09:00" };
  }
  return zhihuMonitorState.value[id];
}
function toggleMonitor(scope: "zhihu" | "comment", id: string) {
  // 评论 scope 现在由 CommentMonitorModule 内部处理；这里只剩 zhihu 分支
  // 实际可达。保留 scope 形参让模板调用签名不变，不可达分支当作 noop。
  if (scope !== "zhihu") return;
  const st = ensureZhihuState(id);
  st.enabled = !st.enabled;
  toast.info(`已${st.enabled ? "启动" : "暂停"}监测`);
}
function changeSchedule(scope: "zhihu" | "comment", id: string, v: string) {
  if (scope !== "zhihu") return;
  const st = ensureZhihuState(id);
  st.schedule = v;
  toast.success(`监测频率：${scheduleLabel(v)}`);
}

// 紧急告警 hero 改成可翻页的卡片堆叠：多条告警同时存在时，hero 只显示
// 当前一条 + 后面 2 张更小更暗的「卡片影子」，左右两个圆形 chevron 切上
// 一条 / 下一条。1 条告警时影子和 chevron 自动隐藏（hasNav 为 false）。
const zhihuAlertIdx = ref(0);
const currentZhihuAlert = computed(() => zhihuAlerts.value[zhihuAlertIdx.value]);
function cycleAlert(kind: "zhihu" | "comment", dir: 1 | -1) {
  if (kind !== "zhihu") return;
  const list = zhihuAlerts.value;
  if (!list.length) return;
  // wrap-around 让用户在 1↔️N 来回切不会被卡住；按钮始终可点，更直白。
  zhihuAlertIdx.value = (zhihuAlertIdx.value + dir + list.length) % list.length;
  // 同步通知父组件，让其他 tab 共享的告警 chevron 行为保持一致
  emit("cycle-alert", dir);
}

async function _buildZhihuAlertData(taskId: number, alert: HeroAlert): Promise<ZhihuAlertData | null> {
  const t = props.tasks.find((x) => x.id === taskId);
  if (!t) return null;
  // 拉近 14 条 result 做 sparkline + 时间线 + 取最新的 metric.answers
  let history: any[] = [];
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 14 },
    });
    history = r.data?.results ?? [];
  } catch {
    history = [];
  }
  const latest = history[0];
  const prev = history[1];
  const latestMatchedCount =
    typeof latest?.metric?.matched_count === "number"
      ? latest.metric.matched_count
      : (latest?.rank ?? -1) > 0 ? 1 : 0;
  const prevMatchedCount =
    prev
      ? (typeof prev?.metric?.matched_count === "number"
          ? prev.metric.matched_count
          : (prev?.rank ?? -1) > 0 ? 1 : 0)
      : null;
  const alertTopN =
    typeof latest?.metric?.top_n === "number"
      ? latest.metric.top_n
      : Number((t.schedule_cron && undefined) ?? 10) || 10;
  // sparkline 点：每次首条命中位置；-1 显示成 alertTopN+5 哨兵让 sparkline
  // 视觉上能区分"上榜"vs"掉出"。倒序排成"老 → 新"。
  const sparkPoints = history
    .slice()
    .reverse()
    .map((r: any) => {
      const rank = r?.rank ?? -1;
      return rank > 0 ? rank : alertTopN + 5;
    });
  // sparkline X 轴：取首尾 + 3 个等距日期标签
  const sparkAxis: string[] = [];
  if (history.length >= 2) {
    const first = new Date(history[history.length - 1].checked_at);
    const last = new Date(history[0].checked_at);
    const span = last.getTime() - first.getTime();
    for (let i = 0; i < 5; i++) {
      const d = new Date(first.getTime() + (span * i) / 4);
      sparkAxis.push(`${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
    }
  }
  // 时间线：最多取 5 条最近的 result
  const timeline: AlertTimelineItem[] = history.slice(0, 5).map((r: any, i: number) => {
    const rank = r?.rank ?? -1;
    const mc =
      typeof r?.metric?.matched_count === "number"
        ? r.metric.matched_count
        : rank > 0 ? 1 : 0;
    const prevR = history[i + 1];
    const prevRank = prevR?.rank ?? null;
    let text: string;
    let level: AlertTimelineItem["level"];
    if (rank === -1) {
      text = `「${t.name}」掉出前 ${alertTopN}`;
      level = "alert";
    } else if (prevRank && prevRank > 0 && rank > prevRank) {
      text = `下滑至第 ${rank} 名（−${rank - prevRank}）`;
      level = "warn";
    } else if (prevRank && prevRank > 0 && rank < prevRank) {
      text = `升至第 ${rank} 名（+${prevRank - rank}）· 命中 ${mc} 条`;
      level = "info";
    } else {
      text = `第 ${rank} 名（持平）· 命中 ${mc} 条`;
      level = "info";
    }
    return {
      t: formatTimelineTime(r.checked_at),
      rank: rank > 0 ? `#${rank}` : "—",
      text,
      level,
    };
  });
  // Top 抢占者：latest.metric.answers[:3]，命中目标品牌的高亮
  const answers = Array.isArray(latest?.metric?.answers) ? latest.metric.answers : [];
  const topAnswers: AlertGrabber[] = answers.slice(0, 3).map((a: any) => ({
    rank: Number(a.rank) || 0,
    who: String(a.author || "—"),
    title: String(a.content_preview || ""),
    voteup: Number(a.voteup_count) || 0,
    matchesBrand: Boolean(a.matches_brand),
  }));
  return {
    title: `「${t.name}」紧急告警`,
    subtitle: `知乎问题 · ${alert.subtitle}`,
    matchedCount: latestMatchedCount,
    matchedCountPrev: prevMatchedCount,
    alertTopN,
    firstRank: latest?.rank ?? -1,
    scheduleLabel: t.schedule_cron === "manual" ? "手动" : t.schedule_cron,
    sparkPoints,
    sparkAxis,
    timeline,
    topAnswers,
  };
}

async function openZhihuAlert(alert?: HeroAlert) {
  // 用 currentZhihuAlert 兜底（没显式传时）
  const a = alert ?? currentZhihuAlert.value;
  // 先 emit 一次空 data 让父组件打开 modal 占位（避免等 await 时模态延迟）
  emit("open-alert", { kind: "zhihu_alert", data: null });
  if (a?.taskId) {
    const data = await _buildZhihuAlertData(a.taskId, a);
    emit("open-alert", { kind: "zhihu_alert", data });
  }
}

// 卡位趋势 7 天 calendar bucket scaffold —— 跟 BaiduRankingPage 的
// bucketByCalendarDay 同模式，永远 7 个 bucket（今天 → 6 天前）；
// 把 taskResults 按 checked_at 的日期落到对应 bucket（同一天多次跑取
// 最后一次）。这样 LineChart 永远能 render 完整 7 天的 frame，没数据
// 的天为 null（chart.js spanGaps=false 自动画 gap），不再因为 taskResults
// 为空就退到文本 fallback。原本 14 天，用户反馈太长，缩到 7 天。
const sparkBuckets = computed<Array<{ label: string; value: number | null }>>(() => {
  // 7 个空 bucket（label = 日期 only "10"，跟 baidu 一致）
  const out: Array<{ iso: string; label: string; value: number | null }> = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push({ iso, label: String(d.getDate()), value: null });
  }
  // Demo mode 数据空（SAMPLE_SPARK_RANK 已清），直接返回纯 scaffold
  if (props.demoMode) return out;
  // 真实数据 → 按 iso 日期落桶；taskResults 按 checked_at desc 排（API
  // 默认顺序），同一天多次 "立刻监测" 取第一个（即最新一次）
  const placed = new Set<string>();
  for (const r of taskResults.value) {
    const d = new Date(r.checked_at);
    if (Number.isNaN(d.getTime())) continue;
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (placed.has(iso)) continue;  // 同日只放最新一次
    const bucket = out.find((b) => b.iso === iso);
    if (bucket) {
      bucket.value = Number((r as any).metric?.matched_count ?? 0);
      placed.add(iso);
    }
  }
  return out;
});

const sparkPoints = computed<(number | null)[]>(() => sparkBuckets.value.map((b) => b.value));
const sparkChartLabels = computed<string[]>(() => sparkBuckets.value.map((b) => b.label));

// 14 天卡位趋势的 Y 轴上限 = 当前选中任务的 Top-N（命中条数的容量上限）。
// 优先级：最新一次 metric.top_n（运行时写入）→ task.config.top_n（用户编辑
// 时存的）→ 10 兜底。这样曲线相对"容量"显示，而不是被某天小峰值放大。
const selectedTopN = computed<number>(() => {
  const fromMetric = taskResults.value[0]?.metric?.top_n;
  if (typeof fromMetric === "number" && fromMetric > 0) return fromMetric;
  const fromCfg = selectedTask.value?.config?.top_n;
  if (typeof fromCfg === "number" && fromCfg > 0) return fromCfg;
  return 10;
});

// L2 详情面板宽屏判断：≥640px 时趋势图和答案列表并排。
// matchMedia 驱动，避免 CSS-only 方案在 SSR 或测试环境出问题。
const l2Wide = ref(typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches);
let l2Mq: MediaQueryList | null = null;
const onL2MqChange = (e: MediaQueryListEvent) => { l2Wide.value = e.matches; };
if (typeof window !== "undefined") {
  l2Mq = window.matchMedia("(min-width: 640px)");
  l2Mq.addEventListener("change", onL2MqChange);
}
onBeforeUnmount(() => l2Mq?.removeEventListener("change", onL2MqChange));

watch(selectedTaskId, async (id) => {
  if (id != null && id > 0) await loadResults(id);
});

// 跟父组件 loadTasks / loadTasksAndSnapshotsAtomic 之前的「首次进 zhihu
// tab 时若 selectedTaskId 不在 tasks 列表里，自动 fallback 到第一条任
// 务」行为同步：把这个逻辑迁到模块内对 props.tasks 的 watch 里。父组件
// 抽完 zhihu state 后不再管 selectedTaskId，模块自己接管选中态。
watch(
  () => props.tasks,
  (newTasks) => {
    if (newTasks.length > 0 && (!selectedTaskId.value || !newTasks.find((t) => t.id === selectedTaskId.value))) {
      selectedTaskId.value = newTasks[0].id;
    }
  },
  { immediate: true },
);

const selectedTask = computed(() =>
  props.tasks.find((t) => t.id === selectedTaskId.value) ?? null,
);

// 知乎详情卡的 "Top 3 抢占者" —— 从 taskResults 的最新一次 result
// (`taskResults[0]`，按 checked_at desc 来) 的 `metric.answers` 取前 3。
// 每条 answer 由 zhihu_question 的 `_rank_brand` 写出，字段：rank /
// author / content_preview / voteup_count / matches_brand。matches_brand
// 标记的是命中目标品牌的那条，UI 上用 primary-soft 高亮。
interface ZhihuTopAnswer {
  rank: number;
  author: string;
  content_preview: string;
  voteup_count: number;
  matches_brand: boolean;
}
// 详情卡里展示的全部前 N 条答案。原来只取前 3（"Top 3 抢占者"），但
// 用户要求"前 N 条命中的都标记出来"，所以拿全量返回，模板用
// `.matches_brand` 高亮命中行。
const topAnswersForSelectedTask = computed<ZhihuTopAnswer[]>(() => {
  if (!selectedTask.value) return [];
  const latest = taskResults.value[0];
  const answers = latest?.metric?.answers;
  if (!Array.isArray(answers)) return [];
  return answers.map((a: any) => ({
    rank: Number(a.rank) || 0,
    author: String(a.author ?? ""),
    content_preview: String(a.content_preview ?? ""),
    voteup_count: Number(a.voteup_count) || 0,
    matches_brand: Boolean(a.matches_brand),
  }));
});

// 演示模式下的当前 zhihu 任务（用于详情卡片）。SAMPLE_ZHIHU 发布前已清空，
// 这里改为可空 ref；模板里详情卡用 v-if 守卫，没有示例数据就显示空状态。
const sampleSelectedZhihu = ref<SampleZhihu | null>(SAMPLE_ZHIHU[0] ?? null);

// ── 告警 hero（zhihu）computed ────────────────────────────────────────
//
//   zhihu  ⇒ task 撞 failed / risk_control / 排名掉出 top_n / 排名暴跌 ≥6
//
// 一类任务最多堆 3 张 hero（match 设计稿的卡片堆叠），多了用户在 chevron
// 之间切。空时 hero 整段不显示。
const zhihuAlerts = computed<HeroAlert[]>(() => {
  if (props.demoMode || props.activeTab !== "zhihu") return [];
  const out: HeroAlert[] = [];
  for (const t of props.tasks) {
    const pair = props.taskSnapshots[t.id];
    const snap = pair?.latest;
    const prev = pair?.prev;
    let headline = "";
    if (t.last_status === "failed") headline = "抓取失败";
    else if (t.last_status === "risk_control") headline = "触发风控";
    else if (snap && snap.rank === -1) {
      const topN = snap.total_fetched > 0 ? snap.total_fetched : 10;
      headline = `已掉出前 ${topN}`;
    } else if (snap && prev && prev.rank > 0 && snap.rank > 0 && snap.rank - prev.rank >= 6) {
      headline = `跌 ${snap.rank - prev.rank} 名 · 现 #${snap.rank}`;
    } else {
      continue;
    }
    out.push({
      keyword: t.name,
      headline,
      subtitle: `上次检查 ${formatRelativeTime(snap?.checked_at || t.last_check_at)}`,
      taskId: t.id,
    });
    if (out.length >= 3) break;
  }
  return out;
});

// 面板交互：点击演示行切换详情卡
function pickSampleZhihu(row: SampleZhihu) {
  sampleSelectedZhihu.value = row;
}

// 父组件历史报告 drill-down 时调用：先切 activeTab，然后等两 tick 让
// atomic load 跑完，最后调本接口把选中态写到位。
function selectTask(taskId: number) {
  selectedTaskId.value = taskId;
}

// 父组件 SSE finished 事件回调 —— 抓完一条立刻刷新 taskResults。
// 仅当 finished 的 task_id 等于当前选中时才拉，跟拆分前的 startMonitorBus
// 里 `if (selectedTaskId.value === d.task_id) loadResults(d.task_id)` 等价。
function onTaskFinished(taskId: number) {
  if (selectedTaskId.value === taskId) {
    loadResults(taskId);
  }
}

// 父组件删除任务后调用：若当前停在被删任务上，清空选中 + 历史。
function handleTaskDeleted(taskId: number) {
  if (selectedTaskId.value === taskId) {
    selectedTaskId.value = null;
    taskResults.value = [];
  }
}

defineExpose({ selectTask, onTaskFinished, handleTaskDeleted });
</script>

<template>
  <!--
    Root：必须是 `flex min-h-0 flex-1 flex-col`（跟 CommentMonitorModule
    同款修复）。MonitorView root 是 flex column + h-full，本模块作为子项
    要"占满剩余高度 + 让内部 flex-1 子链生效"。原本 `space-y-6` 裸 <div>
    不是 flex 容器也没 flex-1，下面 `grid min-h-0 flex-1` 的 grid container
    高度退化到 max(content) —— 左卡(任务表 6 行)和右卡(任务详情)谁内容
    多谁就把 grid row 撑高，另一边 h-full 跟着拉但内部 content 不填满，
    视觉上两张卡高度对不齐（左 580 / 右 480，差 100px）。
    flex-1 占满父剩余 + min-h-0 解锁子级收缩 + gap-24 替代 space-y-6 间距。
  -->
  <div class="flex min-h-0 flex-1 flex-col" :style="{ gap: '24px' }">
    <!--
      告警 hero 包裹层 —— 当告警数 > 1 时，hero 下方再放 1–2 张更窄
      更暗的「影子」卡，形成卡片堆叠的视觉；点右上角的 ‹ › 切换上一
      条 / 下一条。1 条时 hasNav=false，影子和按钮一起隐藏。
    -->
    <div
      v-if="zhihuAlerts.length > 0 && currentZhihuAlert"
      class="relative flex-shrink-0"
      :style="{ paddingBottom: zhihuAlerts.length > 1 ? '14px' : '0' }"
    >
      <!-- 影子卡片 #1 (2nd) — 比 hero 窄 16px，下偏 6px，更暗 -->
      <div
        v-if="zhihuAlerts.length > 1"
        aria-hidden="true"
        :style="{
          position: 'absolute',
          left: '8px',
          right: '8px',
          top: '8px',
          bottom: '0',
          background: 'var(--dark)',
          opacity: 0.55,
          borderRadius: 'var(--radius-card)',
          transform: 'translateY(0)',
          zIndex: 0,
        }"
      />
      <!-- 影子卡片 #2 (3rd) — 再窄 16px -->
      <div
        v-if="zhihuAlerts.length > 2"
        aria-hidden="true"
        :style="{
          position: 'absolute',
          left: '16px',
          right: '16px',
          top: '14px',
          bottom: '-6px',
          background: 'var(--dark)',
          opacity: 0.3,
          borderRadius: 'var(--radius-card)',
          zIndex: 0,
        }"
      />
      <!-- 真正的 hero -->
      <div
        class="relative overflow-hidden"
        :style="{
          background: 'var(--dark)',
          color: 'var(--card)',
          borderRadius: 'var(--radius-card)',
          padding: '26px 28px',
          zIndex: 1,
        }"
      >
        <div
          aria-hidden="true"
          :style="{
            position: 'absolute',
            top: '-50px', left: '20px',
            width: '240px', height: '240px',
            background: 'radial-gradient(circle, rgba(216,90,72,0.55), transparent 65%)',
            filter: 'blur(12px)',
            pointerEvents: 'none',
          }"
        />
        <div
          aria-hidden="true"
          :style="{
            position: 'absolute',
            top: '60px', left: '400px',
            width: '220px', height: '220px',
            background: 'radial-gradient(circle, rgba(238,106,42,0.45), transparent 65%)',
            filter: 'blur(12px)',
            pointerEvents: 'none',
          }"
        />
        <div class="relative flex items-center justify-between gap-6">
          <div class="min-w-0">
            <div
              class="flex items-center gap-2 text-[11px] uppercase"
              :style="{ letterSpacing: '1.5px', color: 'rgba(255,255,255,0.5)' }"
            >
              <span>{{ zhihuAlerts.length }} 个紧急告警</span>
              <span
                v-if="zhihuAlerts.length > 1"
                :style="{ color: 'rgba(255,255,255,0.4)', letterSpacing: '0' }"
              >· {{ zhihuAlertIdx + 1 }} / {{ zhihuAlerts.length }}</span>
            </div>
            <div
              class="font-display mt-2 font-bold"
              :style="{ fontSize: '28px', letterSpacing: '-0.5px', lineHeight: '1.25' }"
            >
              「{{ currentZhihuAlert.keyword }}」<br />
              <span :style="{ color: 'var(--primary)' }">{{ currentZhihuAlert.headline }}</span>
            </div>
            <div class="mt-2 text-[12.5px]" :style="{ color: 'rgba(255,255,255,0.6)' }">
              {{ currentZhihuAlert.subtitle }}
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <!-- prev / next chevrons (only when > 1 alert) -->
            <template v-if="zhihuAlerts.length > 1">
              <button
                type="button"
                title="上一条告警"
                class="inline-flex items-center justify-center"
                :style="{
                  width: '32px',
                  height: '32px',
                  borderRadius: '999px',
                  background: 'rgba(255,255,255,0.08)',
                  color: '#fbf7ec',
                  border: '1px solid rgba(255,255,255,0.12)',
                }"
                @click="cycleAlert('zhihu', -1)"
              >
                <Icon name="arrowLeft" :size="14" />
              </button>
              <button
                type="button"
                title="下一条告警"
                class="inline-flex items-center justify-center"
                :style="{
                  width: '32px',
                  height: '32px',
                  borderRadius: '999px',
                  background: 'rgba(255,255,255,0.08)',
                  color: '#fbf7ec',
                  border: '1px solid rgba(255,255,255,0.12)',
                }"
                @click="cycleAlert('zhihu', 1)"
              >
                <Icon name="arrowRight" :size="14" />
              </button>
              <span :style="{ width: '6px' }" />
            </template>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-medium"
              :style="{
                background: 'rgba(255,255,255,0.08)',
                color: '#fbf7ec',
                borderRadius: '999px',
                border: '1px solid rgba(255,255,255,0.12)',
              }"
              @click="openZhihuAlert(currentZhihuAlert)"
            >
              <Icon name="fileText" :size="14" />
              <span>查看报告</span>
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-medium"
              :style="{
                background: 'var(--primary)',
                color: '#fff',
                borderRadius: '999px',
              }"
              @click="router.push({ name: 'article' })"
            >
              <Icon name="edit" :size="14" />
              <span>起一篇救场</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- table + detail — SplitPane: 左定宽 340px，右 1fr -->
    <SplitPane>
      <template #left>
      <!--
        table card —— min-h-0 + overflow-hidden 把任务列表的滚动锁在卡片内，
        否则任务行过多时 grid 项会撑爆页面。
      -->
      <section
        class="flex h-full min-h-0 flex-col overflow-hidden"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
          <div class="min-w-0">
            <div class="font-display text-[14px] font-semibold">监测任务</div>
            <!-- 「问题列表」subtitle 已按用户要求移除（卡片标题已说明用途） -->
          </div>
          <div class="flex flex-shrink-0 gap-2">
            <!--
              原 Cookie 按钮已移除：Cookie 管理统一走「设置 → 监测中心」，
              避免每个 tab 都开一个入口造成重复。父组件的
              CookieManagerModal + @cookie-mgr 监听保留不动（emit 没人
              发就是 no-op），未来如要在 tab 内重启入口直接补回按钮即可。
            -->
            <button
              type="button"
              class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px]"
              :style="{
                background: 'transparent',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
              }"
              @click="emit('import-batch')"
            >
              <Icon name="folder" :size="12" />
              <span>批量导入</span>
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
              :style="{
                background: 'var(--primary)',
                color: '#fff',
                borderRadius: '999px',
              }"
              @click="emit('add-task')"
            >
              <Icon name="plus" :size="12" />
              <span>新建任务</span>
            </button>
          </div>
        </div>

        <!--
          L2 返回条 —— 固定在滚动区**外**（flex-shrink-0），只让下方子任务
          列表滚动，对齐评论平台 L2。之前它在 overflow-y-auto 里 → 下拉条
          范围把返回条也圈进去了。
        -->
        <div
          v-if="!demoMode && openBatchName != null"
          class="mb-3 flex flex-shrink-0 items-center gap-3"
        >
          <button
            type="button"
            class="inline-flex flex-shrink-0 items-center justify-center"
            :style="{
              width: '28px',
              height: '28px',
              borderRadius: '999px',
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              color: 'var(--ink-2)',
            }"
            title="返回批次列表"
            @click="openBatchName = null"
          >
            <Icon name="arrowLeft" :size="13" />
          </button>
          <div class="min-w-0">
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
              知乎问题 · 子任务列表
            </div>
            <div class="font-display truncate text-[14px] font-semibold">
              {{ openBatchName }}
            </div>
          </div>
          <span
            class="ml-auto flex-shrink-0 rounded-full text-[10.5px]"
            :style="{
              background: 'var(--card-2)',
              color: 'var(--ink-3)',
              padding: '2px 8px',
            }"
          >{{ currentBatchTasks.length }} 个问题</span>
        </div>

        <!--
          列头固定在滚动区**外**（flex-shrink-0 sibling），只让下方数据行
          滚动 —— 三种模式各一份平行列头，gate 条件与下方滚动区里的行
          v-if 链一一对应（demo / L1 批次 / L2 子任务）。grid-template-columns
          必须与各自的行保持一致，否则列会错位。
        -->
        <!-- DEMO 列头 —— 5 列（与 demo 行同 1.6fr .7fr .7fr .7fr 1fr） -->
        <div
          v-if="demoMode"
          class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.6fr .7fr .7fr .7fr 1fr',
            letterSpacing: '1.2px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>问题名字</div>
          <div class="text-center">类型</div>
          <div class="text-center">卡位</div>
          <div class="text-center">变化</div>
          <div class="text-center">操作</div>
        </div>

        <!-- L1 批次列头 —— 3 列（与批次行同 1.5fr .9fr 1.1fr） -->
        <div
          v-else-if="openBatchName == null"
          class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.5fr .9fr 1.1fr',
            letterSpacing: '1.2px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>任务名字</div>
          <div class="text-center">状态</div>
          <div class="text-center">操作</div>
        </div>

        <!-- L2 子任务列头 —— 3 列（与子任务行同 1.5fr .9fr 1.1fr） -->
        <div
          v-else
          class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.5fr .9fr 1.1fr',
            letterSpacing: '1.2px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>问题名字</div>
          <div class="text-center">变化</div>
          <div class="text-center">操作</div>
        </div>

        <!-- scrollable table body — fills remaining vertical space（只含数据行，列头已上移到滚动区外） -->
        <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">

        <!-- ════════ DEMO 模式：保留原扁平空态 / 样本行（不做批次 UI）════════ -->
        <!-- 列头（5 列，删了「状态」）已上移到滚动区外，固定不滚 -->
        <template v-if="demoMode">
          <!-- demo empty state — SAMPLE_ZHIHU 发布前已清空，首次启动展示空态 -->
          <template v-if="SAMPLE_ZHIHU.length === 0">
            <div
              class="py-10 text-center text-[12.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              暂无监测任务 · 点击「新建任务」开始监测
            </div>
          </template>

          <!-- demo rows —— 5 cols (状态列已移除) -->
          <template v-else>
            <div
              v-for="(t, i) in SAMPLE_ZHIHU"
              :key="t.id"
              class="grid cursor-pointer items-center transition"
              :style="{
                gridTemplateColumns: '1.6fr .7fr .7fr .7fr 1fr',
                background: sampleSelectedZhihu?.id === t.id ? 'var(--card-2)' : 'transparent',
                borderBottom: i < SAMPLE_ZHIHU.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '14px 8px',
                borderRadius: '10px',
              }"
              @click="pickSampleZhihu(t)"
            >
              <div class="truncate text-[13px] font-medium">{{ t.kw }}</div>
              <div class="text-center text-[12px]" :style="{ color: 'var(--ink-2)' }">问题</div>
              <div class="text-center font-display text-[13px] font-bold">
                {{ t.lastRank == null ? "—" : `#${t.lastRank}` }}
              </div>
              <div class="text-center">
                <Pill v-if="t.delta > 0" tone="ok">
                  <Icon name="arrowUp" :size="10" />
                  +{{ t.delta }}
                </Pill>
                <Pill v-else-if="t.delta < 0 && t.delta > -10" tone="warn">
                  <Icon name="arrowDown" :size="10" />
                  {{ t.delta }}
                </Pill>
                <Pill v-else-if="t.delta === 0" tone="info">持平</Pill>
                <Pill v-else tone="alert">
                  <Icon name="warn" :size="10" />
                  掉出
                </Pill>
              </div>
              <div class="flex items-center justify-center" :style="{ color: 'var(--ink-3)', fontSize: '11px' }">—</div>
            </div>
          </template>
        </template>

        <!-- ════════ L1：批次列表（openBatchName == null）════════ -->
        <!--
          命名约定批次：parseBatchName 按 task.name 最后一个 " - " 分组。
          点批次行钻入 L2；▶ 启动批次内全部子任务 / ✎ 编辑批次共享设置 /
          🗑 删除整个批次（均复用单任务 emit，父对每个 id 走既有流程）。
        -->
        <template v-else-if="openBatchName == null">
          <!-- 列头（批次名 / 问题数 / 操作）已上移到滚动区外，固定不滚 -->
          <div
            v-if="batches.length === 0"
            class="py-10 text-center text-[12.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            暂无监测任务 · 点「批量导入」开始
          </div>

          <div
            v-for="(b, i) in batches"
            :key="b.name"
            class="grid cursor-pointer items-center transition"
            :style="{
              gridTemplateColumns: '1.5fr .9fr 1.1fr',
              background: selectedBatchName === b.name ? 'var(--card-2)' : 'transparent',
              borderBottom: i < batches.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
              borderRadius: '10px',
            }"
            @click="selectedBatchName = b.name"
            @mouseenter="(e) => { if (selectedBatchName !== b.name) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
            @mouseleave="(e) => { if (selectedBatchName !== b.name) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
          >
            <!-- Col 1: 批次名（钻入 L2）+ 副标题（问题数 · 品牌） -->
            <div class="min-w-0">
              <button
                type="button"
                class="truncate text-left text-[13px] font-semibold"
                :style="{ color: selectedBatchName === b.name ? 'var(--primary-deep)' : 'var(--ink)', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', maxWidth: '100%' }"
                title="查看该批次的问题列表"
                @click.stop="openBatchName = b.name"
              >{{ b.name }}</button>
              <div class="truncate text-[11px]" :style="{ color: 'var(--ink-3)' }">
                {{ b.tasks.length }} 个问题 · 品牌 {{ b.tasks[0]?.config?.target_brand || '—' }}
              </div>
            </div>
            <!-- Col 2: 状态 Pill —— 批次内有任务运行中 → 进行中，否则 → 就绪 -->
            <div class="flex items-center justify-center">
              <Pill
                v-if="b.tasks.some((t) => runningTaskIds[t.id])"
                tone="ok"
              >进行中</Pill>
              <Pill v-else tone="info">就绪</Pill>
            </div>
            <!-- Col 3: ⋯ Dropdown -->
            <div class="flex items-center justify-center">
              <Dropdown
                :items="[
                  { key: 'run', label: '启动批次', icon: 'play' },
                  { key: 'edit', label: '编辑批次', icon: 'edit' },
                  { key: 'delete', label: '删除批次', icon: 'trash', tone: 'danger' },
                ]"
                align="right"
                @select="(key) => {
                  if (key === 'run') startBatch(b);
                  else if (key === 'edit') editBatch(b);
                  else if (key === 'delete') deleteBatch(b);
                }"
              >
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{ borderRadius: '999px', color: 'var(--ink-3)', cursor: 'pointer' }"
                    title="更多操作"
                    @click.stop
                  >
                    <Icon name="more" :size="14" />
                  </button>
                </template>
              </Dropdown>
            </div>
          </div>
        </template>

        <!-- ════════ L2：批次内子任务（openBatchName != null）════════ -->
        <!--
          在原扁平 real-rows 模板上：(a) 顶部加「‹ 返回批次」面包屑，
          (b) v-for 源换成 currentBatchTasks，(c) 名字用 subtaskTitle(t)，
          (d)「类型」列换成「浏览量」（formatVisitCount latest 的
          question_visit_count）。卡位 / 变化 / 操作 cell 原样保留。
        -->
        <template v-else>
          <!-- L2 列头和返回条均已上移到滚动区外，只让行滚动 -->
          <div
            v-for="(t, i) in currentBatchTasks"
            :key="t.id"
            class="grid cursor-pointer items-center transition"
            :style="{
              gridTemplateColumns: '1.5fr .9fr 1.1fr',
              background: selectedTaskId === t.id ? 'var(--card-2)' : 'transparent',
              borderBottom: i < currentBatchTasks.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
              borderRadius: '10px',
            }"
            @click="selectedTaskId = t.id"
          >
            <!-- Col 1: 问题名 + 副标题（浏览量 · 卡位） -->
            <div class="min-w-0">
              <div
                class="truncate text-[13px] font-semibold"
                :style="{ color: selectedTaskId === t.id ? 'var(--primary-deep)' : 'var(--ink)' }"
              >{{ subtaskTitle(t) }}</div>
              <div class="truncate text-[11px]" :style="{ color: 'var(--ink-3)' }">
                {{ formatVisitCount(taskSnapshots[t.id]?.latest?.question_visit_count) }} 浏览 · 卡位 {{ taskSnapshots[t.id]?.latest?.matched_count ?? 0 }}
              </div>
            </div>
            <!--
              Col 2: 变化 Pill —— 命中数 delta（latest vs prev）。
              +N = 多一条占位（ok），-N = 少一条（warn），持平（info）。
            -->
            <div class="flex items-center justify-center">
              <template v-if="taskSnapshots[t.id]?.latest && taskSnapshots[t.id]?.prev">
                <template
                  v-if="taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count > 0"
                >
                  <Pill tone="ok">
                    <Icon name="arrowUp" :size="10" />
                    +{{ taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count }}
                  </Pill>
                </template>
                <template
                  v-else-if="taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count < 0"
                >
                  <Pill tone="warn">
                    <Icon name="arrowDown" :size="10" />
                    {{ taskSnapshots[t.id]!.latest!.matched_count - taskSnapshots[t.id]!.prev!.matched_count }}
                  </Pill>
                </template>
                <Pill v-else tone="info">持平</Pill>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)', fontSize: '12px' }">—</span>
            </div>
            <!-- Col 3: ⋯ Dropdown（运行中 → 第一项为停止，否则为立刻监测） -->
            <div class="flex items-center justify-center">
              <Dropdown
                :items="[
                  runningTaskIds[t.id]
                    ? { key: 'stop', label: '停止', icon: 'x' }
                    : { key: 'run', label: '立刻监测', icon: 'play' },
                  { key: 'edit', label: '编辑任务', icon: 'edit' },
                  { key: 'delete', label: '删除任务', icon: 'trash', tone: 'danger' },
                ]"
                align="right"
                @select="(key) => {
                  if (key === 'run') emit('run-task', t.id);
                  else if (key === 'stop') emit('cancel-task', t.id);
                  else if (key === 'edit') emit('edit-task', t);
                  else if (key === 'delete') emit('delete-task', t.id);
                }"
              >
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{ borderRadius: '999px', color: 'var(--ink-3)', cursor: 'pointer' }"
                    title="更多操作"
                    @click.stop
                  >
                    <Icon name="more" :size="14" />
                  </button>
                </template>
              </Dropdown>
            </div>
          </div>
        </template>
        </div>
      </section>
      </template>

      <template #right>
      <!-- detail card —— min-h-0 + overflow-hidden；滚动锁在子区块（前N答案 / L1属性区） -->
      <section
        class="flex h-full min-h-0 flex-col overflow-hidden"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <template v-if="demoMode && !sampleSelectedZhihu">
          <div class="py-6 text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
            点击左侧任意任务查看详情。
          </div>
        </template>
        <template v-else-if="demoMode && sampleSelectedZhihu">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="font-display text-[14px] font-semibold">
                「{{ sampleSelectedZhihu.kw }}」
              </div>
              <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                {{ sampleSelectedZhihu.type }}
              </div>
            </div>
            <a
              :href="sampleSelectedZhihu.targetUrl"
              target="_blank"
              rel="noopener"
              class="inline-flex flex-shrink-0 items-center gap-1 px-3 py-1.5 text-[11.5px]"
              :style="{
                background: 'var(--card-2)',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
                textDecoration: 'none',
              }"
              title="在浏览器打开知乎问题"
            >
              <Icon name="external" :size="12" />
              <span>问题链接</span>
            </a>
          </div>

          <div class="mt-3 grid grid-cols-3 gap-3">
            <div
              v-for="s in [
                { l: '当前排名', v: sampleSelectedZhihu.lastRank == null ? '—' : `#${sampleSelectedZhihu.lastRank}` },
                { l: '上次排名', v: `#${sampleSelectedZhihu.prevRank}` },
                { l: '检查频率', v: '每 6 小时' },
              ]"
              :key="s.l"
              :style="{
                padding: '12px',
                borderRadius: '12px',
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">{{ s.l }}</div>
              <div
                class="font-display mt-1 font-bold"
                :style="{ fontSize: '18px' }"
              >{{ s.v }}</div>
            </div>
          </div>

          <div class="mt-5">
            <div class="mb-2 text-[12px] font-semibold">最近 7 次快照</div>
            <!--
              demo 模式：sparkBuckets 永远是 14 个 null（SAMPLE_SPARK_RANK
              已清空），LineChart 渲染空 frame；用户看到完整的 14 天日期
              轴提示"这里将来会有趋势线"。
            -->
            <LineChart
              :labels="sparkChartLabels"
              :series="[
                {
                  label: '卡位数量',
                  color: 'var(--red, #d85a48)',
                  data: sparkPoints,
                },
              ]"
            />
          </div>

          <div class="mt-4">
            <div class="mb-2 text-[12px] font-semibold">Top 3 抢占者</div>
            <div
              v-for="(x, i) in SAMPLE_TOP3"
              :key="i"
              class="mb-1.5 flex items-center gap-3"
              :style="{
                padding: '10px',
                borderRadius: '10px',
                background: i === 0 ? 'var(--primary-soft)' : 'var(--card-2)',
                border: '1px solid var(--line)',
              }"
            >
              <span
                class="font-display text-[13px] font-bold"
                :style="{
                  width: '22px',
                  color: i === 0 ? 'var(--primary-deep)' : 'var(--ink-2)',
                }"
              >#{{ x.rank }}</span>
              <div class="min-w-0 flex-1">
                <div class="truncate text-[12.5px] font-medium">{{ x.title }}</div>
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">{{ x.who }}</div>
              </div>
              <Icon name="arrowRight" :size="13" class="opacity-50" />
            </div>
          </div>

          <!-- 启停监测 + 频率设置 —— 部分任务可能没设定时；这里直接调。 -->
          <div
            class="mt-4 flex flex-shrink-0 items-center gap-2"
            :style="{
              paddingTop: '14px',
              borderTop: '1px solid var(--line)',
            }"
          >
            <button
              type="button"
              class="inline-flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-[12px] font-medium"
              :style="{
                background: ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'var(--card-2)' : 'var(--primary)',
                color: ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'var(--ink)' : '#fff',
                border: '1px solid ' + (ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'var(--line)' : 'var(--primary)'),
                borderRadius: '999px',
              }"
              :title="ensureZhihuState(sampleSelectedZhihu.id).enabled ? '点击暂停监测' : '点击启动监测'"
              @click="toggleMonitor('zhihu', sampleSelectedZhihu.id)"
            >
              <Icon
                :name="ensureZhihuState(sampleSelectedZhihu.id).enabled ? 'check' : 'play'"
                :size="13"
              />
              <span>
                {{ ensureZhihuState(sampleSelectedZhihu.id).enabled ? '监测进行中' : '启动监测' }}
              </span>
            </button>
            <!--
              监测定时：图标 + 文字 label 单独站一列，FormSelect 用自带
              的胶囊样式 —— 不再套一层有 bg/border 的外胶囊（之前那层是
              给原生 <select> 兜底的，FormSelect 已经自带卡片底了，叠
              两层会出现"框中框"双胶囊。
            -->
            <div class="flex flex-1 items-center gap-2">
              <Icon
                name="calendar"
                :size="13"
                :style="{ color: 'var(--ink-3)' }"
              />
              <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">监测定时</span>
              <FormSelect
                :model-value="ensureZhihuState(sampleSelectedZhihu.id).schedule"
                :options="SCHEDULE_OPTIONS"
                width="140"
                @update:model-value="(v) => changeSchedule('zhihu', sampleSelectedZhihu!.id, String(v))"
              />
            </div>
          </div>
        </template>

        <!--
          ════ 真实数据 · L2：单问题详情（openBatchName != null）════
          钻入某批次后点子任务行 → 右卡显示该问题的 KPI / 趋势 / 前 N 答案。
          维持原行为不变；只是把 v-else 收窄成 L2 专属分支，L1 走下面的
          批次详情面板。
        -->
        <template v-else-if="openBatchName != null">
          <div v-if="!selectedTask" class="text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
            点击左侧任意问题查看详情。
          </div>
          <template v-else>
            <!-- 头：问题名 + 链接 + 编辑（删除原来的「知乎问题」副标题 —— tab 已经说明了平台） -->
            <div class="flex flex-shrink-0 items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="font-display text-[14px] font-semibold">「{{ selectedTask.name }}」</div>
              </div>
              <div class="flex flex-shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  class="inline-flex items-center gap-1 px-3 py-1.5 text-[11.5px]"
                  :style="{
                    background: 'var(--card-2)',
                    color: 'var(--ink-2)',
                    border: '1px solid var(--line)',
                    borderRadius: '999px',
                  }"
                  title="编辑目标关键词 / Top-N / 计划"
                  @click="emit('edit-task', selectedTask)"
                >
                  <Icon name="edit" :size="12" />
                  <span>编辑</span>
                </button>
                <a
                  :href="selectedTask.target_url"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1 px-3 py-1.5 text-[11.5px]"
                  :style="{
                    background: 'var(--card-2)',
                    color: 'var(--ink-2)',
                    border: '1px solid var(--line)',
                    borderRadius: '999px',
                    textDecoration: 'none',
                  }"
                  title="在浏览器打开知乎问题"
                >
                  <Icon name="external" :size="12" />
                  <span>问题链接</span>
                </a>
              </div>
            </div>

            <!--
              KPI 五联：当前卡位 / 较上次变化 / 最高排名 / 浏览量 / 自家命中数
              注：当前卡位（#1）与自家命中数（#5）均来自 matched_count，
              数值相同——设计§4.3.1 要求五联，保留全部，QA 时可视需要合并为四联。
            -->
            <div class="mt-3 flex-shrink-0" :style="{ display: 'flex', flexWrap: 'wrap', gap: '8px' }">
              <!-- #1 当前卡位 -->
              <div
                :style="{
                  flex: '1 1 80px',
                  padding: '12px',
                  borderRadius: '12px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">当前卡位</div>
                <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                  <template v-if="taskSnapshots[selectedTask.id]?.latest">
                    <template v-if="taskSnapshots[selectedTask.id]!.latest!.matched_count > 0">
                      {{ taskSnapshots[selectedTask.id]!.latest!.matched_count }}
                    </template>
                    <span
                      v-else
                      :style="{ color: 'var(--red, #d85a48)', fontSize: '14px' }"
                    >前 {{ taskSnapshots[selectedTask.id]!.latest!.alert_top_n }} 以外</span>
                  </template>
                  <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                </div>
              </div>

              <!-- #2 较上次变化：latest.matched_count − prev.matched_count -->
              <div
                :style="{
                  flex: '1 1 80px',
                  padding: '12px',
                  borderRadius: '12px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">较上次变化</div>
                <div class="font-display mt-1 font-bold" :style="{ fontSize: '18px' }">
                  <template v-if="taskSnapshots[selectedTask.id]?.latest && taskSnapshots[selectedTask.id]?.prev">
                    <Pill
                      v-if="taskSnapshots[selectedTask.id]!.latest!.matched_count - taskSnapshots[selectedTask.id]!.prev!.matched_count > 0"
                      tone="ok"
                    >
                      <Icon name="arrowUp" :size="10" />
                      +{{ taskSnapshots[selectedTask.id]!.latest!.matched_count - taskSnapshots[selectedTask.id]!.prev!.matched_count }}
                    </Pill>
                    <Pill
                      v-else-if="taskSnapshots[selectedTask.id]!.latest!.matched_count - taskSnapshots[selectedTask.id]!.prev!.matched_count < 0"
                      tone="warn"
                    >
                      <Icon name="arrowDown" :size="10" />
                      {{ taskSnapshots[selectedTask.id]!.latest!.matched_count - taskSnapshots[selectedTask.id]!.prev!.matched_count }}
                    </Pill>
                    <Pill v-else tone="info">持平</Pill>
                  </template>
                  <span v-else :style="{ color: 'var(--ink-3)', fontSize: '14px' }">—</span>
                </div>
              </div>

              <!-- #3 最高排名 -->
              <div
                :style="{
                  flex: '1 1 80px',
                  padding: '12px',
                  borderRadius: '12px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">最高排名</div>
                <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                  <template v-if="taskSnapshots[selectedTask.id]?.latest && taskSnapshots[selectedTask.id]!.latest!.rank > 0">
                    第 {{ taskSnapshots[selectedTask.id]!.latest!.rank }} 名
                  </template>
                  <span
                    v-else-if="taskSnapshots[selectedTask.id]?.latest"
                    :style="{ color: 'var(--ink-3)', fontSize: '14px' }"
                  >未上榜</span>
                  <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                </div>
              </div>

              <!-- #4 浏览量 -->
              <div
                :style="{
                  flex: '1 1 80px',
                  padding: '12px',
                  borderRadius: '12px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">浏览量</div>
                <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                  <template v-if="taskSnapshots[selectedTask.id]?.latest">
                    {{ formatVisitCount(taskSnapshots[selectedTask.id]!.latest!.question_visit_count) }}
                  </template>
                  <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                </div>
              </div>

              <!-- #5 自家命中数（= matched_count，与#1数值相同，保留作语义区分） -->
              <div
                :style="{
                  flex: '1 1 80px',
                  padding: '12px',
                  borderRadius: '12px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">自家命中数</div>
                <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                  <template v-if="taskSnapshots[selectedTask.id]?.latest">
                    <span :style="{ color: 'var(--primary-deep)' }">
                      {{ taskSnapshots[selectedTask.id]!.latest!.matched_count }}
                    </span>
                  </template>
                  <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                </div>
              </div>
            </div>

            <!--
              趋势（左）+ 答案列表（右）并排
              - 宽屏：2 列 gridTemplateColumns 1fr / 1.05fr
              - 窄屏（< 640px）：单列堆叠
              趋势 chart 和答案列表 data binding 保持不变。
            -->
            <div
              class="mt-4 min-h-0 flex-1"
              :style="{
                display: 'grid',
                gridTemplateColumns: l2Wide ? '1fr 1.05fr' : '1fr',
                gap: '16px',
                alignItems: 'start',
              }"
            >
              <!-- 左：7 天卡位趋势 -->
              <div class="flex-shrink-0">
                <div class="mb-2 text-[12px] font-semibold">最近 7 天卡位趋势</div>
                <!--
                  Y 轴上限锁 selectedTopN —— 命中条数的容量上限是 Top-N，
                  让趋势相对"满格"显示。chart.js auto-scale 在低基数（命中
                  0-2 条）时会把数据顶到天花板，视觉夸张，不直观。
                -->
                <LineChart
                  :labels="sparkChartLabels"
                  :series="[
                    {
                      label: '卡位数量',
                      color: 'var(--primary-deep, #c9521f)',
                      data: sparkPoints,
                    },
                  ]"
                  :y-max="selectedTopN"
                />
              </div>

              <!-- 右：前 N 条答案 -->
              <div class="overflow-y-auto" :style="{ maxHeight: l2Wide ? '360px' : 'none' }">
                <div class="mb-2 flex items-center justify-between">
                  <div class="text-[12px] font-semibold">
                    前
                    {{ taskSnapshots[selectedTask.id]?.latest?.alert_top_n ?? topAnswersForSelectedTask.length }}
                    条答案
                  </div>
                </div>
                <template v-if="topAnswersForSelectedTask.length">
                  <div
                    v-for="(x, i) in topAnswersForSelectedTask"
                    :key="i"
                    class="mb-1.5 flex items-center gap-3"
                    :style="{
                      padding: '10px',
                      borderRadius: '10px',
                      background: x.matches_brand ? 'var(--primary-soft)' : 'var(--card-2)',
                      border: '1px solid '
                        + (x.matches_brand ? 'rgba(238,106,42,0.3)' : 'var(--line)'),
                    }"
                  >
                    <span
                      class="font-display text-[13px] font-bold"
                      :style="{
                        width: '22px',
                        color: x.matches_brand ? 'var(--primary-deep)' : 'var(--ink-2)',
                      }"
                    >#{{ x.rank }}</span>
                    <div class="min-w-0 flex-1">
                      <div class="truncate text-[12.5px] font-medium">
                        {{ x.content_preview || "（无摘要）" }}
                      </div>
                      <div class="flex items-center gap-2 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                        <span>{{ x.author || "—" }}</span>
                        <span v-if="x.voteup_count">· 👍 {{ x.voteup_count }}</span>
                        <span
                          v-if="x.matches_brand"
                          class="ml-auto"
                          :style="{ color: 'var(--primary-deep)', fontWeight: 600 }"
                        >自家</span>
                      </div>
                    </div>
                  </div>
                </template>
                <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
                  暂无快照数据 —— 跑一次「立刻监测」，下方将列出当前榜上的前 N 个答案，命中目标品牌的会高亮。
                </div>
              </div>
            </div>
          </template>
        </template>

        <!--
          ════ 真实数据 · L1：批次详情面板（openBatchName == null）════
          对齐 BaiduRankingPage 右卡 master-detail：批次名标题 + 「任务详情」
          eyebrow、问题数量、目标品牌，底部 pinned「导出数据 / 定时监测」。
          按用户明确要求：没有趋势图。selectedBatch 由左侧批次「行」点击选中
          （fallback 第一条），批次名链接负责钻入 L2。
        -->
        <template v-else>
          <div
            v-if="!selectedBatch"
            class="flex flex-1 flex-col items-center justify-center text-center"
            :style="{ color: 'var(--ink-3)' }"
          >
            <div class="mb-1 text-[14px] font-medium">暂无批次</div>
            <div class="text-[11.5px]">点击「批量导入」或「新建任务」开始监测</div>
          </div>

          <template v-else>
            <!-- 标题：批次名 + 「批次汇总」eyebrow -->
            <div class="mb-3 flex-shrink-0">
              <div class="font-display text-[14px] font-semibold">{{ selectedBatch.name }}</div>
              <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                批次汇总
              </div>
            </div>

            <!-- 滚动区：KPI 四联 + 问题概览表 + 导出/定时 -->
            <div class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">

              <!-- KPI 四联 —— 与 L2 二联 同款 card 样式 -->
              <div class="grid grid-cols-2 gap-3">
                <!-- 问题数 -->
                <div
                  :style="{
                    padding: '12px',
                    borderRadius: '12px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">问题数</div>
                  <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                    {{ selectedBatch.tasks.length }}
                  </div>
                </div>

                <!-- 目标品牌 -->
                <div
                  :style="{
                    padding: '12px',
                    borderRadius: '12px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">目标品牌</div>
                  <div class="font-display mt-1 font-bold" :style="{ fontSize: '16px' }">
                    {{ selectedBatchBrand || '—' }}
                  </div>
                </div>

                <!-- 命中问题数 -->
                <div
                  :style="{
                    padding: '12px',
                    borderRadius: '12px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">命中问题数</div>
                  <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                    <template v-if="selectedBatchKpis">
                      {{ selectedBatchKpis.hitQuestions }}<span :style="{ color: 'var(--ink-3)', fontSize: '13px' }">/{{ selectedBatchKpis.total }}</span>
                    </template>
                    <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                  </div>
                </div>

                <!-- 平均卡位 -->
                <div
                  :style="{
                    padding: '12px',
                    borderRadius: '12px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">平均卡位</div>
                  <div class="font-display mt-1 font-bold" :style="{ fontSize: '20px' }">
                    <template v-if="selectedBatchKpis?.avgRank != null">
                      第 {{ selectedBatchKpis.avgRank }} 名
                    </template>
                    <span v-else :style="{ color: 'var(--ink-3)', fontSize: '14px' }">—</span>
                  </div>
                </div>
              </div>

              <!-- 问题概览速查表 -->
              <div>
                <div
                  class="mb-2 text-[10.5px] uppercase"
                  :style="{ color: 'var(--ink-3)', letterSpacing: '1px' }"
                >问题概览</div>
                <div
                  :style="{
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                    overflow: 'hidden',
                  }"
                >
                  <!-- 表头 -->
                  <div
                    class="grid text-[10.5px]"
                    :style="{
                      gridTemplateColumns: '1fr 48px 64px',
                      padding: '5px 10px',
                      background: 'var(--card-2)',
                      color: 'var(--ink-3)',
                      borderBottom: '1px solid var(--line)',
                    }"
                  >
                    <span>问题名</span>
                    <span :style="{ textAlign: 'right' }">卡位</span>
                    <span :style="{ textAlign: 'right' }">最高排名</span>
                  </div>
                  <!-- 每行 -->
                  <div
                    v-for="t in selectedBatch.tasks"
                    :key="t.id"
                    class="grid text-[11.5px]"
                    :style="{
                      gridTemplateColumns: '1fr 48px 64px',
                      padding: '6px 10px',
                      borderBottom: '1px solid var(--line)',
                      color: 'var(--ink-2)',
                    }"
                  >
                    <span
                      class="truncate pr-2"
                      :title="subtaskTitle(t)"
                      :style="{ color: 'var(--ink)' }"
                    >{{ subtaskTitle(t) }}</span>
                    <span :style="{ textAlign: 'right', color: 'var(--ink-2)' }">
                      {{ props.taskSnapshots[t.id]?.latest?.matched_count ?? 0 }}
                    </span>
                    <span :style="{ textAlign: 'right', color: 'var(--ink-2)' }">
                      <template v-if="props.taskSnapshots[t.id]?.latest && (props.taskSnapshots[t.id]!.latest!.rank ?? -1) > 0">
                        第 {{ props.taskSnapshots[t.id]!.latest!.rank }} 名
                      </template>
                      <span v-else :style="{ color: 'var(--ink-3)', fontSize: '10.5px' }">未进榜</span>
                    </span>
                  </div>
                </div>
              </div>

              <!-- 导出数据 / 定时监测 -->
              <div class="flex flex-shrink-0 gap-2">
                <button
                  type="button"
                  class="flex-1 text-[12.5px] font-medium"
                  :style="{
                    padding: '9px 14px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                    borderRadius: '8px',
                    color: 'var(--ink-2)',
                    cursor: 'pointer',
                  }"
                  @click="exportBatchCsv(selectedBatch)"
                >导出数据</button>
                <button
                  type="button"
                  class="flex-1 text-[12.5px] font-medium"
                  :style="{
                    padding: '9px 14px',
                    background: 'var(--primary)',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '8px',
                    cursor: 'pointer',
                  }"
                  @click="scheduleBatch(selectedBatch)"
                >定时监测</button>
              </div>

            </div>
          </template>
        </template>
      </section>
      </template>
    </SplitPane>
  </div>
</template>
