<script setup lang="ts">
/**
 * 评论 tab —— 监测中心的"平台评论"子模块。
 *
 * 从 MonitorView.vue（约 858 行的评论 tab 整段）拆出来，独立维护：
 *   - 三级导航（任务批次 L1 / 视频列表 L2 / 单视频详情 L3）
 *   - commentAlerts hero（卡片堆叠 + chevron 翻页）
 *   - 留存趋势 sparkline / 被删评论列表
 *   - 评论批次的批量操作（立刻监测 / 取消 / 编辑 / 删除）
 *
 * 父组件 MonitorView 通过 props 注入 tasks / taskSnapshots / commentSubtab /
 * runningTaskIds 等"跨 tab 共享"状态；evil 跨域操作（打开 modal、打开
 * AlertDetailModal、cycleAlert）由模块 emit 给父组件兜底，保持单一 modal 树。
 *
 * 拆分前后零行为改动：template 一字不改，computed / function 体内的
 * 逻辑原样保留；只是把 watch / open* 流程的入口换成 defineExpose 让
 * 父组件的 goToCommentTask 仍能从模块外驱动 L2 / L3 选中。
 */
import { computed, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useToast } from "@/composables/useToast";
import {
  parseBatchName,
  statusFromRatio,
  formatRelativeTime,
} from "@/utils/monitor-batch";
import {
  type TaskSnapshotPair,
} from "@/utils/monitor-snapshot";
import {
  type Task,
  type CommentPlatform,
  type SampleComment,
  type VideoEntry,
  type CommentAlertData,
  type AlertDeletedComment,
  type HeroAlert,
  type MonitorState,
  SCHEDULE_OPTIONS,
  scheduleLabel,
} from "@/utils/monitor-types";

const props = defineProps<{
  tasks: Task[];
  taskSnapshots: Record<number, TaskSnapshotPair>;
  commentSubtab: CommentPlatform;
  loading: boolean;
  failed: boolean;
  runningTaskIds: Record<number, true>;
  demoMode: boolean;
  activeTab: string;
}>();

const emit = defineEmits<{
  (e: "update:commentSubtab", v: CommentPlatform): void;
  (e: "add-task"): void;
  (e: "import-batch"): void;
  (e: "edit-batch", batchName: string): void;
  (e: "delete-batch", batchName: string): void;
  (e: "run-batch", batchName: string): void;
  (e: "cancel-batch", batchName: string): void;
  (e: "run-now", taskId: number): void;
  (e: "alert-action", action: "rescue" | "repost" | "close"): void;
  (e: "open-alert", payload: { kind: "comment_alert"; data: CommentAlertData | null }): void;
  (e: "cycle-alert", dir: 1 | -1): void;
}>();

const toast = useToast();

// 评论 tab 三级导航：
//   selectedCommentTaskId  —— 一级 → 二级（左列从任务列表换成视频列表）
//   selectedVideoId        —— 二级 → 三级（右列从汇总图换成单视频详情）
// 两者都是字符串 id，分别对应 commentRows / videosByBatchId 里的 id。
const selectedCommentTaskId = ref<string | null>(null);
const selectedVideoId = ref<string | null>(null);

// ── 告警 hero index（cycleAlert 切上一条 / 下一条 by 父组件 emit） ─────
const commentAlertIdx = ref(0);

// 平台 chip 计数清零 —— V1 设计稿示例任务已清空，发布前保留空状态。
const PLATFORMS: Array<{ k: CommentPlatform; l: string; color: string; count: number }> = [
  { k: "bilibili", l: "B 站", color: "#ee6a2a", count: 0 },
  { k: "douyin", l: "抖音", color: "#1e1c19", count: 0 },
  { k: "kuaishou", l: "快手", color: "#f5c042", count: 0 },
];

// Sparkline 横轴日期 —— 用今天往回推 N 天，演示模式下纯前端生成。
function daysAgoLabels(count: number, totalSpan: number): string[] {
  const out: string[] = [];
  const now = new Date();
  for (let i = 0; i < count; i++) {
    const offset = Math.round(((count - 1 - i) / (count - 1)) * (totalSpan - 1));
    const d = new Date(now.getTime() - offset * 24 * 60 * 60 * 1000);
    out.push(`${d.getMonth() + 1}/${d.getDate()}`);
  }
  return out;
}
const COMMENT_SPARK_LABELS = daysAgoLabels(7, 7); // 7 天留存

// V1 设计稿示例数据，发布前清空保留空状态 —— 三个平台默认全空，
// SAMPLE_COMMENTS[platform].length === 0 时模板会渲染"还没有监测任务"。
const SAMPLE_COMMENTS: Record<CommentPlatform, SampleComment[]> = {
  bilibili: [],
  douyin: [],
  kuaishou: [],
};
const SAMPLE_VIDEOS: Record<string, VideoEntry[]> = {};
const SAMPLE_RETENTION: number[] = [];
const SAMPLE_DELETED: Array<{ tag: string; who: string; date: string; tone: "alert" | "warn" }> = [];

// 监测启停 + 频率 —— 演示模式下保存在本地 ref 里。每个任务一份独立设置，
// 切任务不会丢状态。
const commentMonitorState = ref<Record<string, MonitorState>>({
  "s-b1": { enabled: false, schedule: "hourly-1" },
  "s-b2": { enabled: false, schedule: "hourly-6" },
  "s-b3": { enabled: false, schedule: "daily-09:00" },
});

function ensureCommentState(id: string): MonitorState {
  if (!commentMonitorState.value[id]) {
    commentMonitorState.value[id] = { enabled: false, schedule: "daily-09:00" };
  }
  return commentMonitorState.value[id];
}
function toggleMonitor(scope: "zhihu" | "comment", id: string) {
  // 模块内只处理 comment 域；保留 scope 形参让 template 调用签名不变。
  void scope;
  const st = ensureCommentState(id);
  st.enabled = !st.enabled;
  toast.info(`已${st.enabled ? "启动" : "暂停"}监测`);
}
function changeSchedule(scope: "zhihu" | "comment", id: string, v: string) {
  void scope;
  const st = ensureCommentState(id);
  st.schedule = v;
  toast.success(`监测频率：${scheduleLabel(v)}`);
}

function truncate15(s: string): string {
  return s.length > 15 ? `${s.slice(0, 15)}…` : s;
}

// ── Real-data unifiers ────────────────────────────────────────────────
//
// 这一段是把后端真实 task + snapshot 数据"塑形"成原来 demo 用的
// SampleComment / VideoEntry 形状，让下面的 rich UI 模板不需要重写。
// 切换 demoMode 时只换数据源，不动模板。
const realCommentRows = computed<SampleComment[]>(() => {
  if (props.demoMode) return [];
  // group tasks by batch name
  const byBatch = new Map<string, Task[]>();
  for (const t of props.tasks) {
    const b = parseBatchName(t.name);
    const arr = byBatch.get(b) ?? [];
    arr.push(t);
    byBatch.set(b, arr);
  }
  const out: SampleComment[] = [];
  for (const [batchName, batchTasks] of byBatch) {
    let matchedNow = 0;
    let matchedPrev = 0;
    let havePrev = false;
    let latestCheck: string | null = null;
    for (const t of batchTasks) {
      const pair = props.taskSnapshots[t.id];
      if (pair?.latest?.matched) matchedNow++;
      if (pair?.prev) {
        havePrev = true;
        if (pair.prev.matched) matchedPrev++;
      }
      const ts = pair?.latest?.checked_at || t.last_check_at;
      if (ts && (!latestCheck || ts > latestCheck)) latestCheck = ts;
    }
    out.push({
      id: batchName,
      kw: batchName,
      lastChecked: formatRelativeTime(latestCheck),
      retained: matchedNow,
      total: batchTasks.length,
      delta: havePrev ? matchedNow - matchedPrev : 0,
      status: statusFromRatio(matchedNow, batchTasks.length),
    });
  }
  // 按状态严重度 → 留存率升序排：先看告警的
  const severityOrder = { alert: 0, warn: 1, ok: 2 } as const;
  out.sort((a, b) => {
    const s = severityOrder[a.status] - severityOrder[b.status];
    if (s !== 0) return s;
    const ra = a.total ? a.retained / a.total : 1;
    const rb = b.total ? b.retained / b.total : 1;
    return ra - rb;
  });
  return out;
});

// L2 视频列表 —— 把每个批次内的 tasks 塑形成 VideoEntry
//
// 状态规则（与后端 alert_top_n / scrape_top_n 拆分对齐）：
//   matched && rank <= alert_top_n → "ok"      在显且在理想范围内
//   matched && rank >  alert_top_n → "folded"  在显但跌出理想（前端文案"跌出 #N"）
//   !matched                        → "deleted" 没在前 scrape_top_n 条命中（被删 / 折叠 / 没爬到均落此态，UI 显示"无 / 未找到"）
const realVideosByBatchId = computed<Record<string, VideoEntry[]>>(() => {
  if (props.demoMode) return {};
  const map: Record<string, VideoEntry[]> = {};
  for (const t of props.tasks) {
    const b = parseBatchName(t.name);
    const snap = props.taskSnapshots[t.id]?.latest;
    const matched = snap?.matched ?? false;
    const rank = snap?.rank ?? -1;
    const alertN = snap?.alert_top_n ?? 5;
    const status: VideoEntry["status"] =
      matched
        ? rank > 0 && rank <= alertN ? "ok" : "folded"
        : "deleted";
    const urlTail = t.name.includes(" - ")
      ? t.name.slice(t.name.lastIndexOf(" - ") + 3)
      : t.name;
    const entry: VideoEntry = {
      id: `task-${t.id}`,
      url: t.target_url,
      title: urlTail || t.target_url,
      myComment: snap?.my_comment_text ?? "—",
      rank: rank > 0 ? rank : 0,
      status,
      postedAt: t.last_check_at ? new Date(t.last_check_at).toLocaleDateString() : "—",
      totalComments: snap?.total_fetched ?? 0,
    };
    (map[b] ||= []).push(entry);
  }
  return map;
});

// 把 video.id 反查回 task.id 用，L3 单视频 SSE / 立刻跑要原数字 id
function realTaskIdFromVideoId(videoId: string): number | null {
  const m = /^task-(\d+)$/.exec(videoId);
  return m ? Number(m[1]) : null;
}

// 留存趋势 sparkline —— 用 task.id 维度的"每次检查 matched 占比"作为
// 一条折线。真实数据下，未选批次时聚合所有任务、选中批次时只聚合该批次。
//
// 简化：用每条 task 的最近 N 次 result（已经 fetch 了 latest+prev，再
// 临时拉 limit=14）；按 checked_at 桶 7 天。先用 latest+prev 两点做兜底
// （能看到趋势但不够细），后面想细可以再拉历史。
const realRetentionPoints = computed<number[]>(() => {
  if (props.demoMode) return [];
  // 选中批次时只看该批次
  const scope: Task[] = selectedCommentTaskId.value
    ? props.tasks.filter((t) => parseBatchName(t.name) === selectedCommentTaskId.value)
    : props.tasks;
  if (!scope.length) return [];
  // 两个点：prev 与 latest 的 matched 占比 ×100
  let mNow = 0, nNow = 0, mPrev = 0, nPrev = 0;
  for (const t of scope) {
    const pair = props.taskSnapshots[t.id];
    if (pair?.latest) {
      nNow++;
      if (pair.latest.matched) mNow++;
    }
    if (pair?.prev) {
      nPrev++;
      if (pair.prev.matched) mPrev++;
    }
  }
  const points: number[] = [];
  if (nPrev > 0) points.push(Math.round((mPrev / nPrev) * 100));
  if (nNow > 0) points.push(Math.round((mNow / nNow) * 100));
  // 单点没法画线；补一个相同值让 sparkline 不至于空
  if (points.length === 1) points.unshift(points[0]);
  return points;
});

// 被删评论列表 —— scope 同上：未选批次=所有任务、选中批次=该批次
const realDeletedComments = computed(() => {
  if (props.demoMode) return [] as Array<{ tag: string; who: string; date: string; tone: "alert" | "warn" }>;
  const scope: Task[] = selectedCommentTaskId.value
    ? props.tasks.filter((t) => parseBatchName(t.name) === selectedCommentTaskId.value)
    : props.tasks;
  const items: Array<{ tag: string; who: string; date: string; tone: "alert" | "warn" }> = [];
  for (const t of scope) {
    const snap = props.taskSnapshots[t.id]?.latest;
    if (!snap) continue;
    if (snap.matched) continue; // 留存中，跳过
    // 抢占者：matched=false 时 hot_comments[0] 就是 top1（不是我）
    const top1 = snap.hot_comments?.[0];
    const grabber = top1?.author || top1?.nickname || "—";
    const tone: "alert" | "warn" = snap.rank > 0 ? "warn" : "alert";
    items.push({
      tag: tone === "alert" ? "被删" : "折叠",
      who: `@${grabber}（${snap.my_comment_text.slice(0, 16)}${snap.my_comment_text.length > 16 ? "…" : ""}）`,
      date: snap.checked_at ? new Date(snap.checked_at).toLocaleDateString() : "—",
      tone,
    });
  }
  // 最近发生的排前面
  items.sort((a, b) => (a.date < b.date ? 1 : -1));
  return items;
});

// ── Unified data source ──────────────────────────────────────────────
// 模板里统一引用这 4 个 computed —— demoMode 时拿示例、否则拿真实数据。
// 这样模板不需要 v-if="demoMode" 来回切两套布局。
const commentRows = computed<SampleComment[]>(() =>
  props.demoMode ? SAMPLE_COMMENTS[props.commentSubtab] : realCommentRows.value,
);
const videosByBatchId = computed<Record<string, VideoEntry[]>>(() =>
  props.demoMode ? SAMPLE_VIDEOS : realVideosByBatchId.value,
);
const retentionPoints = computed<number[]>(() =>
  props.demoMode ? SAMPLE_RETENTION : realRetentionPoints.value,
);
const deletedComments = computed(() =>
  props.demoMode ? SAMPLE_DELETED : realDeletedComments.value,
);

const selectedCommentRow = computed(() =>
  selectedCommentTaskId.value
    ? commentRows.value.find((c) => c.id === selectedCommentTaskId.value) ?? null
    : null,
);
const selectedTaskVideos = computed<VideoEntry[]>(() =>
  selectedCommentTaskId.value
    ? videosByBatchId.value[selectedCommentTaskId.value] ?? []
    : [],
);
const selectedVideo = computed<VideoEntry | null>(() => {
  if (!selectedVideoId.value) return null;
  return selectedTaskVideos.value.find((v) => v.id === selectedVideoId.value) ?? null;
});

// ── 告警 hero（comment）computed ───────────────────────────────────────
//
// V1 设计稿那条红黑底「N 个紧急告警」卡片：从真实数据派生 ——
// comment ⇒ batch 整体 status === "alert"（留存率 < 60%）。
// 最多堆 3 张 hero（match 设计稿的卡片堆叠），多了用户在 chevron 切。
const commentAlerts = computed<HeroAlert[]>(() => {
  if (props.demoMode || props.activeTab !== "comment") return [];
  const out: HeroAlert[] = [];
  for (const r of realCommentRows.value) {
    if (r.status !== "alert") continue;
    const dropped = r.total - r.retained;
    const ratio = r.total > 0 ? Math.round((r.retained / r.total) * 100) : 0;
    out.push({
      keyword: r.kw,
      headline: `评论被删 ${dropped} 条 · 留存跌至 ${ratio}%`,
      subtitle: `${r.lastChecked} · ${r.total} 条视频`,
      batchName: r.id,
    });
    if (out.length >= 3) break;
  }
  return out;
});
const currentCommentAlert = computed(() => commentAlerts.value[commentAlertIdx.value]);

function _buildCommentAlertData(batchName: string, alert: HeroAlert): CommentAlertData | null {
  const childTasks = props.tasks.filter((t) => parseBatchName(t.name) === batchName);
  if (!childTasks.length) return null;
  let retained = 0;
  let prevRetained = 0;
  let havePrev = false;
  const deleted: AlertDeletedComment[] = [];
  for (const t of childTasks) {
    const pair = props.taskSnapshots[t.id];
    const snap = pair?.latest;
    const prev = pair?.prev;
    if (snap?.matched) retained++;
    if (prev) {
      havePrev = true;
      if (prev.matched) prevRetained++;
    }
    if (snap && !snap.matched) {
      const top1 = snap.hot_comments?.[0];
      const grabber = (top1 as any)?.author || (top1 as any)?.nickname || "—";
      deleted.push({
        who: `@${grabber}`,
        text: snap.my_comment_text || "（无原文）",
        date: snap.checked_at ? new Date(snap.checked_at).toLocaleDateString() : "—",
        state: snap.rank > 0 ? "折叠" : "被删",
      });
    }
  }
  const total = childTasks.length;
  const ratio = total > 0 ? Math.round((retained / total) * 100) : 0;
  // sparkline：暂时只两点（latest / prev 留存率）；若无 prev 单点 fallback
  const sparkPoints: number[] = [];
  if (havePrev) {
    sparkPoints.push(Math.round((prevRetained / total) * 100));
  }
  sparkPoints.push(ratio);
  const platformLabel =
    childTasks[0].type === "bilibili_comment" ? "B 站"
    : childTasks[0].type === "douyin_comment" ? "抖音"
    : childTasks[0].type === "kuaishou_comment" ? "快手" : "评论";
  return {
    title: `「${batchName}」评论留存告警`,
    subtitle: `${platformLabel} · ${alert.subtitle}`,
    retained,
    total,
    ratio,
    recentDelta: havePrev ? retained - prevRetained : 0,
    prevRetained: havePrev ? prevRetained : null,
    sparkPoints,
    sparkAxis: [], // 两点没必要画轴
    deleted,
  };
}

function openCommentAlert(alert?: HeroAlert) {
  const a = alert ?? currentCommentAlert.value;
  const data = a?.batchName ? _buildCommentAlertData(a.batchName, a) : null;
  emit("open-alert", { kind: "comment_alert", data });
}

// cycle hero alerts — wrap-around 让用户在 1↔️N 来回切不会被卡住。
function cycleAlert(_kind: "zhihu" | "comment", dir: 1 | -1) {
  const list = commentAlerts.value;
  if (!list.length) return;
  commentAlertIdx.value = (commentAlertIdx.value + dir + list.length) % list.length;
  // 同时通知父组件，让其他 tab（如 zhihu）共享的告警 chevron 行为保持一致
  emit("cycle-alert", dir);
}

function openCommentDetail(taskId: string) {
  selectedCommentTaskId.value = taskId;
  selectedVideoId.value = null; // 进二级先清三级，避免脏数据
}
function backToCommentList() {
  selectedCommentTaskId.value = null;
  selectedVideoId.value = null;
}
function selectVideo(videoId: string) {
  selectedVideoId.value = videoId;
}
function closeVideoDetail() {
  selectedVideoId.value = null;
}

// 切平台时清掉二级/三级选中，避免拿着 B 站的 task id 误展示在抖音/快手。
watch(() => props.commentSubtab, () => {
  selectedCommentTaskId.value = null;
  selectedVideoId.value = null;
});

// 批次按钮文案 / 禁用态。点击瞬间 markRunning 把所有子 task 全部
// 标为 running → 显示"监测中…"；SSE finished 逐个清除 → 数字递增
// 显示"监测中 1/5"、"监测中 2/5"…；归零后回到"立刻监测"。
function batchRunState(batchName: string): { label: string; disabled: boolean } {
  const child = props.tasks.filter((t) => parseBatchName(t.name) === batchName);
  const total = child.length;
  const runningCount = child.filter((t) => props.runningTaskIds[t.id]).length;
  if (runningCount === 0) return { label: "立刻监测", disabled: false };
  if (runningCount === total) return { label: "监测中…", disabled: true };
  return { label: `监测中 ${total - runningCount}/${total}`, disabled: true };
}

// 父组件历史报告 drill-down 时调用：先切 activeTab/commentSubtab，
// 然后等两 tick 让 atomic load 跑完，最后调本接口把 L2/L3 选中态写到位。
function selectBatchAndVideo(batchName: string, taskId: number) {
  selectedCommentTaskId.value = batchName;
  selectedVideoId.value = `task-${taskId}`;
}

// 父组件删除一个批次后调用：若用户当前正停在这个批次上，回到 L1。
function clearSelectionIfBatch(batchName: string) {
  if (selectedCommentTaskId.value === batchName) {
    selectedCommentTaskId.value = null;
    selectedVideoId.value = null;
  }
}

defineExpose({ selectBatchAndVideo, clearSelectionIfBatch });
</script>

<template>
  <!--
    Root: `space-y-6` 给 hero / subtab / body 三个直接子节点统一 24px 间距
    （对齐 MonitorView root 的 gap-24 节奏）。原来是裸 <div>，紧急告警 hero
    跟下面平台 pivot 行紧贴成一团 —— 屏幕大时看着像粘连。
  -->
  <div class="space-y-6">
    <!-- alert hero (stacked when commentAlerts.length > 1) -->
    <div
      v-if="commentAlerts.length > 0 && currentCommentAlert"
      class="relative flex-shrink-0"
      :style="{ paddingBottom: commentAlerts.length > 1 ? '14px' : '0' }"
    >
      <div
        v-if="commentAlerts.length > 1"
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
          zIndex: 0,
        }"
      />
      <div
        v-if="commentAlerts.length > 2"
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
          background: 'radial-gradient(circle, rgba(216,90,72,0.5), transparent 65%)',
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
          background: 'radial-gradient(circle, rgba(238,106,42,0.4), transparent 65%)',
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
            <span>{{ commentAlerts.length }} 个紧急告警 · B 站</span>
            <span
              v-if="commentAlerts.length > 1"
              :style="{ color: 'rgba(255,255,255,0.4)', letterSpacing: '0' }"
            >· {{ commentAlertIdx + 1 }} / {{ commentAlerts.length }}</span>
          </div>
          <div
            class="font-display mt-2 font-bold"
            :style="{ fontSize: '28px', letterSpacing: '-0.5px', lineHeight: '1.25' }"
          >
            「{{ currentCommentAlert.keyword }}」<br />
            <span :style="{ color: 'var(--primary)' }">{{ currentCommentAlert.headline }}</span>
          </div>
          <div class="mt-2 text-[12.5px]" :style="{ color: 'rgba(255,255,255,0.6)' }">
            {{ currentCommentAlert.subtitle }}
          </div>
        </div>
        <div class="flex flex-shrink-0 items-center gap-2">
          <template v-if="commentAlerts.length > 1">
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
              @click="cycleAlert('comment', -1)"
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
              @click="cycleAlert('comment', 1)"
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
            @click="openCommentAlert(currentCommentAlert)"
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
            @click="emit('alert-action', 'repost')"
          >
            <Icon name="refresh" :size="14" />
            <span>补发评论</span>
          </button>
        </div>
      </div>
    </div>
    </div><!-- /alert hero stack wrapper -->

    <!-- platform sub-pivot -->
    <div class="flex flex-shrink-0 items-center justify-between">
      <div
        class="flex items-center"
        :style="{
          background: 'var(--card)',
          borderRadius: '999px',
          padding: '4px',
          border: '1px solid var(--line)',
        }"
      >
        <button
          v-for="p in PLATFORMS"
          :key="p.k"
          type="button"
          class="inline-flex items-center"
          :style="{
            height: '32px',
            padding: '0 16px',
            borderRadius: '999px',
            background: commentSubtab === p.k ? 'var(--dark)' : 'transparent',
            color: commentSubtab === p.k ? '#fbf7ec' : 'var(--ink-3)',
            fontSize: '12.5px',
            fontWeight: 500,
            gap: '8px',
            transition: 'background .15s, color .15s',
          }"
          @click="emit('update:commentSubtab', p.k)"
        >
          <span
            :style="{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              background: p.color,
              boxShadow: commentSubtab === p.k ? '0 0 0 2px rgba(255,255,255,0.15)' : 'none',
            }"
          />
          <span>{{ p.l }}</span>
        </button>
      </div>
      <!--
        评论平台只保留批量导入：每天要监测的视频链接通常很多，
        一条一条用 modal 加效率太低。单条的「新增任务」按钮在评论
        tab 下隐藏，统一走批量入口（用户决定）。Cookie 入口删除：
        池子在「设置 → 监测中心 → Cookie 管理」统一配置，
        在工作页再开一个等同重复。
      -->
      <div class="flex flex-shrink-0 gap-2">
        <button
          type="button"
          class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
          :style="{
            background: 'var(--primary)',
            color: '#fff',
            borderRadius: '999px',
          }"
          @click="emit('import-batch')"
        >
          <Icon name="folder" :size="12" />
          <span>批量导入</span>
        </button>
      </div>
    </div>

    <!-- comment platform body -->
    <!--
      空态：示例已清 & 没真实任务 ⇒ commentRows 必为空。统一一个分支
      覆盖 demo 空态 + 真实空态，文案不变。
    -->
    <template v-if="commentRows.length === 0">
      <div
        class="flex min-h-0 flex-1 flex-col items-center justify-center text-center"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '60px 30px',
        }"
      >
        <span
          class="inline-flex items-center justify-center"
          :style="{
            width: '54px',
            height: '54px',
            borderRadius: '16px',
            background: 'var(--card-2)',
            color: 'var(--ink-3)',
          }"
        >
          <Icon name="radar" :size="22" />
        </span>
        <div
          class="font-display mt-4 font-bold"
          :style="{ fontSize: '18px' }"
        >
          {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} 还没有监测任务
        </div>
        <div
          class="mt-1.5 max-w-[400px] text-[12.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          把 {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} 上要监控的视频/帖子链接加进来，CSM 会定时抓取评论留存情况。
        </div>
        <button
          type="button"
          class="mt-5 inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-medium"
          :style="{
            background: 'var(--primary)',
            color: '#fff',
            borderRadius: '999px',
          }"
          @click="emit('add-task')"
        >
          <Icon name="plus" :size="14" />
          <span>添加 {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} 监控</span>
        </button>
      </div>
    </template>

    <!--
      rich 三栏视图 —— demoMode 和真实数据共用同一段模板，数据来自
      commentRows / videosByBatchId / retentionPoints / deletedComments。
    -->
    <template v-else>
      <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
        <!--
          ── 左列：一级 任务列表 / 二级 视频列表 ───────────────
          min-h-0 + overflow-hidden 必须双层都加：grid 项的默认
          min-height: auto 会让子内容把整行撑高，导致页面级出现滚动条。
          内部的 `flex min-h-0 flex-1 overflow-y-auto` 才能把滚动锁在
          视频列表区块里（用户截图里 40 条视频触发的问题）。
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
          <!-- L1 任务列表 -->
          <template v-if="!selectedCommentTaskId">
            <div class="mb-3 flex-shrink-0">
              <div class="font-display text-[14px] font-semibold">
                {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} · 评论监控
              </div>
              <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                评论留存率 = 当前可见数 / 历史峰值
              </div>
            </div>
            <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <div
                class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
                :style="{
                  gridTemplateColumns: '1.6fr .7fr .7fr 1fr',
                  letterSpacing: '1.2px',
                  color: 'var(--ink-3)',
                  borderBottom: '1px solid var(--line)',
                }"
              >
                <div>任务名字</div><div>留存</div><div>变化</div><div class="text-center">操作</div>
              </div>
              <div
                v-for="(t, i) in commentRows"
                :key="t.id"
                class="grid cursor-pointer items-center transition"
                :style="{
                  gridTemplateColumns: '1.6fr .7fr .7fr 1fr',
                  borderBottom: i < commentRows.length - 1 ? '1px solid var(--line)' : 'none',
                  padding: '14px 8px',
                  borderRadius: '10px',
                }"
                @click="openCommentDetail(t.id)"
                @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
                @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
              >
                <div class="min-w-0">
                  <div
                    class="truncate text-[13px] font-medium"
                    :style="{ color: 'var(--primary-deep)' }"
                  >{{ t.kw }}</div>
                  <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                    {{ t.lastChecked }} · {{ (videosByBatchId[t.id] ?? []).length }} 条视频
                  </div>
                </div>
                <div>
                  <div class="font-display text-[13px] font-bold">
                    {{ t.retained }}/{{ t.total }}
                  </div>
                  <div
                    :style="{
                      height: '3px',
                      background: 'var(--line)',
                      borderRadius: '999px',
                      marginTop: '4px',
                      width: '60px',
                    }"
                  >
                    <div
                      :style="{
                        width: `${(t.retained / t.total) * 100}%`,
                        height: '100%',
                        background: t.retained < t.total ? 'var(--red, #d85a48)' : 'var(--green, #6c9b5d)',
                        borderRadius: '999px',
                      }"
                    />
                  </div>
                </div>
                <div>
                  <Pill v-if="t.delta < 0" tone="alert">
                    <Icon name="arrowDown" :size="10" />{{ t.delta }}
                  </Pill>
                  <Pill v-else-if="t.delta > 0" tone="ok">
                    <Icon name="arrowUp" :size="10" />+{{ t.delta }}
                  </Pill>
                  <Pill v-else tone="info">持平</Pill>
                </div>
                <!--
                  操作 cell —— 已移除「正常 / 关注 / 评论丢失」pill（用户反馈
                  没用信号都从「留存」列直观看出）。三个 icon 按钮：
                    ▶ 批量立刻监测  /  ✎ 编辑批次  /  🗑 删除批次
                  统一居中对齐到 column header 「操作」。
                -->
                <div class="flex items-center justify-center gap-1">
                  <button
                    v-if="!demoMode && batchRunState(t.id).disabled"
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--red, #d85a48)',
                      cursor: 'pointer',
                    }"
                    :title="`停止批次（${batchRunState(t.id).label}）`"
                    @click.stop="emit('cancel-batch', t.id)"
                  >
                    <Icon name="x" :size="13" />
                  </button>
                  <button
                    v-else-if="!demoMode"
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--primary-deep)',
                      cursor: 'pointer',
                    }"
                    :title="`批量立刻监测（共 ${tasks.filter((x) => parseBatchName(x.name) === t.id).length} 条）`"
                    @click.stop="emit('run-batch', t.id)"
                  >
                    <Icon name="play" :size="13" />
                  </button>
                  <button
                    v-if="!demoMode"
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--ink-3)',
                    }"
                    title="编辑批次"
                    @click.stop="emit('edit-batch', t.id)"
                  >
                    <Icon name="edit" :size="13" />
                  </button>
                  <button
                    v-if="!demoMode"
                    type="button"
                    class="inline-flex h-7 w-7 items-center justify-center"
                    :style="{
                      borderRadius: '999px',
                      color: 'var(--ink-3)',
                    }"
                    title="删除批次"
                    @click.stop="emit('delete-batch', t.id)"
                  >
                    <Icon name="trash" :size="13" />
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- L2 视频列表（点任务名进来） -->
          <template v-else>
            <div class="mb-3 flex flex-shrink-0 items-center gap-3">
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
                title="返回任务列表"
                @click="backToCommentList"
              >
                <Icon name="arrowLeft" :size="13" />
              </button>
              <div class="min-w-0">
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                  {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} · 视频列表
                </div>
                <div class="font-display truncate text-[14px] font-semibold">
                  {{ selectedCommentRow?.kw }}
                </div>
              </div>
              <span
                class="ml-auto flex-shrink-0 rounded-full text-[10.5px]"
                :style="{
                  background: 'var(--card-2)',
                  color: 'var(--ink-3)',
                  padding: '2px 8px',
                }"
              >{{ selectedTaskVideos.length }} 条</span>
            </div>
            <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <div
                class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
                :style="{
                  gridTemplateColumns: '1.8fr .6fr .6fr',
                  letterSpacing: '1.2px',
                  color: 'var(--ink-3)',
                  borderBottom: '1px solid var(--line)',
                }"
              >
                <div>视频名字</div><div>评论排名</div><div>状态</div>
              </div>
              <div
                v-for="(v, i) in selectedTaskVideos"
                :key="v.id"
                class="grid cursor-pointer items-center transition"
                :style="{
                  gridTemplateColumns: '1.8fr .6fr .6fr',
                  borderBottom: i < selectedTaskVideos.length - 1 ? '1px solid var(--line)' : 'none',
                  padding: '14px 8px',
                  borderRadius: '10px',
                  background: selectedVideoId === v.id ? 'var(--card-2)' : 'transparent',
                }"
                @click="selectVideo(v.id)"
                @mouseenter="(e) => { if (selectedVideoId !== v.id) (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
                @mouseleave="(e) => { if (selectedVideoId !== v.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
              >
                <div class="min-w-0">
                  <div
                    class="text-[13px] font-medium"
                    :title="v.title"
                    :style="{
                      color: selectedVideoId === v.id ? 'var(--primary-deep)' : 'var(--ink)',
                    }"
                  >{{ truncate15(v.title) }}</div>
                  <div class="mt-0.5 truncate text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                    {{ v.postedAt }}
                  </div>
                </div>
                <div>
                  <!-- rank=0 (即 backend rank=-1) = 未在前 scrape_top_n 条命中，显示 "无" 与右侧 "未找到" pill 语义对齐 -->
                  <span
                    v-if="v.rank > 0"
                    class="font-display text-[14px] font-bold"
                    :style="{ color: v.status === 'ok' ? 'var(--ink)' : 'var(--red, #d85a48)' }"
                  >#{{ v.rank }}</span>
                  <span
                    v-else
                    class="text-[11.5px]"
                    :style="{ color: 'var(--red, #d85a48)' }"
                  >无</span>
                </div>
                <div>
                  <Pill v-if="v.status === 'ok'" tone="ok">在显</Pill>
                  <Pill v-else-if="v.status === 'folded'" tone="warn">跌出理想</Pill>
                  <Pill v-else tone="alert">未找到</Pill>
                </div>
              </div>
            </div>
          </template>
        </section>

        <!--
          ── 右列：未选视频 → 留存汇总；已选视频 → 单视频详情 ──
          同左列：min-h-0 把 grid 项的高度收紧到 row；overflow-y-auto
          让本卡内容超出时自己滚，不传给页面。
        -->
        <section
          class="flex h-full min-h-0 flex-col overflow-y-auto"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <!-- L3 单视频详情（点视频名后右列变这个） -->
          <template v-if="selectedVideo">
            <div class="mb-3 flex flex-shrink-0 items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                  <template v-if="selectedVideo.rank > 0">视频 #{{ selectedVideo.rank }} 详情</template>
                  <template v-else>视频详情（评论未找到）</template>
                </div>
                <div
                  class="font-display mt-0.5 font-bold"
                  :title="selectedVideo.title"
                  :style="{ fontSize: '15px', lineHeight: 1.35 }"
                >{{ selectedVideo.title }}</div>
              </div>
              <button
                type="button"
                class="inline-flex flex-shrink-0 items-center justify-center"
                :style="{
                  width: '26px',
                  height: '26px',
                  borderRadius: '999px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                  color: 'var(--ink-2)',
                }"
                title="关闭详情"
                @click="closeVideoDetail"
              >
                <Icon name="x" :size="13" />
              </button>
            </div>

            <!-- 状态 / 排名 KPI -->
            <div class="mb-4 mt-3 grid grid-cols-3 gap-2 flex-shrink-0">
              <div
                :style="{
                  padding: '10px 12px',
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">评论排名</div>
                <div
                  class="font-display mt-0.5 font-bold"
                  :style="{
                    fontSize: '18px',
                    color: selectedVideo.rank > 0
                      ? (selectedVideo.status === 'ok' ? 'var(--ink)' : 'var(--red, #d85a48)')
                      : 'var(--red, #d85a48)',
                  }"
                >
                  <template v-if="selectedVideo.rank > 0">#{{ selectedVideo.rank }}</template>
                  <span v-else :style="{ fontSize: '14px' }">无</span>
                </div>
              </div>
              <div
                :style="{
                  padding: '10px 12px',
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">状态</div>
                <div class="mt-1.5">
                  <Pill v-if="selectedVideo.status === 'ok'" tone="ok">在显</Pill>
                  <Pill v-else-if="selectedVideo.status === 'folded'" tone="warn">跌出理想</Pill>
                  <Pill v-else tone="alert">未找到</Pill>
                </div>
              </div>
              <div
                :style="{
                  padding: '10px 12px',
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">总评论数</div>
                <div
                  class="font-display mt-0.5 font-bold"
                  :style="{ fontSize: '18px' }"
                >{{ selectedVideo.totalComments }}</div>
              </div>
            </div>

            <!-- 我的评论原文 -->
            <div class="mb-2 text-[12px] font-semibold flex-shrink-0">我的评论</div>
            <div
              class="flex-shrink-0"
              :style="{
                padding: '12px 14px',
                borderRadius: '10px',
                background:
                  selectedVideo.status === 'deleted'
                    ? 'rgba(216,90,72,0.07)'
                    : selectedVideo.status === 'folded'
                      ? 'rgba(245,192,66,0.08)'
                      : 'var(--card-2)',
                border: '1px solid var(--line)',
                fontSize: '12.5px',
                lineHeight: 1.6,
                color: 'var(--ink)',
              }"
            >「{{ selectedVideo.myComment }}」</div>
            <div class="mt-1 flex-shrink-0 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
              发布于 {{ selectedVideo.postedAt }}
            </div>

            <!-- 操作按钮 —— 真实数据下额外挂一个"立刻跑"，复用 zhihu 同款 SSE 触发流 -->
            <div class="mt-5 flex flex-shrink-0 gap-2">
              <a
                :href="selectedVideo.url"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-1.5 px-4 py-2 text-[12.5px]"
                :style="{
                  background: 'transparent',
                  color: 'var(--ink-2)',
                  border: '1px solid var(--line)',
                  borderRadius: '999px',
                  textDecoration: 'none',
                }"
              >
                <Icon name="external" :size="13" />
                <span>打开视频</span>
              </a>
              <button
                v-if="realTaskIdFromVideoId(selectedVideo.id)"
                type="button"
                class="inline-flex items-center gap-1.5 px-4 py-2 text-[12.5px]"
                :style="{
                  background: 'transparent',
                  color: runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]
                    ? 'var(--ink-3)'
                    : 'var(--primary-deep)',
                  border: '1px solid ' + (runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]
                    ? 'var(--line)'
                    : 'rgba(238,106,42,0.3)'),
                  borderRadius: '999px',
                  cursor: runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0] ? 'not-allowed' : 'pointer',
                }"
                :disabled="!!runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]"
                @click="() => { const id = realTaskIdFromVideoId(selectedVideo!.id); if (id) emit('run-now', id); }"
              >
                <Spinner
                  v-if="runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]"
                  :size="13"
                />
                <Icon v-else name="refresh" :size="13" />
                <span>{{ runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0] ? "监测中…" : "立刻监测" }}</span>
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-4 py-2 text-[12.5px] font-medium"
                :style="{
                  background: 'var(--primary)',
                  color: '#fff',
                  borderRadius: '999px',
                }"
                @click="emit('alert-action', 'repost')"
              >
                <Icon name="refresh" :size="13" />
                <span>补发评论</span>
              </button>
            </div>
          </template>

          <!-- L1/L2 默认右列 —— 留存趋势 + 被删评论 -->
          <template v-else>
            <div class="flex-shrink-0">
              <div class="font-display text-[14px] font-semibold">
                {{ selectedCommentTaskId ? "任务汇总" : "留存趋势" }}
              </div>
              <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                {{ selectedCommentTaskId ? "点左侧视频名查看单条评论详情" : "近 7 天" }}
              </div>
            </div>
            <div class="mt-3">
              <!--
                真实数据 sparkline 暂时只有 prev/latest 两点（来自 limit=2
                的快照对）；点不够时 Sparkline 自己会 fallback 到空态。
                后续要更细，可在选中批次时再拉每个 task limit=14 聚合。
              -->
              <Sparkline
                v-if="retentionPoints.length >= 2"
                :points="retentionPoints"
                :width="360"
                :height="80"
                stroke="var(--red, #d85a48)"
                :axis-labels="COMMENT_SPARK_LABELS"
                fluid
              />
              <div
                v-else
                class="text-[11.5px]"
                :style="{ color: 'var(--ink-3)', padding: '6px 0' }"
              >
                暂无足够的历史快照画趋势 —— 至少需要两次检查后才能成线。
              </div>
            </div>
            <div class="mt-4">
              <div class="mb-2 text-[12px] font-semibold">
                {{
                  deletedComments.length
                    ? `被删的 ${deletedComments.length} 条评论`
                    : '暂无被删评论'
                }}
              </div>
              <div
                v-for="(x, i) in deletedComments"
                :key="i"
                class="mb-1 flex items-center gap-3"
                :style="{
                  padding: '10px',
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <Pill :tone="x.tone">{{ x.tag }}</Pill>
                <span class="flex-1 text-[12px]">{{ x.who }}</span>
                <span class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">{{ x.date }}</span>
              </div>
            </div>

            <!--
              只有进入 L2（选中任务但还没选视频）才显示启停 + 频率
              控件 —— 在 L1 这里 selectedCommentTaskId 为空，没有具体
              任务可以挂这两个状态，控件就藏起来。
            -->
            <div
              v-if="selectedCommentTaskId"
              class="mt-4 flex items-center gap-2"
              :style="{
                paddingTop: '14px',
                borderTop: '1px solid var(--line)',
              }"
            >
              <button
                type="button"
                class="inline-flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-[12px] font-medium"
                :style="{
                  background: ensureCommentState(selectedCommentTaskId).enabled ? 'var(--card-2)' : 'var(--primary)',
                  color: ensureCommentState(selectedCommentTaskId).enabled ? 'var(--ink)' : '#fff',
                  border: '1px solid ' + (ensureCommentState(selectedCommentTaskId).enabled ? 'var(--line)' : 'var(--primary)'),
                  borderRadius: '999px',
                }"
                :title="ensureCommentState(selectedCommentTaskId).enabled ? '点击暂停监测' : '点击启动监测'"
                @click="toggleMonitor('comment', selectedCommentTaskId)"
              >
                <Icon
                  :name="ensureCommentState(selectedCommentTaskId).enabled ? 'check' : 'play'"
                  :size="13"
                />
                <span>
                  {{ ensureCommentState(selectedCommentTaskId).enabled ? '监测进行中' : '启动监测' }}
                </span>
              </button>
              <div class="flex flex-1 items-center gap-2">
                <Icon
                  name="calendar"
                  :size="13"
                  :style="{ color: 'var(--ink-3)' }"
                />
                <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">监测定时</span>
                <FormSelect
                  :model-value="ensureCommentState(selectedCommentTaskId).schedule"
                  :options="SCHEDULE_OPTIONS"
                  width="140"
                  @update:model-value="(v) => changeSchedule('comment', selectedCommentTaskId!, String(v))"
                />
              </div>
            </div>
          </template>
        </section>
      </div>
    </template>

    <!--
      以前真实数据走的是一段 flat fallback list（只显任务名 + 状态 pill），
      现在 rich 三栏视图既适配 demo 也适配真实，所以这个 fallback 整段删
      掉。L3 单视频详情里需要的"立刻跑 / 状态 spinner"已经接到了选中
      任务，详见 selectedVideo + selectedRealTaskId 流。
    -->
  </div>
</template>
