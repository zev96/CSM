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
 *   /api/monitor/cookies?platform=...  → cookie 池（按钮入口）
 *   /api/monitor/tasks/{id}/run-now    → 强制立刻派发
 *   /api/monitor/events SSE            → 实时刷新
 *
 * sidecar 没启动 / 表里没数据时，沿用 ArticleView 的演示模式：把 V1
 * 设计稿里的 mock 任务 / 抢占者 / 留存趋势铺出来，让用户
 * 一眼看到这页能呈现什么。演示行不挂"立刻跑/删除"按钮（id 是负数标记，
 * 不应该误调真实接口）。
 *
 * Cookie + 新增任务按钮按用户要求收进左侧任务卡的标题行右侧，避免和
 * 顶部 pivot 抢视线。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import AddTaskModal from "@/components/monitor/AddTaskModal.vue";
import AlertDetailModal from "@/components/monitor/AlertDetailModal.vue";
import BatchImportTaskModal from "@/components/monitor/BatchImportTaskModal.vue";
import CookieManagerModal from "@/components/monitor/CookieManagerModal.vue";
import EditBatchModal from "@/components/monitor/EditBatchModal.vue";
import CommentMonitorModule from "@/components/monitor/CommentMonitorModule.vue";
import RetentionPage from "@/components/monitor/history/RetentionPage.vue";
import ZhihuRankingPage from "@/components/monitor/history/ZhihuRankingPage.vue";
import BaiduRankingPage from "@/components/monitor/history/BaiduRankingPage.vue";
import BaiduSEOAnalytics from "@/components/monitor/history/BaiduSEOAnalytics.vue";

import { subscribe } from "@/api/client";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import { useStaleGuard } from "@/composables/useStaleGuard";
import {
  resultToSnapshot,
  type TaskSnapshotPair,
} from "@/utils/monitor-snapshot";
import {
  parseBatchName,
  formatRelativeTime,
  formatTimelineTime,
} from "@/utils/monitor-batch";
import {
  type Task,
  type CommentPlatform,
  type CommentAlertData,
  type HeroAlert,
  type MonitorState,
  SCHEDULE_OPTIONS,
  scheduleLabel,
} from "@/utils/monitor-types";

const sidecar = useSidecar();
const cfg = useConfig();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const { whenReady } = useSidecarReady();

type Tab = "zhihu" | "comment" | "baidu" | "report";

function tabFromQuery(): Tab {
  const q = route.query.tab;
  if (q === "zhihu" || q === "comment" || q === "baidu" || q === "report") return q;
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

type HistorySubtab = "retention" | "zhihu" | "baidu";
const historySubtab = ref<HistorySubtab>("retention");

// 当前 tab 对应的任务 type——modal 的 :default-type 和 @imported reload 共用，
// 避免两处分别 inline 维护出现错位（baidu 分支原本只在 :default-type 里有，
// @imported 漏了，导致百度批量导入后刷错 tab 的列表）。
const currentTaskType = computed<string>(() => {
  if (activeTab.value === "zhihu") return "zhihu_question";
  if (activeTab.value === "baidu") return "baidu_keyword";
  if (activeTab.value === "report" && historySubtab.value === "baidu") return "baidu_keyword";
  return PLATFORM_TYPE[commentSubtab.value];
});

const tasks = ref<Task[]>([]);
const selectedTaskId = ref<number | null>(null);
const taskResults = ref<Array<{ checked_at: string; status: string; rank: number; metric: any }>>([]);

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

// 评论 tab 的三级导航 / SAMPLE_COMMENTS / SAMPLE_VIDEOS / SAMPLE_RETENTION /
// SAMPLE_DELETED / PLATFORMS / truncate15 / COMMENT_SPARK_LABELS /
// commentMonitorState / ensureCommentState 全部下沉到
// components/monitor/CommentMonitorModule.vue（Phase 2 拆分）。

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

// ── Comment snapshots（每个 task 最近两次 result）─────────────────────
//
// 评论 tab 的 rich UI（留存 8/14 / 变化 -3 / 被删评论列表 / 留存趋势 sparkline）
// 全靠后端 MonitorResult.metric 里塞的 `matched / hot_comments / total_fetched`
// 字段（见 csm_core/monitor/platforms/_comment_common.py）。`/api/monitor/tasks`
// 只回任务元信息，要拿 metric 必须二次拉 `/api/monitor/results?task_id=X`。
//
// 这里在 loadTasks 后并行 fetch 每条任务的近两次 result：latest 算
// "当前留存"，prev 算"变化 delta"（matched_now - matched_prev）。limit=2
// 一次请求双带，比 limit=1 + limit=1 多一次 round trip 划算。
//
// 历史 30 条用于父批次的 7 天 sparkline —— 但 30 条 × N 任务太重，分两
// 跳：L1/L2 列表用 limit=2 的轻量结果；进 L3 单视频详情时再单独 fetch
// limit=14（沿用 zhihu 的 loadResults 路径）。
// TaskSnapshot / TaskSnapshotPair / resultToSnapshot now live in
// utils/monitor-snapshot.ts so the sub-tab modules can import them
// without dragging this 3300-line file along.
const taskSnapshots = ref<Record<number, TaskSnapshotPair>>({});

async function _fetchSnapshotPair(taskId: number): Promise<void> {
  try {
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: taskId, limit: 2 },
    });
    const rows: any[] = r.data?.results ?? [];
    // 后端按 checked_at desc 返回，rows[0] = latest, rows[1] = prev
    taskSnapshots.value = {
      ...taskSnapshots.value,
      [taskId]: {
        latest: resultToSnapshot(rows[0] ?? null),
        prev: resultToSnapshot(rows[1] ?? null),
      },
    };
  } catch {
    // 静默失败 —— 没拿到 snapshot 的 task 在 UI 上显示 "—" 即可，
    // 不弹 toast（一次点开就 N 个错误会刷屏）。
  }
}

async function loadTaskSnapshots() {
  // 评论 / 知乎 tab 都用：L1 行的"上次 / 变化 / 留存"列要靠 latest+prev
  // 两次 result 计算。空表跳过。
  if (!tasks.value.length) return;
  await Promise.all(tasks.value.map((t) => _fetchSnapshotPair(t.id)));
}

// 原子加载平台任务 + snapshots：把新平台 tasks 与每条 task 的近两条 result
// snapshot 全部静默拉到临时对象，最后一次性赋给 reactive state。早期实现
// 在 watch 里先 ``taskSnapshots.value = {}`` 同步清空再 ``await loadTasks``，
// 期间旧 tasks 拿不到 snapshot 会全部回落到 ``matched=false / rank=-1`` 渲
// 染（视觉上是「整列瞬间变成无 / 未找到」的明显闪动），切平台、切顶级
// tab 都触发。原子赋值后中间态被消除，UI 直接从旧终态跳到新终态。
//
// Stale guard on top of the atomic write: with multiple awaits (tasks
// list + N parallel snapshot fetches) a rapid tab switch can still
// arrive in flight-order rather than user-click order. The guard drops
// any result tied to an obsolete typeKey before we touch reactive state.
const tasksLoadGuard = useStaleGuard();

async function loadTasksAndSnapshotsAtomic(typeKey: string): Promise<void> {
  const my = tasksLoadGuard.issue();
  loading.value = true;
  failed.value = false;
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", { params: { type: typeKey } });
    if (tasksLoadGuard.isStale(my)) return;
    const newTasks: Task[] = r.data?.tasks ?? [];
    const pairs: Record<number, TaskSnapshotPair> = {};
    await Promise.all(newTasks.map(async (t) => {
      try {
        const rr = await sidecar.client.get("/api/monitor/results", {
          params: { task_id: t.id, limit: 2 },
        });
        const rows: any[] = rr.data?.results ?? [];
        pairs[t.id] = {
          latest: resultToSnapshot(rows[0] ?? null),
          prev: resultToSnapshot(rows[1] ?? null),
        };
      } catch {
        // 单任务 snapshot 失败保持空 pair，让 UI 对该行显示 "—"，
        // 不阻塞整批切换。
      }
    }));
    if (tasksLoadGuard.isStale(my)) return;
    tasks.value = newTasks;
    taskSnapshots.value = pairs;
    if (newTasks.length > 0 && (!selectedTaskId.value || !newTasks.find((t) => t.id === selectedTaskId.value))) {
      selectedTaskId.value = newTasks[0].id;
    }
  } catch (e: any) {
    if (tasksLoadGuard.isStale(my)) return;
    failed.value = true;
    tasks.value = [];
    taskSnapshots.value = {};
    if (e?.response?.status !== 503) toast.error(`加载失败：${e?.message ?? e}`);
  } finally {
    // Only the most recent call should clear the spinner.
    if (!tasksLoadGuard.isStale(my)) {
      loading.value = false;
    }
  }
}

const showAddTask = ref(false);
const showBatchImport = ref(false);
// 编辑模式：非空时 AddTaskModal 走 PATCH 路径，关闭后清掉
const editingTask = ref<Task | null>(null);
// 评论批次编辑/删除
const showEditBatch = ref(false);
const editingBatchName = ref("");
const editingBatchTasks = ref<Task[]>([]);
function openEditTask(t: Task) {
  editingTask.value = t;
  showAddTask.value = true;
}
function clearEditOnClose() {
  // AddTaskModal 关闭后回到"新增"语义；不清掉的话下次点新增按钮会带
  // 残留任务进编辑模式。
  if (!showAddTask.value) editingTask.value = null;
}

// Modal 回调 —— 不放 inline `Promise.all(...)` 在模板里：Vue 编译内联
// 箭头函数时把 `Promise.all` 解析路径出错，运行时报
// "Cannot read properties of undefined (reading 'all')"。抽到这里
// setup 作用域里 `Promise` 是确定的全局引用。
// Template ref to whichever BaiduRankingPage is currently mounted (top-level
// baidu tab OR history sub-tab). Only one is mounted at a time, so the same
// ref name is fine.
const baiduPageRef = ref<{ reload: () => Promise<void> } | null>(null);

// 评论模块的 template ref —— 历史报告 drill-down 时父组件先切
// activeTab/commentSubtab，等模块挂载 + atomic load 跑完再调它的
// expose 接口写 selectedCommentTaskId / selectedVideoId；deleteBatch
// 完成后也通过 ref 让模块自己清空被删批次的选中态。
const commentModuleRef = ref<{
  selectBatchAndVideo: (batchName: string, taskId: number) => void;
  clearSelectionIfBatch: (batchName: string) => void;
} | null>(null);

async function onTaskMutatedReload() {
  // Pick typeKey by activeTab — including "baidu" so the call isn't a
  // wasted fetch against a comment-tab type. MonitorView.tasks isn't
  // rendered on baidu tab but the loadTasks call is cheap and keeps
  // the store consistent if the user pivots tabs right after.
  const typeKey =
    activeTab.value === "zhihu" ? "zhihu_question"
    : activeTab.value === "baidu" ? "baidu_keyword"
    : PLATFORM_TYPE[commentSubtab.value];
  // Fan out the mutation signal BEFORE awaiting anything so subscribed
  // pages (e.g. BaiduRankingPage) start their own reload in parallel
  // rather than waiting for MonitorView's loadTasks/snapshots round-trip.
  // The previous baiduPageRef.value?.reload?.() chain silently no-op'd
  // for batch-import on the baidu tab — refs are brittle across HMR
  // re-mounts and modal close timing. Store nonce is the source of truth.
  monitorStatus.bumpTaskMutation();
  await loadTasks(typeKey);
  await loadTaskSnapshots();
  // Keep the ref-based call as belt-and-suspenders for the comment/zhihu
  // tabs where BaiduRankingPage isn't mounted at all (it's a no-op there).
  await baiduPageRef.value?.reload?.();
}

// 评论批次：根据 batchName 拢到子 task 列表，打开编辑 modal
function openEditBatch(batchName: string) {
  editingBatchName.value = batchName;
  editingBatchTasks.value = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  showEditBatch.value = true;
}

// 批量删除：并行 DELETE 所有子 task，全部失败也只弹一条 toast
async function deleteBatch(batchName: string) {
  const childIds = tasks.value
    .filter((t) => parseBatchName(t.name) === batchName)
    .map((t) => t.id);
  if (!childIds.length) return;
  if (!(await confirmDialog(
    `删除批次「${batchName}」下的 ${childIds.length} 条任务？历史结果会一并删除。`,
    { title: "删除批次" },
  ))) return;
  const failures: string[] = [];
  await Promise.all(
    childIds.map((id) =>
      sidecar.client
        .delete(`/api/monitor/tasks/${id}`)
        .catch((e: any) => {
          const detail = e?.response?.data?.detail ?? e?.message ?? e;
          failures.push(`#${id}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
        }),
    ),
  );
  if (!failures.length) {
    toast.success(`已删除 ${childIds.length} 条任务`);
  } else {
    toast.warn(`完成 ${childIds.length - failures.length} / ${childIds.length}，失败 ${failures.length}`);
    console.warn("[batch delete failures]", failures);
  }
  // 刷新任务列表 + 快照；若用户当前停在被删的批次上，回到 L1。
  // selectedCommentTaskId / selectedVideoId 现在归 CommentMonitorModule 管，
  // 通过暴露的 clearSelectionIfBatch 让模块自己回 L1。
  commentModuleRef.value?.clearSelectionIfBatch(batchName);
  await loadTasks(currentTaskType.value);
  await loadTaskSnapshots();
}
const showCookieMgr = ref(false);

// 紧急告警详情 modal —— 两种语义共用一张面板。模态本身不
// 抓数据，全部由 MonitorView 在打开时算好塞进 alertDetail。
const showAlertModal = ref(false);
const alertKind = ref<"zhihu_alert" | "comment_alert">("zhihu_alert");

// 告警详情 modal 用的真实数据（zhihu / comment 两套），openZhihuAlert /
// openCommentAlert 时同步算好。Null = 没数据，模态展示空态。
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
interface ZhihuAlertData {
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
// CommentAlertData / AlertDeletedComment / HeroAlert 类型已抽到
// @/utils/monitor-types，知乎和评论 tab 共享同一份类型契约。
const zhihuAlertData = ref<ZhihuAlertData | null>(null);
const commentAlertData = ref<CommentAlertData | null>(null);

// 紧急告警 hero 改成可翻页的卡片堆叠：多条告警同时存在时，hero 只显示
// 当前一条 + 后面 2 张更小更暗的「卡片影子」，左右两个圆形 chevron 切上
// 一条 / 下一条。1 条告警时影子和 chevron 自动隐藏（hasNav 为 false）。
//
// commentAlerts / commentAlertIdx / currentCommentAlert 已下沉到
// CommentMonitorModule 内部；这里只保留知乎域。父组件 cycleAlert 只对
// kind="zhihu" 有效，评论 hero 的翻页由模块内部处理（模块仍会 emit
// `cycle-alert` 让父组件知道，但当前没有跨域副作用 — 留作未来 hook）。
const zhihuAlertIdx = ref(0);
const currentZhihuAlert = computed(() => zhihuAlerts.value[zhihuAlertIdx.value]);
function cycleAlert(kind: "zhihu" | "comment", dir: 1 | -1) {
  if (kind !== "zhihu") return;
  const list = zhihuAlerts.value;
  if (!list.length) return;
  // wrap-around 让用户在 1↔️N 来回切不会被卡住；按钮始终可点，更直白。
  zhihuAlertIdx.value = (zhihuAlertIdx.value + dir + list.length) % list.length;
}

async function _buildZhihuAlertData(taskId: number, alert: HeroAlert): Promise<ZhihuAlertData | null> {
  const t = tasks.value.find((x) => x.id === taskId);
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

// _buildCommentAlertData 已下沉到 CommentMonitorModule —— 模块自己持有
// tasks/taskSnapshots 的 props，直接算好 CommentAlertData 后 emit
// open-alert payload 给父组件，父组件只负责把 modal 打开 + 填数据。

async function openZhihuAlert(alert?: HeroAlert) {
  alertKind.value = "zhihu_alert";
  commentAlertData.value = null;
  zhihuAlertData.value = null;
  showAlertModal.value = true;
  // 用 currentZhihuAlert 兜底（没显式传时）
  const a = alert ?? currentZhihuAlert.value;
  if (a?.taskId) {
    zhihuAlertData.value = await _buildZhihuAlertData(a.taskId, a);
  }
}
// 评论模块 emit open-alert 时的入口 —— 模块已算好 data，这里只负责
// 切换 alertKind + 灌入 modal 并打开。
function openCommentAlertFromModule(payload: { kind: "comment_alert"; data: CommentAlertData | null }) {
  alertKind.value = payload.kind;
  zhihuAlertData.value = null;
  commentAlertData.value = payload.data;
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
    await loadTasks(currentTaskType.value);
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

// 正在抓取中的 task_id —— 数据现在来自 monitorStatus 全局 store（SSE
// 订阅 + 周期性 /running hydrate）。这里只暴露一个跟原签名兼容的
// `runningTaskIds[id]` 访问器，让模板里的 `runningTaskIds[t.id]` 表达
// 式不用改。
const monitorStatus = useMonitorStatus();
const runningTaskIds = computed<Record<number, true>>(() => {
  const out: Record<number, true> = {};
  for (const id of monitorStatus.runningTaskIds) out[id] = true;
  return out;
});
function markRunning(taskId: number) {
  monitorStatus.markRunning(taskId);
}
function clearRunning(taskId: number) {
  monitorStatus.clearRunning(taskId);
}

async function runNow(taskId: number) {
  // 乐观先标记 —— 后端 run-now 同步返回 {queued:true}，但 SSE 的 started
  // 事件可能要等到 worker 线程拿到 slot 才发出来，中间空窗用户会以为
  // 没反应。先点亮 spinner，SSE 来了顺势接住，failed/finished 时清掉。
  markRunning(taskId);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${taskId}/run-now`);
    toast.info("已派发，正在监测…");
  } catch (e: any) {
    clearRunning(taskId);
    const detail = e?.response?.data?.detail ?? e?.message ?? e;
    toast.error(`派发失败：${detail}`);
  }
}

/**
 * Cooperative cancel —— ask sidecar to abort. State clears via SSE
 * `failed` event (reason "cancelled by user"). See BaiduRankingPage
 * for the same pattern. Single-shot adapters (zhihu / comment) don't
 * yet honor the cancel flag mid-fetch; the cancel call still records
 * intent so a follow-up tick doesn't pile on. For now the worker
 * finishes its current SERP/comment scrape then exits.
 */
async function cancelTask(taskId: number) {
  try {
    const delivered = await monitorStatus.cancel(taskId);
    if (delivered) {
      toast.info("已请求停止，等待当前抓取完成后中断…");
    } else {
      toast.warn("没有可停止的任务（可能已经结束）");
    }
  } catch (e: any) {
    toast.error(`停止失败: ${e?.message ?? e}`);
  }
}

// L1 批次批量派发：取该批次下所有子 task，并行 POST run-now。
// 后端有 per-platform Semaphore（默认 2 并发）+ pacer，前端一次性
// fire N 个不会冲风控；SSE finished 事件已经会对每个子任务调
// _fetchSnapshotPair，L1 行的留存/变化跟着自动刷，这里不重复 reload。
async function runBatch(batchName: string) {
  const child = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  if (!child.length) return;
  // 乐观先标 —— 按钮立刻切到 disabled "监测中…"，避免连点。
  child.forEach((t) => markRunning(t.id));
  const results = await Promise.allSettled(
    child.map((t) => sidecar.client.post(`/api/monitor/tasks/${t.id}/run-now`)),
  );
  const fails = results.filter((r) => r.status === "rejected");
  if (fails.length === 0) {
    toast.info(`已派发 ${child.length} 个任务`);
  } else if (fails.length === child.length) {
    // 全部失败 —— 这些任务永远不会有 SSE 事件进来清 spinner，手动清。
    child.forEach((t) => clearRunning(t.id));
    toast.error(`派发失败：${fails.length}/${child.length}`);
  } else {
    // 部分失败：只清掉失败那部分；成功的依然依赖 SSE 自然完成。
    results.forEach((r, i) => {
      if (r.status === "rejected") clearRunning(child[i].id);
    });
    toast.warn(`派发 ${child.length - fails.length}/${child.length}，${fails.length} 失败`);
  }
}

/**
 * 取消该批次下还在跑的所有子任务。store.cancel() 是幂等的，对非跑动
 * 任务后端返回 cancelled:false —— 我们只统计真的被中断的数量。SSE
 * `failed`（reason=cancelled by user）会负责把 store 状态清掉。
 */
async function cancelBatch(batchName: string) {
  const child = tasks.value.filter((t) => parseBatchName(t.name) === batchName);
  const running = child.filter((t) => runningTaskIds.value[t.id]);
  if (!running.length) {
    toast.warn("批次内没有正在跑的任务");
    return;
  }
  const results = await Promise.allSettled(
    running.map((t) => monitorStatus.cancel(t.id)),
  );
  const delivered = results.filter(
    (r) => r.status === "fulfilled" && r.value === true,
  ).length;
  if (delivered > 0) {
    toast.info(`已请求停止 ${delivered}/${running.length} 个任务`);
  } else {
    toast.warn("没有可停止的任务（可能已经完成）");
  }
}

// 历史报告 drill-down 跳转 ── RetentionPage 行点击 emit navigate({platform, batchName, taskId}) → 这里。
// 切到平台评论 tab、平台 chip、批次 L2、视频 L3。靠 nextTick 等
// watch(activeTab) / watch(commentSubtab) 的 atomic-load 跑完，再通过模块
// 暴露的 selectBatchAndVideo 写入 selectedCommentTaskId/selectedVideoId，
// 否则 atomic-load 内部的「selectedTaskId.value = newTasks[0].id」会盖
// 掉我们的设置。
async function goToCommentTask(payload: {
  platform: "bilibili_comment" | "douyin_comment" | "kuaishou_comment";
  batchName: string;
  taskId: number;
}) {
  const subtabKey: CommentPlatform =
    payload.platform === "bilibili_comment" ? "bilibili"
    : payload.platform === "douyin_comment" ? "douyin"
    : "kuaishou";
  activeTab.value = "comment";
  commentSubtab.value = subtabKey;
  await nextTick();
  await nextTick();  // 一个 tick 不够；watch handler 是 async，等两 tick 让 atomic load 跑完
  commentModuleRef.value?.selectBatchAndVideo(payload.batchName, payload.taskId);
}

async function goToZhihuTask(payload: { taskId: number }) {
  activeTab.value = "zhihu";
  await nextTick();
  await nextTick();
  selectedTaskId.value = payload.taskId;
}

function goToBaiduTask(_payload: { taskId: number }) {
  // MVP: switch to baidu workspace tab. User can then click the task row there.
  activeTab.value = "baidu";
}

// batchRunState 已下沉到 CommentMonitorModule —— 评论 tab 的批次按钮
// 文案 / 禁用态在模块内由 props.runningTaskIds 衍生计算。

let stopMonitorBus: (() => void) | null = null;
function startMonitorBus() {
  stopMonitorBus = subscribe("/api/monitor/events", {
    started: (d: any) => {
      // adapter 真正开始 fetch 了 —— 把 spinner 接住（runNow 也会乐观标，
      // 这里只是兜底：定时调度的任务也能在 UI 上看见正在跑）。
      if (typeof d.task_id === "number" && d.task_id > 0) markRunning(d.task_id);
    },
    finished: (d: any) => {
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) {
        t.last_check_at = d.at;
        t.last_status = d.result?.status ?? t.last_status;
      }
      if (selectedTaskId.value === d.task_id) {
        loadResults(d.task_id);
      }
      // 抓完一条立刻刷它的 latest/prev snapshot —— 评论 tab 用来更新
      // 留存/被删评论列表；知乎 tab 用来更新"上次/变化"列。
      if (activeTab.value === "zhihu" || activeTab.value === "comment") {
        _fetchSnapshotPair(d.task_id);
      }
      clearRunning(d.task_id);
    },
    alert: (d: any) => {
      toast.warn(`任务 #${d.task_id} 触发告警`);
    },
    failed: (d: any) => {
      const t = tasks.value.find((x) => x.id === d.task_id);
      if (t) t.last_status = "failed";
      clearRunning(d.task_id);
      const detail = d.error ? `：${String(d.error).split("\n")[0]}` : "";
      toast.error(`任务 #${d.task_id} 抓取失败${detail}`);
    },
    captcha_required: (d: any) => {
      toast.warn(
        `任务 #${d.task_id} 百度要求验证码 — 浏览器已弹出，请在 90 秒内完成验证`,
      );
    },
    captcha_resolved: (d: any) => {
      toast.success(`任务 #${d.task_id} 已通过验证码，继续抓取`);
    },
    captcha_timeout: (d: any) => {
      toast.error(`任务 #${d.task_id} 验证码等待超时，任务已标记为失败`);
    },
  });
}

// 卡位趋势（Y 轴 = matched_count）—— 之前用 rank（越小越好），现在统一
// 改成命中数语义跟新 KPI「卡位数量」对齐。无 metric 的旧 result 当 0 处理。
const sparkPoints = computed(() => {
  if (demoMode.value) return SAMPLE_SPARK_RANK;
  return [...taskResults.value]
    .reverse()
    .map((r) => Number((r as any).metric?.matched_count ?? 0));
});

watch(activeTab, async (t) => {
  if (t === "zhihu") {
    await loadTasksAndSnapshotsAtomic("zhihu_question");
  } else if (t === "comment") {
    await loadTasksAndSnapshotsAtomic(PLATFORM_TYPE[commentSubtab.value]);
  }
  // 历史报告 sub-page self-loads via RetentionPage / ZhihuRankingPage onMounted
});

watch(commentSubtab, async (s) => {
  if (activeTab.value !== "comment") return;
  await loadTasksAndSnapshotsAtomic(PLATFORM_TYPE[s]);
});

watch(selectedTaskId, async (id) => {
  if (id != null && id > 0) await loadResults(id);
});

const selectedTask = computed(() =>
  tasks.value.find((t) => t.id === selectedTaskId.value) ?? null,
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

// 评论 tab 三级导航 / Real-data unifiers / commentAlerts 全部下沉到
// CommentMonitorModule。父组件仅保留 zhihuAlerts。

// ── 告警 hero（zhihu）computed ────────────────────────────────────────
//
//   zhihu  ⇒ task 撞 failed / risk_control / 排名掉出 top_n / 排名暴跌 ≥6
//
// 一类任务最多堆 3 张 hero（match 设计稿的卡片堆叠），多了用户在 chevron
// 之间切。空时 hero 整段不显示。
const zhihuAlerts = computed<HeroAlert[]>(() => {
  if (demoMode.value || activeTab.value !== "zhihu") return [];
  const out: HeroAlert[] = [];
  for (const t of tasks.value) {
    const pair = taskSnapshots.value[t.id];
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

// commentAlerts / openCommentDetail / backToCommentList / selectVideo /
// closeVideoDetail / watch(commentSubtab) 已下沉到 CommentMonitorModule。

// tabCounts 计数徽章已下线（顶部 pivot 不再展示 4/1/12 数字胶囊）；
// 如需重启回归，把上面的 pill 模板 + 这里的 computed 一起恢复。

onMounted(async () => {
  try {
    await whenReady();
    if (!cfg.data) await cfg.load();
    if (activeTab.value === "zhihu") {
      await loadTasks("zhihu_question");
      await loadTaskSnapshots();
    } else if (activeTab.value === "comment") {
      await loadTasks(currentTaskType.value);
      await loadTaskSnapshots();
    }
    // 历史报告 sub-page self-loads via RetentionPage / ZhihuRankingPage onMounted
    startMonitorBus();
    // Force a /running hydrate so navigating away+back doesn't leave
    // stale state. The store also polls every 30 s, but mount-time
    // hydrate eliminates the visible delay.
    void monitorStatus.hydrate();
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
  { k: "baidu", l: "百度排名", ic: "search" },
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
              ? "知乎问题监测"
              : activeTab === "comment"
                ? "评论留存率监控"
                : activeTab === "baidu"
                  ? "百度排名 · 关键词监控"
                  : "历史监测报告"
          }}
        </div>
        <div class="mt-1 text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
          {{
            activeTab === "zhihu"
              ? "回答排名"
              : activeTab === "comment"
                ? "B站/抖音/快手"
                : activeTab === "baidu"
                  ? "百度搜索 · 默认 + 最新资讯 · 自家命中"
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
                  @click.stop="cancelTask(t.id)"
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
                  @click.stop="runNow(t.id)"
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
                  @click.stop="openEditTask(t)"
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
                  @click.stop="deleteTask(t.id)"
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
                    @click="openEditTask(selectedTask)"
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
    </template>

    <!-- ── 平台评论 ─────────────────────────────────────────────── -->
    <template v-else-if="activeTab === 'comment'">
      <CommentMonitorModule
        ref="commentModuleRef"
        :tasks="tasks"
        :task-snapshots="taskSnapshots"
        v-model:comment-subtab="commentSubtab"
        :loading="loading"
        :failed="failed"
        :running-task-ids="runningTaskIds"
        :demo-mode="demoMode"
        :active-tab="activeTab"
        @add-task="showAddTask = true"
        @import-batch="showBatchImport = true"
        @cookie-mgr="showCookieMgr = true"
        @edit-batch="(name) => openEditBatch(name)"
        @delete-batch="(name) => deleteBatch(name)"
        @run-batch="(name) => runBatch(name)"
        @cancel-batch="(name) => cancelBatch(name)"
        @run-now="(id) => runNow(id)"
        @alert-action="(act) => onAlertAction(act)"
        @open-alert="openCommentAlertFromModule"
        @cycle-alert="(dir) => cycleAlert('comment', dir)"
      />
    </template>

    <!-- ── 百度关键词（顶级 tab，渲染同款 BaiduRankingPage）────────── -->
    <template v-else-if="activeTab === 'baidu'">
      <BaiduRankingPage
        ref="baiduPageRef"
        @add-task="showAddTask = true"
        @batch-import="showBatchImport = true"
        @edit-task="(t) => { editingTask = t as any; showAddTask = true; }"
      />
    </template>

    <!-- ── 历史报告（重构后：sub-pivot + 两个子页）──────────────────── -->
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
        <!-- sub-pivot：平台评论 / 知乎排名 / 百度排名 -->
        <div class="mb-3 flex-shrink-0 flex justify-between items-center">
          <div>
            <div class="font-display text-[14px] font-semibold">
              {{
                historySubtab === 'retention' ? '评论平台 · 留存率分析'
                : historySubtab === 'zhihu' ? '知乎排名 · 品牌占有率分析'
                : '百度 SEO · 关键词排名分析'
              }}
            </div>
          </div>
          <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }">
            <button
              @click="historySubtab = 'retention'"
              class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
              :style="{
                background: historySubtab === 'retention' ? 'var(--dark)' : 'transparent',
                color: historySubtab === 'retention' ? 'var(--card)' : 'var(--ink-3)',
              }"
            >平台评论</button>
            <button
              @click="historySubtab = 'zhihu'"
              class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
              :style="{
                background: historySubtab === 'zhihu' ? 'var(--dark)' : 'transparent',
                color: historySubtab === 'zhihu' ? 'var(--card)' : 'var(--ink-3)',
              }"
            >知乎排名</button>
            <button
              @click="historySubtab = 'baidu'"
              class="px-4 py-1.5 rounded-full text-[12.5px] font-medium"
              :style="{
                background: historySubtab === 'baidu' ? 'var(--dark)' : 'transparent',
                color: historySubtab === 'baidu' ? 'var(--card)' : 'var(--ink-3)',
              }"
            >百度排名</button>
          </div>
        </div>

        <!--
          history sub-page wrapper —— overflow-hidden 让 sub-page 自己管
          滚动。每个 sub-page 的根 div 用 h-full + flex 列布局，把滚动
          锁在「问题列表 / 关键词列表」区块里，KPI + 图表保持固定。
        -->
        <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
          <RetentionPage v-if="historySubtab === 'retention'" @navigate="goToCommentTask" />
          <ZhihuRankingPage v-else-if="historySubtab === 'zhihu'" @navigate="goToZhihuTask" />
          <BaiduSEOAnalytics v-else-if="historySubtab === 'baidu'" @navigate="goToBaiduTask" />
        </div>
      </section>
    </template>

    <!-- ── Modals ──────────────────────────────────────────────── -->
    <AddTaskModal
      :open="showAddTask"
      :editing-task="editingTask as any"
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
      @update:open="(v) => { showAddTask = v; clearEditOnClose(); }"
      @created="onTaskMutatedReload"
      @updated="onTaskMutatedReload"
    />
    <EditBatchModal
      v-model:open="showEditBatch"
      :batch-name="editingBatchName"
      :tasks="editingBatchTasks as any"
      @updated="onTaskMutatedReload"
    />
    <BatchImportTaskModal
      v-model:open="showBatchImport"
      :default-type="(currentTaskType as any)"
      @imported="onTaskMutatedReload"
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
      :zhihu-data="zhihuAlertData ?? undefined"
      :comment-data="commentAlertData ?? undefined"
      @action="onAlertAction"
    />
  </div>
</template>
