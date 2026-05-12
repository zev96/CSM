<script setup lang="ts">
/**
 * 监测中心 — V1 design alignment.
 *
 * 三大 tab：知乎问题 / 平台评论 / 历史报告。顶部使用 V1 同款的圆角胶囊
 * pivot（黑底高亮 + 计数徽章），下方根据 tab 渲染 dark 告警 hero +
 * 主表格 + 详情面板 / 平台子 pivot / 报告列表。
 *
 * 数据流保持原貌：
 *   /api/monitor/tasks?type=...        → 任务列表
 *   /api/monitor/results?task_id=X     → 任务历史（sparkline）
 *   /api/monitor/reports?period=daily  → 历史报告分桶
 *   /api/monitor/cookies?platform=...  → cookie 池（按钮入口）
 *   /api/monitor/tasks/{id}/run-now    → 强制立刻派发
 *   /api/monitor/events SSE            → 实时刷新
 *
 * sidecar 没启动 / 表里没数据时，沿用 ArticleView 的演示模式：把 V1
 * 设计稿里的 mock 任务 / 抢占者 / 留存趋势 / 历史报告条目铺出来，让用户
 * 一眼看到这页能呈现什么。演示行不挂"立刻跑/删除"按钮（id 是负数标记，
 * 不应该误调真实接口）。
 *
 * Cookie + 新增任务按钮按用户要求收进左侧任务卡的标题行右侧，避免和
 * 顶部 pivot 抢视线。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import AddTaskModal from "@/components/monitor/AddTaskModal.vue";
import AlertDetailModal from "@/components/monitor/AlertDetailModal.vue";
import BatchImportTaskModal from "@/components/monitor/BatchImportTaskModal.vue";
import CookieManagerModal from "@/components/monitor/CookieManagerModal.vue";

import { subscribe } from "@/api/client";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const sidecar = useSidecar();
const cfg = useConfig();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const { whenReady } = useSidecarReady();

type Tab = "zhihu" | "comment" | "report";
type CommentPlatform = "bilibili" | "douyin" | "kuaishou";

function tabFromQuery(): Tab {
  const q = route.query.tab;
  if (q === "zhihu" || q === "comment" || q === "report") return q;
  return "zhihu";
}
const activeTab = ref<Tab>(tabFromQuery());
watch(
  () => route.query.tab,
  () => {
    activeTab.value = tabFromQuery();
  },
);

const PLATFORM_TYPE: Record<CommentPlatform, string> = {
  bilibili: "bilibili_comment",
  douyin: "douyin_comment",
  kuaishou: "kuaishou_comment",
};
const commentSubtab = ref<CommentPlatform>("bilibili");

interface Task {
  id: number;
  type: string;
  name: string;
  target_url: string;
  enabled: boolean;
  schedule_cron: string;
  last_check_at: string | null;
  last_status: string | null;
}
const tasks = ref<Task[]>([]);
const selectedTaskId = ref<number | null>(null);
const taskResults = ref<Array<{ checked_at: string; status: string; rank: number; metric: any }>>([]);

const reports = ref<Array<{ period: string; total_checks: number; alert_count: number; by_status: Record<string, number> }>>([]);

const loading = ref(false);
const failed = ref(false);

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

interface SampleComment {
  id: string;
  kw: string;
  lastChecked: string;
  retained: number;
  total: number;
  delta: number;
  status: "ok" | "warn" | "alert";
}
// V1 设计稿示例数据，发布前清空保留空状态 —— 三个平台默认全空，
// SAMPLE_COMMENTS[platform].length === 0 时模板会渲染"还没有监测任务"。
const SAMPLE_COMMENTS: Record<CommentPlatform, SampleComment[]> = {
  bilibili: [],
  douyin: [],
  kuaishou: [],
};

const SAMPLE_RETENTION: number[] = [];

// 评论 tab 的三级导航数据结构：任务 → 视频列表 → 单视频详情。
// 一级（SAMPLE_COMMENTS）：任务名 / 留存 / 变化 / 状态
// 二级（这里 SAMPLE_VIDEOS）：每个任务下挂的视频列表
// 三级（视频本身）：自己在该视频下的评论原文 + 排名 + 状态 + URL
//
// 一二级同时可见 —— 左列在一级显任务列表，二级换成视频列表（保留返回箭头）；
// 三级走右列，把汇总图换成单视频详情。这样一屏就能看完上下文，不需要 modal。
interface VideoEntry {
  id: string;
  url: string;
  /** 视频原标题 —— 列表渲染时只取前 15 字，鼠标悬停看全文。 */
  title: string;
  /** 我自己在这条视频下的评论原文。 */
  myComment: string;
  /** 我的评论目前在该视频下的热度排名。 */
  rank: number;
  /** 评论现状：在显 / 被删 / 折叠。 */
  status: "ok" | "deleted" | "folded";
  /** 评论发出时间。 */
  postedAt: string;
  /** 视频评论区的总评论数（仅展示用）。 */
  totalComments: number;
}
// V1 设计稿示例数据，发布前清空保留空状态 —— 任务列表为空时下面这些
// 视频明细自然进不到，发布版本里全部清掉。
const SAMPLE_VIDEOS: Record<string, VideoEntry[]> = {};

function truncate15(s: string): string {
  return s.length > 15 ? `${s.slice(0, 15)}…` : s;
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
const COMMENT_SPARK_LABELS = daysAgoLabels(7, 7); // 7 天留存

// 监测启停 + 频率 —— 演示模式下保存在本地 ref 里，真实模式改 PATCH
// /api/monitor/tasks/{id}。每个任务一份独立设置，切任务不会丢状态。
interface MonitorState {
  enabled: boolean;
  schedule: string;
}
const SCHEDULE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "manual", label: "手动触发" },
  { value: "hourly-1", label: "每 1 小时" },
  { value: "hourly-6", label: "每 6 小时" },
  { value: "daily-09:00", label: "每天 09:00" },
  { value: "daily-12:00", label: "每天 12:00" },
  { value: "daily-18:00", label: "每天 18:00" },
];
function scheduleLabel(v: string): string {
  return SCHEDULE_OPTIONS.find((o) => o.value === v)?.label ?? v;
}
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
const commentMonitorState = ref<Record<string, MonitorState>>({
  "s-b1": { enabled: false, schedule: "hourly-1" },
  "s-b2": { enabled: false, schedule: "hourly-6" },
  "s-b3": { enabled: false, schedule: "daily-09:00" },
});

function ensureZhihuState(id: string): MonitorState {
  if (!zhihuMonitorState.value[id]) {
    zhihuMonitorState.value[id] = { enabled: false, schedule: "daily-09:00" };
  }
  return zhihuMonitorState.value[id];
}
function ensureCommentState(id: string): MonitorState {
  if (!commentMonitorState.value[id]) {
    commentMonitorState.value[id] = { enabled: false, schedule: "daily-09:00" };
  }
  return commentMonitorState.value[id];
}
function toggleMonitor(scope: "zhihu" | "comment", id: string) {
  const st = scope === "zhihu" ? ensureZhihuState(id) : ensureCommentState(id);
  st.enabled = !st.enabled;
  toast.info(`已${st.enabled ? "启动" : "暂停"}监测`);
}
function changeSchedule(scope: "zhihu" | "comment", id: string, v: string) {
  const st = scope === "zhihu" ? ensureZhihuState(id) : ensureCommentState(id);
  st.schedule = v;
  toast.success(`监测频率：${scheduleLabel(v)}`);
}

// V1 设计稿示例数据，发布前清空保留空状态。
const SAMPLE_DELETED: Array<{ tag: string; who: string; date: string; tone: "alert" | "warn" }> = [];

const SAMPLE_REPORTS: Array<{ id: string; n: string; scope: string; t: string; abn: number }> = [];

// 平台 chip 计数清零 —— V1 设计稿示例任务已清空，发布前保留空状态。
const PLATFORMS: Array<{ k: CommentPlatform; l: string; color: string; count: number }> = [
  { k: "bilibili", l: "B 站", color: "#ee6a2a", count: 0 },
  { k: "douyin", l: "抖音", color: "#1e1c19", count: 0 },
  { k: "kuaishou", l: "快手", color: "#f5c042", count: 0 },
];

// ── Demo mode: sidecar 不可用或表为空 ──────────────────────────────────
const demoMode = computed(() => failed.value || (!loading.value && tasks.value.length === 0));

// ── Loaders ─────────────────────────────────────────────────────────────
async function loadTasks(typeKey: string) {
  loading.value = true;
  failed.value = false;
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: typeKey },
    });
    tasks.value = r.data.tasks ?? [];
    if (tasks.value.length > 0 && (!selectedTaskId.value || !tasks.value.find((t) => t.id === selectedTaskId.value))) {
      selectedTaskId.value = tasks.value[0].id;
    }
  } catch (e: any) {
    failed.value = true;
    tasks.value = [];
    if (e?.response?.status !== 503) {
      toast.error(`加载失败：${e?.message ?? e}`);
    }
  } finally {
    loading.value = false;
  }
}

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

async function loadReports() {
  try {
    const r = await sidecar.client.get("/api/monitor/reports", {
      params: { period: "daily", limit: 30 },
    });
    reports.value = r.data.items ?? [];
  } catch (e: any) {
    if (e?.response?.status === 503) failed.value = true;
    reports.value = [];
  }
}

const showAddTask = ref(false);
const showBatchImport = ref(false);
const showCookieMgr = ref(false);

// 紧急告警 / 历史报告详情 modal —— 三种语义共用一张面板，只换 kind/report
const showAlertModal = ref(false);
const alertKind = ref<"zhihu_alert" | "comment_alert" | "history_report">("zhihu_alert");
const selectedReport = ref<{ n: string; scope: string; t: string; abn: number } | null>(null);

// 紧急告警 hero 改成可翻页的卡片堆叠：多条告警同时存在时，hero 只显示
// 当前一条 + 后面 2 张更小更暗的「卡片影子」，左右两个圆形 chevron 切上
// 一条 / 下一条。1 条告警时影子和 chevron 自动隐藏（hasNav 为 false）。
interface HeroAlert {
  keyword: string;
  headline: string;
  subtitle: string;
}
// V1 设计稿示例告警，发布前清空保留空状态 —— 真正触发告警时由后端填充。
const zhihuAlerts: HeroAlert[] = [];
const commentAlerts: HeroAlert[] = [];
const zhihuAlertIdx = ref(0);
const commentAlertIdx = ref(0);
const currentZhihuAlert = computed(() => zhihuAlerts[zhihuAlertIdx.value]);
const currentCommentAlert = computed(() => commentAlerts[commentAlertIdx.value]);
function cycleAlert(kind: "zhihu" | "comment", dir: 1 | -1) {
  const list = kind === "zhihu" ? zhihuAlerts : commentAlerts;
  const ref_ = kind === "zhihu" ? zhihuAlertIdx : commentAlertIdx;
  // wrap-around 让用户在 1↔️N 来回切不会被卡住；按钮始终可点，更直白。
  ref_.value = (ref_.value + dir + list.length) % list.length;
}

function openZhihuAlert() {
  alertKind.value = "zhihu_alert";
  selectedReport.value = null;
  showAlertModal.value = true;
}
function openCommentAlert() {
  alertKind.value = "comment_alert";
  selectedReport.value = null;
  showAlertModal.value = true;
}
function openReport(r: { n: string; scope: string; t: string; abn: number }) {
  alertKind.value = "history_report";
  selectedReport.value = r;
  showAlertModal.value = true;
}
function onAlertAction(a: "rescue" | "repost" | "close") {
  showAlertModal.value = false;
  if (a === "rescue") {
    router.push({ name: "article" });
  } else if (a === "repost") {
    // 真实告警接入后由后端给出推荐补发文案；空示例阶段给出一句通用占位。
    const sample = "在此处粘贴你针对本条告警准备的补发文案。";
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(sample).then(
        () => toast.success("已复制示例补发文案到剪贴板"),
        () => toast.info("演示：示例文案已就绪"),
      );
    } else {
      toast.info("演示：示例文案已就绪");
    }
  }
}

async function deleteTask(taskId: number) {
  if (!(await confirmDialog("确定删除这个监测任务？历史结果会一并删除。", { title: "删除监测任务" }))) return;
  try {
    await sidecar.client.delete(`/api/monitor/tasks/${taskId}`);
    toast.success("任务已删除");
    if (selectedTaskId.value === taskId) {
      selectedTaskId.value = null;
      taskResults.value = [];
    }
    await loadTasks(activeTab.value === "zhihu" ? "zhihu_question" : PLATFORM_TYPE[commentSubtab.value]);
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

async function runNow(taskId: number) {
  try {
    await sidecar.client.post(`/api/monitor/tasks/${taskId}/run-now`);
    toast.info("已派发，结果会通过 SSE 推送回来");
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? e;
    toast.error(`派发失败：${detail}`);
  }
}

let stopMonitorBus: (() => void) | null = null;
function startMonitorBus() {
  stopMonitorBus = subscribe("/api/monitor/events", {
    finished: (d: any) => {
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) {
        t.last_check_at = d.at;
        t.last_status = d.result?.status ?? t.last_status;
      }
      if (selectedTaskId.value === d.task_id) {
        loadResults(d.task_id);
      }
    },
    alert: (d: any) => {
      toast.warn(`任务 #${d.task_id} 触发告警`);
    },
    failed: (d: any) => {
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) t.last_status = "failed";
    },
  });
}

const sparkPoints = computed(() => {
  if (demoMode.value) return SAMPLE_SPARK_RANK;
  const topN = cfg.data?.monitor?.alert_top_n ?? 5;
  return [...taskResults.value]
    .reverse()
    .map((r) => (r.rank > 0 ? r.rank : topN + 5));
});

watch(activeTab, async (t) => {
  if (t === "zhihu") {
    await loadTasks("zhihu_question");
  } else if (t === "comment") {
    await loadTasks(PLATFORM_TYPE[commentSubtab.value]);
  } else {
    await loadReports();
  }
});

watch(commentSubtab, async (s) => {
  if (activeTab.value === "comment") await loadTasks(PLATFORM_TYPE[s]);
});

watch(selectedTaskId, async (id) => {
  if (id != null && id > 0) await loadResults(id);
});

const selectedTask = computed(() =>
  tasks.value.find((t) => t.id === selectedTaskId.value) ?? null,
);

// 演示模式下的当前 zhihu 任务（用于详情卡片）。SAMPLE_ZHIHU 发布前已清空，
// 这里改为可空 ref；模板里详情卡用 v-if 守卫，没有示例数据就显示空状态。
const sampleSelectedZhihu = ref<SampleZhihu | null>(SAMPLE_ZHIHU[0] ?? null);

// 评论 tab 三级导航：
//   selectedCommentTaskId  —— 一级 → 二级（左列从任务列表换成视频列表）
//   selectedVideoId        —— 二级 → 三级（右列从汇总图换成单视频详情）
// 两者都是字符串 id，分别对应 SAMPLE_COMMENTS / SAMPLE_VIDEOS 里的 id。
const selectedCommentTaskId = ref<string | null>(null);
const selectedVideoId = ref<string | null>(null);

const selectedCommentRow = computed(() =>
  selectedCommentTaskId.value
    ? SAMPLE_COMMENTS[commentSubtab.value]?.find((c) => c.id === selectedCommentTaskId.value) ?? null
    : null,
);
const selectedTaskVideos = computed<VideoEntry[]>(() =>
  selectedCommentTaskId.value
    ? SAMPLE_VIDEOS[selectedCommentTaskId.value] ?? []
    : [],
);
const selectedVideo = computed<VideoEntry | null>(() => {
  if (!selectedVideoId.value) return null;
  return selectedTaskVideos.value.find((v) => v.id === selectedVideoId.value) ?? null;
});

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
watch(commentSubtab, () => {
  selectedCommentTaskId.value = null;
  selectedVideoId.value = null;
});

function severity(t: Task): "alert" | "warn" | "ok" | "info" {
  if (!t.last_status) return "info";
  if (t.last_status === "failed" || t.last_status === "risk_control") return "alert";
  if (t.last_status !== "ok") return "info";
  return "ok";
}
const STATUS_LABEL: Record<string, string> = {
  alert: "异常",
  warn: "跌出",
  ok: "稳定",
  info: "未检",
};

// tabCounts 计数徽章已下线（顶部 pivot 不再展示 4/1/12 数字胶囊）；
// 如需重启回归，把上面的 pill 模板 + 这里的 computed 一起恢复。

onMounted(async () => {
  try {
    await whenReady();
    if (!cfg.data) await cfg.load();
    if (activeTab.value === "zhihu") await loadTasks("zhihu_question");
    else if (activeTab.value === "comment") await loadTasks(PLATFORM_TYPE[commentSubtab.value]);
    else await loadReports();
    startMonitorBus();
  } catch {
    /* sidecar already toasted; demoMode 会接管显示 */
    failed.value = true;
  }
});

onUnmounted(() => {
  if (stopMonitorBus) stopMonitorBus();
});

// 面板交互：点击演示行切换详情卡
function pickSampleZhihu(row: SampleZhihu) {
  sampleSelectedZhihu.value = row;
}

const TAB_META: Array<{ k: Tab; l: string; ic: string }> = [
  { k: "zhihu", l: "知乎问题", ic: "radar" },
  { k: "comment", l: "平台评论", ic: "warn" },
  { k: "report", l: "历史报告", ic: "fileText" },
];
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '24px' }">
    <!-- ── 顶部：title + pivot ───────────────────────────────────── -->
    <div class="flex flex-shrink-0 items-end justify-between gap-4">
      <div class="min-w-0">
        <div
          class="text-[11px] uppercase"
          :style="{ letterSpacing: '1.5px', color: 'var(--ink-3)' }"
        >监测中心</div>
        <div
          class="font-display mt-2 font-bold"
          :style="{ fontSize: '30px', letterSpacing: '-0.5px' }"
        >
          {{
            activeTab === "zhihu"
              ? "排名异动 & 评论留存"
              : activeTab === "comment"
                ? "平台评论 · 留存监控"
                : "历史检测报告"
          }}
        </div>
        <div class="mt-1 text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
          {{
            activeTab === "zhihu"
              ? "知乎问题 · 关键词排名 + Top 抢占者"
              : activeTab === "comment"
                ? "B 站 / 抖音 / 快手 · 评论被删与折叠告警"
                : "日报 · 周报 · 按时间倒序"
          }}
        </div>
      </div>

      <div
        class="flex flex-shrink-0 items-center"
        :style="{
          background: 'var(--card)',
          borderRadius: '999px',
          padding: '4px',
          border: '1px solid var(--line)',
        }"
      >
        <button
          v-for="t in TAB_META"
          :key="t.k"
          type="button"
          class="inline-flex items-center"
          :style="{
            height: '32px',
            padding: '0 16px',
            borderRadius: '999px',
            background: activeTab === t.k ? 'var(--dark)' : 'transparent',
            color: activeTab === t.k ? '#fbf7ec' : 'var(--ink-3)',
            fontSize: '12.5px',
            fontWeight: 500,
            gap: '6px',
            transition: 'background .15s, color .15s',
          }"
          @click="activeTab = t.k"
        >
          <!--
            原来 t.l 后面跟一颗 `tabCounts[t.k]` 数字胶囊（4 / 1 / 12），
            被用户判定为无信息价值 —— 总条数对决策没帮助，反而让 pill
            视觉变长。删掉，pill 只剩 icon + 名称。
          -->
          <Icon :name="t.ic" :size="13" />
          <span>{{ t.l }}</span>
        </button>
      </div>
    </div>

    <!-- ── 知乎问题 ─────────────────────────────────────────────── -->
    <template v-if="activeTab === 'zhihu'">
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
                @click="openZhihuAlert"
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
        <!-- table card -->
        <section
          class="flex h-full flex-col"
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
                按上次检查倒序
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
                @click="showCookieMgr = true"
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
                @click="showBatchImport = true"
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
                @click="showAddTask = true"
              >
                <Icon name="plus" :size="12" />
                <span>新增任务</span>
              </button>
            </div>
          </div>

          <!-- scrollable table body — fills remaining vertical space -->
          <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <!-- header row -->
          <div
            class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
            :style="{
              gridTemplateColumns: '1.6fr .8fr .6fr .6fr .6fr',
              letterSpacing: '1.2px',
              color: 'var(--ink-3)',
              borderBottom: '1px solid var(--line)',
            }"
          >
            <div>问题名字</div><div>类型</div><div>上次</div><div>变化</div><div>状态</div>
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

          <!-- demo rows -->
          <template v-else-if="demoMode">
            <div
              v-for="(t, i) in SAMPLE_ZHIHU"
              :key="t.id"
              class="grid cursor-pointer items-center transition"
              :style="{
                gridTemplateColumns: '1.6fr .8fr .6fr .6fr .6fr',
                background: sampleSelectedZhihu?.id === t.id ? 'var(--card-2)' : 'transparent',
                borderBottom: i < SAMPLE_ZHIHU.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '14px 8px',
                borderRadius: '10px',
              }"
              @click="pickSampleZhihu(t)"
            >
              <div class="truncate text-[13px] font-medium">{{ t.kw }}</div>
              <div class="text-[12px]" :style="{ color: 'var(--ink-2)' }">{{ t.type }}</div>
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
              <div>
                <Pill v-if="t.status === 'ok'" tone="ok">正常</Pill>
                <Pill v-else-if="t.status === 'warn'" tone="warn">关注</Pill>
                <Pill v-else tone="alert">告警</Pill>
              </div>
            </div>
          </template>

          <!-- real rows -->
          <template v-else>
            <div
              v-for="(t, i) in tasks"
              :key="t.id"
              class="grid cursor-pointer items-center transition"
              :style="{
                gridTemplateColumns: '1.6fr .8fr .6fr .6fr .6fr',
                background: selectedTaskId === t.id ? 'var(--card-2)' : 'transparent',
                borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
                padding: '14px 8px',
                borderRadius: '10px',
              }"
              @click="selectedTaskId = t.id"
            >
              <div class="truncate text-[13px] font-medium">{{ t.name }}</div>
              <div class="text-[12px]" :style="{ color: 'var(--ink-2)' }">{{ t.type }}</div>
              <div class="font-display text-[13px] font-bold">—</div>
              <div>
                <Pill :tone="severity(t)">{{ STATUS_LABEL[severity(t)] }}</Pill>
              </div>
              <div class="flex justify-end gap-1">
                <button
                  type="button"
                  class="text-[11px]"
                  :style="{ color: 'var(--primary-deep)' }"
                  @click.stop="runNow(t.id)"
                >立刻跑</button>
                <button
                  type="button"
                  class="px-1.5"
                  :style="{ color: 'var(--ink-3)' }"
                  title="删除任务"
                  @click.stop="deleteTask(t.id)"
                >
                  <Icon name="trash" :size="13" />
                </button>
              </div>
            </div>
          </template>
          </div>
        </section>

        <!-- detail card -->
        <section
          class="flex h-full flex-col overflow-y-auto"
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
              <div class="font-display text-[14px] font-semibold">{{ selectedTask.name }}</div>
              <a
                :href="selectedTask.target_url"
                target="_blank"
                rel="noopener"
                class="mt-1 block truncate text-[11px]"
                :style="{ color: 'var(--primary)' }"
              >{{ selectedTask.target_url }}</a>
              <div class="mt-4">
                <div class="mb-1 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                  最近 14 次排名
                </div>
                <Sparkline
                  v-if="sparkPoints.length"
                  :points="sparkPoints"
                  :width="280"
                  :height="60"
                />
                <div v-else class="text-[11px] italic" :style="{ color: 'var(--ink-3)' }">
                  无历史数据
                </div>
              </div>
            </template>
          </template>
        </section>
      </div>
    </template>

    <!-- ── 平台评论 ─────────────────────────────────────────────── -->
    <template v-else-if="activeTab === 'comment'">
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
              @click="openCommentAlert"
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
              @click="onAlertAction('repost')"
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
            @click="commentSubtab = p.k"
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
            <span
              class="text-[10.5px]"
              :style="{
                color: commentSubtab === p.k ? 'rgba(255,255,255,0.5)' : 'var(--ink-3)',
                background: commentSubtab === p.k ? 'rgba(255,255,255,0.08)' : 'var(--card-2)',
                borderRadius: '999px',
                padding: '1px 7px',
              }"
            >{{ p.count }}</span>
          </button>
        </div>
        <!--
          评论平台只保留批量导入：每天要监测的视频链接通常很多，
          一条一条用 modal 加效率太低。单条的「新增任务」按钮在评论
          tab 下隐藏，统一走批量入口（用户决定）。Cookie 仍保留。
        -->
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
            @click="showCookieMgr = true"
          >
            <Icon name="key" :size="12" />
            <span>Cookie</span>
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
            :style="{
              background: 'var(--primary)',
              color: '#fff',
              borderRadius: '999px',
            }"
            @click="showBatchImport = true"
          >
            <Icon name="folder" :size="12" />
            <span>批量导入</span>
          </button>
        </div>
      </div>

      <!-- comment platform body -->
      <template v-if="demoMode && SAMPLE_COMMENTS[commentSubtab].length === 0">
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
            @click="showAddTask = true"
          >
            <Icon name="plus" :size="14" />
            <span>添加 {{ PLATFORMS.find((p) => p.k === commentSubtab)?.l }} 监控</span>
          </button>
        </div>
      </template>

      <template v-else-if="demoMode">
        <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
          <!-- ── 左列：一级 任务列表 / 二级 视频列表 ─────────────── -->
          <section
            class="flex h-full flex-col"
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
                    gridTemplateColumns: '1.8fr .8fr .8fr .6fr',
                    letterSpacing: '1.2px',
                    color: 'var(--ink-3)',
                    borderBottom: '1px solid var(--line)',
                  }"
                >
                  <div>任务名字</div><div>留存</div><div>变化</div><div>状态</div>
                </div>
                <div
                  v-for="(t, i) in SAMPLE_COMMENTS[commentSubtab]"
                  :key="t.id"
                  class="grid cursor-pointer items-center transition"
                  :style="{
                    gridTemplateColumns: '1.8fr .8fr .8fr .6fr',
                    borderBottom: i < SAMPLE_COMMENTS[commentSubtab].length - 1 ? '1px solid var(--line)' : 'none',
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
                      {{ t.lastChecked }} · {{ (SAMPLE_VIDEOS[t.id] ?? []).length }} 条视频
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
                  <div>
                    <Pill v-if="t.status === 'ok'" tone="ok">正常</Pill>
                    <Pill v-else-if="t.status === 'warn'" tone="warn">关注</Pill>
                    <Pill v-else tone="alert">删除</Pill>
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
                    <span
                      class="font-display text-[14px] font-bold"
                      :style="{ color: 'var(--ink)' }"
                    >#{{ v.rank }}</span>
                  </div>
                  <div>
                    <Pill v-if="v.status === 'ok'" tone="ok">在显</Pill>
                    <Pill v-else-if="v.status === 'folded'" tone="warn">折叠</Pill>
                    <Pill v-else tone="alert">被删</Pill>
                  </div>
                </div>
              </div>
            </template>
          </section>

          <!-- ── 右列：未选视频 → 留存汇总；已选视频 → 单视频详情 ── -->
          <section
            class="flex h-full flex-col overflow-y-auto"
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
                    视频 #{{ selectedVideo.rank }} 详情
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
                    :style="{ fontSize: '18px' }"
                  >#{{ selectedVideo.rank }}</div>
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
                    <Pill v-else-if="selectedVideo.status === 'folded'" tone="warn">折叠</Pill>
                    <Pill v-else tone="alert">被删</Pill>
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

              <!-- 操作按钮 -->
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
                  type="button"
                  class="inline-flex items-center gap-1.5 px-4 py-2 text-[12.5px] font-medium"
                  :style="{
                    background: 'var(--primary)',
                    color: '#fff',
                    borderRadius: '999px',
                  }"
                  @click="onAlertAction('repost')"
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
                <Sparkline
                  :points="SAMPLE_RETENTION"
                  :width="360"
                  :height="80"
                  stroke="var(--red, #d85a48)"
                  :axis-labels="COMMENT_SPARK_LABELS"
                  fluid
                />
              </div>
              <div class="mt-4">
                <div class="mb-2 text-[12px] font-semibold">被删的 6 条评论</div>
                <div
                  v-for="(x, i) in SAMPLE_DELETED"
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

      <!-- real comment data -->
      <template v-else>
        <section
          class="flex h-full min-h-0 flex-1 flex-col overflow-y-auto"
          :style="{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-card)',
            padding: '22px',
          }"
        >
          <div v-if="!tasks.length" class="py-6 text-center text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
            还没有 {{ commentSubtab }} 任务。
          </div>
          <div v-else>
            <div
              v-for="t in tasks"
              :key="t.id"
              class="flex items-center justify-between border-b py-3"
              :style="{ borderColor: 'var(--line)' }"
            >
              <div class="min-w-0">
                <div class="truncate text-[13px] font-medium">{{ t.name }}</div>
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                  {{ t.last_check_at ? new Date(t.last_check_at).toLocaleString() : "—" }}
                </div>
              </div>
              <div class="flex items-center gap-2">
                <Pill :tone="severity(t)">{{ STATUS_LABEL[severity(t)] }}</Pill>
                <button
                  type="button"
                  class="text-[11px]"
                  :style="{ color: 'var(--primary-deep)' }"
                  @click.stop="runNow(t.id)"
                >立刻跑</button>
              </div>
            </div>
          </div>
        </section>
      </template>
    </template>

    <!-- ── 历史报告 ─────────────────────────────────────────────── -->
    <template v-else>
      <section
        class="flex min-h-0 flex-1 flex-col"
        :style="{
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          padding: '22px',
        }"
      >
        <div class="mb-3 flex-shrink-0">
          <div class="font-display text-[14px] font-semibold">历史检测报告</div>
          <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
            按时间倒序，最近 30 天
          </div>
        </div>
        <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div
          class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.4fr 1fr .8fr .8fr .6fr',
            letterSpacing: '1.2px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>报告</div><div>覆盖</div><div>时间</div><div>异动</div><div></div>
        </div>

        <template v-if="(demoMode || !reports.length) && SAMPLE_REPORTS.length === 0">
          <div
            class="py-10 text-center text-[12.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            暂无历史报告 · 监测任务跑起来后会生成日报 / 周报
          </div>
        </template>
        <template v-else-if="demoMode || !reports.length">
          <div
            v-for="(r, i) in SAMPLE_REPORTS"
            :key="r.id"
            class="grid items-center"
            :style="{
              gridTemplateColumns: '1.4fr 1fr .8fr .8fr .6fr',
              borderBottom: i < SAMPLE_REPORTS.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
            }"
          >
            <div class="flex items-center gap-2">
              <Icon name="fileText" :size="13" class="opacity-50" />
              <span class="text-[13px] font-medium">{{ r.n }}</span>
            </div>
            <div class="text-[12px]" :style="{ color: 'var(--ink-2)' }">{{ r.scope }}</div>
            <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">{{ r.t }}</div>
            <div>
              <Pill v-if="r.abn > 0" tone="warn">{{ r.abn }} 个异动</Pill>
              <Pill v-else tone="ok">无异常</Pill>
            </div>
            <div class="flex justify-end">
              <button
                type="button"
                class="text-[11.5px]"
                :style="{ color: 'var(--primary-deep)' }"
                @click="openReport({ n: r.n, scope: r.scope, t: r.t, abn: r.abn })"
              >查看 →</button>
            </div>
          </div>
        </template>
        <template v-else>
          <div
            v-for="(r, i) in reports"
            :key="r.period"
            class="grid items-center"
            :style="{
              gridTemplateColumns: '1.4fr 1fr .8fr .8fr .6fr',
              borderBottom: i < reports.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
            }"
          >
            <div class="flex items-center gap-2">
              <Icon name="fileText" :size="13" class="opacity-50" />
              <span class="text-[13px] font-medium">{{ r.period }}</span>
            </div>
            <div class="text-[12px]" :style="{ color: 'var(--ink-2)' }">
              {{ r.total_checks }} 次检查
            </div>
            <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">{{ r.period }}</div>
            <div>
              <Pill v-if="r.alert_count > 0" tone="warn">
                {{ r.alert_count }} 告警
              </Pill>
              <Pill v-else tone="ok">无异常</Pill>
            </div>
            <div class="flex justify-end">
              <button
                type="button"
                class="text-[11.5px]"
                :style="{ color: 'var(--primary-deep)' }"
              >查看 →</button>
            </div>
          </div>
        </template>
        </div>
      </section>
    </template>

    <!-- ── Modals ──────────────────────────────────────────────── -->
    <AddTaskModal
      v-model:open="showAddTask"
      :default-type="
        activeTab === 'zhihu'
          ? 'zhihu_question'
          : commentSubtab === 'bilibili'
            ? 'bilibili_comment'
            : commentSubtab === 'douyin'
              ? 'douyin_comment'
              : 'kuaishou_comment'
      "
      @created="loadTasks(activeTab === 'zhihu' ? 'zhihu_question' : PLATFORM_TYPE[commentSubtab])"
    />
    <BatchImportTaskModal
      v-model:open="showBatchImport"
      :default-type="
        activeTab === 'zhihu'
          ? 'zhihu_question'
          : commentSubtab === 'bilibili'
            ? 'bilibili_comment'
            : commentSubtab === 'douyin'
              ? 'douyin_comment'
              : 'kuaishou_comment'
      "
      @imported="loadTasks(activeTab === 'zhihu' ? 'zhihu_question' : PLATFORM_TYPE[commentSubtab])"
    />
    <CookieManagerModal
      v-model:open="showCookieMgr"
      :default-platform="
        activeTab === 'zhihu'
          ? 'zhihu_question'
          : commentSubtab === 'bilibili'
            ? 'bilibili_comment'
            : commentSubtab === 'douyin'
              ? 'douyin_comment'
              : 'kuaishou_comment'
      "
    />
    <AlertDetailModal
      v-model:open="showAlertModal"
      :kind="alertKind"
      :report="selectedReport ?? undefined"
      @action="onAlertAction"
    />
  </div>
</template>
