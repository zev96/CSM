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

import AddTaskModal from "@/components/monitor/AddTaskModal.vue";
import AlertDetailModal from "@/components/monitor/AlertDetailModal.vue";
import BatchImportTaskModal from "@/components/monitor/BatchImportTaskModal.vue";
import CookieManagerModal from "@/components/monitor/CookieManagerModal.vue";
import EditBatchModal from "@/components/monitor/EditBatchModal.vue";
import CommentMonitorModule from "@/components/monitor/CommentMonitorModule.vue";
import ZhihuMonitorModule, { type ZhihuAlertData } from "@/components/monitor/ZhihuMonitorModule.vue";
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
} from "@/utils/monitor-batch";
import {
  type Task,
  type CommentPlatform,
  type CommentAlertData,
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

const loading = ref(false);
const failed = ref(false);

// 评论 tab 的三级导航 / SAMPLE_COMMENTS / SAMPLE_VIDEOS / SAMPLE_RETENTION /
// SAMPLE_DELETED / PLATFORMS / truncate15 / COMMENT_SPARK_LABELS /
// commentMonitorState / ensureCommentState 全部下沉到
// components/monitor/CommentMonitorModule.vue（Phase 2 拆分）。
//
// 知乎 tab 的 SAMPLE_ZHIHU / SAMPLE_TOP3 / SAMPLE_SPARK_RANK /
// ZHIHU_SPARK_LABELS / zhihuMonitorState / ensureZhihuState /
// toggleMonitor / changeSchedule / selectedTaskId / taskResults /
// loadResults 全部下沉到 components/monitor/ZhihuMonitorModule.vue
// （Phase 3 拆分）。

// ── Demo mode: sidecar 不可用或表为空 ──────────────────────────────────
const demoMode = computed(() => failed.value || (!loading.value && tasks.value.length === 0));

// ── Loaders ─────────────────────────────────────────────────────────────
async function loadTasks(typeKey: string) {
  // 知乎 tab 的"默认选中第一条任务"现在由 ZhihuMonitorModule 自己接管
  // （watch(() => props.tasks, ..., immediate: true)），父组件不再写
  // selectedTaskId，避免拆完模块后两端都摸同一份 ref。
  loading.value = true;
  failed.value = false;
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: typeKey },
    });
    tasks.value = r.data.tasks ?? [];
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
    // selectedTaskId 不再在父组件管 —— ZhihuMonitorModule 内部 watch
    // props.tasks 自动 fallback 到第一条任务，跟拆分前同语义。
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

// 知乎模块的 template ref —— 历史报告 drill-down 时父组件先切到 zhihu
// activeTab，等模块挂载 + atomic load 跑完再调它的 selectTask 写入
// 选中任务；deleteTask 通过 ref 让模块清掉被删任务的选中态；SSE
// finished 事件转发给模块刷新 taskResults。
const zhihuModuleRef = ref<{
  selectTask: (taskId: number) => void;
  onTaskFinished: (taskId: number) => void;
  handleTaskDeleted: (taskId: number) => void;
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

// 告警详情 modal 用的真实数据（zhihu / comment 两套）。
// _buildZhihuAlertData / _buildCommentAlertData 已下沉到各自子模块：
// 模块自己持有 tasks/taskSnapshots 的 props，直接算好 data 后 emit
// open-alert payload 给父组件，父组件只负责把 modal 打开 + 填数据。
// CommentAlertData / AlertDeletedComment / HeroAlert 类型在
// @/utils/monitor-types；ZhihuAlertData 在 ZhihuMonitorModule 内并 export。
const zhihuAlertData = ref<ZhihuAlertData | null>(null);
const commentAlertData = ref<CommentAlertData | null>(null);

// 知乎模块 emit open-alert 时的入口 —— 模块已算好 data，这里只负责
// 切换 alertKind + 灌入 modal 并打开。
function openZhihuAlertFromModule(payload: { kind: "zhihu_alert"; data: ZhihuAlertData | null }) {
  alertKind.value = payload.kind;
  commentAlertData.value = null;
  zhihuAlertData.value = payload.data;
  showAlertModal.value = true;
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
    // selectedTaskId / taskResults 归 ZhihuMonitorModule 管，通过暴露的
    // handleTaskDeleted 让模块自己清掉被删任务的选中态 + 历史。
    zhihuModuleRef.value?.handleTaskDeleted(taskId);
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
  // selectedTaskId 现在归 ZhihuMonitorModule 管 —— 切到 zhihu tab 后等
  // 模块挂载 + atomic load 跑完，再通过暴露的 selectTask 写入。两 tick
  // 让 watch(activeTab) handler 跑完，跟 goToCommentTask 同语义。
  activeTab.value = "zhihu";
  await nextTick();
  await nextTick();
  zhihuModuleRef.value?.selectTask(payload.taskId);
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
      // 抓完一条立刻刷它的 latest/prev snapshot —— 评论 tab 用来更新
      // 留存/被删评论列表；知乎 tab 用来更新"上次/变化"列。
      if (activeTab.value === "zhihu" || activeTab.value === "comment") {
        _fetchSnapshotPair(d.task_id);
      }
      // 转发给知乎模块：若它当前正在看 d.task_id，刷新 taskResults
      // 让详情卡片的 sparkline / 前 N 答案随之更新。模块 ref 没挂载时
      // 自动 no-op（其它 tab 没必要拉 results）。
      zhihuModuleRef.value?.onTaskFinished(d.task_id);
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

// sparkPoints / selectedTask / topAnswersForSelectedTask / ZhihuTopAnswer /
// sampleSelectedZhihu / pickSampleZhihu / zhihuAlerts / watch(selectedTaskId)
// 全部下沉到 ZhihuMonitorModule。

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
      <ZhihuMonitorModule
        ref="zhihuModuleRef"
        :tasks="tasks"
        :task-snapshots="taskSnapshots"
        :loading="loading"
        :failed="failed"
        :running-task-ids="runningTaskIds"
        :demo-mode="demoMode"
        :active-tab="activeTab"
        @add-task="showAddTask = true"
        @import-batch="showBatchImport = true"
        @cookie-mgr="showCookieMgr = true"
        @edit-task="(t) => openEditTask(t)"
        @delete-task="(id) => deleteTask(id)"
        @run-task="(id) => runNow(id)"
        @cancel-task="(id) => cancelTask(id)"
        @alert-action="(act) => onAlertAction(act as any)"
        @open-alert="openZhihuAlertFromModule"
        @cycle-alert="() => {}"
      />
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
        @cycle-alert="() => {}"
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
