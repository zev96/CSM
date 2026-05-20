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
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";
import { formatTimelineTime, formatRelativeTime } from "@/utils/monitor-batch";
import {
  type TaskSnapshotPair,
} from "@/utils/monitor-snapshot";
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

const SAMPLE_SPARK_RANK: number[] = [];

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
  (e: "delete-task", taskId: number): void;
  (e: "run-task", taskId: number): void;
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

async function loadResults(taskId: number) {
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 14 },
    });
    taskResults.value = r.data.results ?? [];
  } catch {
    taskResults.value = [];
  }
}

// Sparkline 横轴日期 —— 用今天往回推 N 天，演示模式下纯前端生成。
function daysAgoLabels(count: number, totalSpan: number): string[] {
  // count: 想显示几个标签；totalSpan: 数据覆盖多少天
  const out: string[] = [];
  const now = new Date();
  for (let i = 0; i < count; i++) {
    const offset = Math.round(((count - 1 - i) / (count - 1)) * (totalSpan - 1));
    const d = new Date(now.getTime() - offset * 24 * 60 * 60 * 1000);
    out.push(`${d.getMonth() + 1}/${d.getDate()}`);
  }
  return out;
}
const ZHIHU_SPARK_LABELS = daysAgoLabels(5, 14); // 14 次快照横跨 14 天

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

// 卡位趋势（Y 轴 = matched_count）—— 之前用 rank（越小越好），现在统一
// 改成命中数语义跟新 KPI「卡位数量」对齐。无 metric 的旧 result 当 0 处理。
const sparkPoints = computed(() => {
  if (props.demoMode) return SAMPLE_SPARK_RANK;
  return [...taskResults.value]
    .reverse()
    .map((r) => Number((r as any).metric?.matched_count ?? 0));
});

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
  <div>
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
          color: '#fbf7ec',
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

    <!-- table + detail -->
    <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
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
            <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              问题列表
            </div>
          </div>
          <div class="flex flex-shrink-0 gap-2">
            <button
              type="button"
              class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px]"
              :style="{
                background: 'transparent',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
              }"
              @click="emit('cookie-mgr')"
            >
              <Icon name="key" :size="12" />
              <span>Cookie</span>
            </button>
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
              <span>新增任务</span>
            </button>
          </div>
        </div>

        <!-- scrollable table body — fills remaining vertical space -->
        <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <!--
          5-column header row —— 删掉「状态」列（卡位 / 变化 已经覆盖了
          上榜与否，状态 pill 是冗余信号）。非主名列统一 0.7fr 等宽，
          类型 / 操作 列文字居中，对齐下方 icon 组。
        -->
        <div
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
          <div>卡位</div>
          <div>变化</div>
          <div class="text-center">操作</div>
        </div>

        <!-- demo empty state — SAMPLE_ZHIHU 发布前已清空，首次启动展示空态 -->
        <template v-if="demoMode && SAMPLE_ZHIHU.length === 0">
          <div
            class="py-10 text-center text-[12.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            暂无监测任务 · 点击「新增任务」开始监测
          </div>
        </template>

        <!-- demo rows —— 5 cols (状态列已移除) -->
        <template v-else-if="demoMode">
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
            <div class="font-display text-[13px] font-bold">
              {{ t.lastRank == null ? "—" : `#${t.lastRank}` }}
            </div>
            <div>
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

        <!-- real rows —— 与 demo 5 列对齐：名字 / 类型 / 上次 / 变化 / 状态+操作 -->
        <!--
          状态+操作那一列要容纳 pill + "立刻监测" + 编辑 + 删除 4 个元
          素，原来 .6fr 太窄会把"立刻监测"压成两行。最后一列改成 1.4fr
          （是 .6fr 的 2 倍多），其它列等比缩窄，名字仍最宽。
        -->
        <template v-else>
          <div
            v-for="(t, i) in tasks"
            :key="t.id"
            class="grid cursor-pointer items-center transition"
            :style="{
              gridTemplateColumns: '1.6fr .7fr .7fr .7fr 1fr',
              background: selectedTaskId === t.id ? 'var(--card-2)' : 'transparent',
              borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
              borderRadius: '10px',
            }"
            @click="selectedTaskId = t.id"
          >
            <div class="truncate text-[13px] font-medium">{{ t.name }}</div>
            <!-- 类型：知乎问题 → 问题，居中 -->
            <div class="text-center text-[12px]" :style="{ color: 'var(--ink-2)' }">问题</div>
            <!--
              卡位：matched_count 单值（不再 X/N 分母 + 最高#N 副标）。
              跟右卡「卡位数量」语义保持一致。命中 0 → "前 N 以外"红字。
            -->
            <div class="font-display text-[13px] font-bold">
              <template v-if="taskSnapshots[t.id]?.latest">
                <template v-if="taskSnapshots[t.id]!.latest!.matched_count > 0">
                  <span>{{ taskSnapshots[t.id]!.latest!.matched_count }}</span>
                </template>
                <span
                  v-else
                  :style="{ color: 'var(--red, #d85a48)', fontSize: '12px', fontWeight: 'normal' }"
                >前 {{ taskSnapshots[t.id]!.latest!.alert_top_n }} 以外</span>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>
            <!--
              变化：用命中数 delta 而不是 rank delta —— 用户的心智模型
              是"我们家这次有几条上榜、上次有几条"。+1 = 多一条占位，
              -1 = 少一条；持平不显 pill。
            -->
            <div>
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
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>
            <!--
              操作 cell —— 状态列已移除（卡位 / 变化 已经反映上榜状态）。
              三个 icon 居中：
                ▶ 立刻监测（监测中 → ⏹ stop, 点击发取消）  /  ✎ 编辑  /  🗑 删除
              running 状态由 monitorStatus store 提供，跨页面导航不丢。
            -->
            <div class="flex items-center justify-center gap-1">
              <button
                v-if="runningTaskIds[t.id]"
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{
                  borderRadius: '999px',
                  color: 'var(--red, #d85a48)',
                  cursor: 'pointer',
                }"
                title="停止监测"
                @click.stop="emit('cancel-task', t.id)"
              >
                <Icon name="x" :size="13" />
              </button>
              <button
                v-else
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{
                  borderRadius: '999px',
                  color: 'var(--primary-deep)',
                  cursor: 'pointer',
                }"
                title="立刻监测"
                @click.stop="emit('run-task', t.id)"
              >
                <Icon name="play" :size="13" />
              </button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{
                  borderRadius: '999px',
                  color: 'var(--ink-3)',
                }"
                title="编辑任务（目标关键词 / Top-N / 计划）"
                @click.stop="emit('edit-task', t)"
              >
                <Icon name="edit" :size="13" />
              </button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{
                  borderRadius: '999px',
                  color: 'var(--ink-3)',
                }"
                title="删除任务"
                @click.stop="emit('delete-task', t.id)"
              >
                <Icon name="trash" :size="13" />
              </button>
            </div>
          </div>
        </template>
        </div>
      </section>

      <!-- detail card —— min-h-0 + overflow-y-auto 把详情滚动锁在卡内 -->
      <section
        class="flex h-full min-h-0 flex-col overflow-y-auto"
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
            <div class="mb-2 text-[12px] font-semibold">最近 14 次快照</div>
            <Sparkline
              :points="sparkPoints"
              :width="380"
              :height="70"
              stroke="var(--red, #d85a48)"
              :axis-labels="ZHIHU_SPARK_LABELS"
              fluid
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

        <template v-else>
          <div v-if="!selectedTask" class="text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
            点击左侧任意任务查看详情。
          </div>
          <template v-else>
            <!-- 头：问题名 + 链接 + 编辑（删除原来的「知乎问题」副标题 —— tab 已经说明了平台） -->
            <div class="flex items-start justify-between gap-2">
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
              KPI 二联：卡位数量 / 最高排名
              - 卡位数量 = 前 N 条答案里包含目标品牌词的条数（单值，不再 N/M）
              - 最高排名 = result.rank（自家最高排到第几名）；命中 0 → 「未上榜」
              - 检查频率已移除 —— 用户通过编辑任务设置定时。
            -->
            <div class="mt-3 grid grid-cols-2 gap-3">
              <div
                :style="{
                  padding: '12px',
                  borderRadius: '12px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">卡位数量</div>
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
              <div
                :style="{
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
            </div>

            <!--
              14 天卡位趋势：Y 轴 = matched_count（卡位数），越高越好。
              之前的 Y 轴 = rank（越低越好）容易误读，跟新 KPI「卡位数量」
              语义保持一致。
            -->
            <div class="mt-5">
              <div class="mb-2 text-[12px] font-semibold">最近 14 天卡位趋势</div>
              <Sparkline
                v-if="sparkPoints.length"
                :points="sparkPoints"
                :width="380"
                :height="70"
                stroke="var(--primary-deep, #c9521f)"
                :axis-labels="ZHIHU_SPARK_LABELS"
                fluid
              />
              <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
                无历史数据 —— 跑过几次"立刻监测"才能成线。
              </div>
            </div>

            <!--
              前 N 条答案 —— 从 taskResults[0].metric.answers 取全部。
              每条左侧带排名 #N，命中目标品牌的行用 primary-soft 背景 +
              橙色描边高亮，右侧角标"自家"。让用户一眼看出"前 N 条里
              我占了哪几位"——这是用户描述的核心需求。
            -->
            <div class="mt-4">
              <div class="mb-2 flex items-center justify-between">
                <div class="text-[12px] font-semibold">
                  前
                  {{ taskSnapshots[selectedTask.id]?.latest?.alert_top_n ?? topAnswersForSelectedTask.length }}
                  条答案
                </div>
                <div
                  v-if="taskSnapshots[selectedTask.id]?.latest"
                  class="text-[11px]"
                  :style="{ color: 'var(--ink-3)' }"
                >
                  自家命中
                  <span :style="{ color: 'var(--primary-deep)', fontWeight: 600 }">
                    {{ taskSnapshots[selectedTask.id]!.latest!.matched_count }}
                  </span>
                  条
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
          </template>
        </template>
      </section>
    </div>
  </div>
</template>
