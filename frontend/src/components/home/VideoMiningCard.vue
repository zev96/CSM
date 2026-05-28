<script setup lang="ts">
/**
 * 视频抓取 — 首页 Row 2 第 4 张监测卡。
 *
 *   ┌─────────────────────────────────────────┐
 *   │ 视频抓取                          [→]   │
 *   │ 13                                       │  ← 当前实际视频总数
 *   │  (没有 sparkline，hero 直接接列表)        │
 *   │ 宠物家庭吸尘器                 [进行中]  │  ← hover 切换顶部
 *   │ 无线吸尘器推荐                 [已完成]  │     13 → row.commented/video
 *   │ ...                                     │
 *   └─────────────────────────────────────────┘
 *
 * 数量 / 状态都按「当前实际数据」算（不是抓取时的快照）：
 *   - 顶部数字 = 各任务 video_count 之和（后端已过滤用户删除的 excluded 视频）
 *   - 行状态 = 跟引流任务卡同款：抓取中 / 进行中(还有没评论) / 已完成 / 失败
 *   - 每次进首页 onMounted 重新 loadJobs，所以删/评论后回首页即时反映
 *
 * 交互：
 *   - 默认顶部：totalVideos（所有任务实际视频数之和）
 *   - hover 某行 → 顶部数字切到该任务 commentedCount/videoCount
 *   - 行 hover 高亮 + 阴影凸起；点击行 → router.push 引流中心 + 该 job
 *
 * 原副标 "全部任务已完成 · 共 X 个任务" 删除（用户要求 hero 副位只在
 * hover 时承载关键词，不展示全局统计）。
 *
 * rows 全量映射（不再 slice 0-4）—— 列表 flex-1 + overflow-y-auto
 * 自然处理高度。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { useMiningStore, type MiningJob } from "@/stores/mining";
import { useSidecarReady } from "@/composables/useSidecarReady";

const store = useMiningStore();
const router = useRouter();
const { whenReady } = useSidecarReady();

interface Row {
  id: number;
  keyword: string;
  videoCount: number;     // 当前实际视频数（后端 video_count，已排除删除的）
  commentedCount: number; // 已评论视频数
  state: "running" | "queued" | "in_progress" | "done" | "failed";
}

// 跟引流任务卡（TaskListItem）同款状态语义：抓取层 running/pending/failed
// 直接映射；done/partial_done 再按「标注进度」细分 —— 全部已评论=已完成，
// 还有没评论=进行中。这样首页卡片跟引流中心列表显示一致的真实状态。
function classifyState(j: MiningJob): Row["state"] {
  const s = j.status?.toLowerCase() ?? "";
  if (s === "running") return "running";
  if (s === "pending" || s === "queued") return "queued";
  if (s === "failed" || s === "cancelled") return "failed";
  const total = j.video_count ?? 0;
  const commented = j.commented_count ?? 0;
  if (total > 0 && commented < total) return "in_progress";
  return "done";
}

const STATE_ORDER: Record<Row["state"], number> = {
  running: 0,
  queued: 1,
  in_progress: 2,
  done: 3,
  failed: 4,
};

// 首页这张卡列表最多 15 条（避免数据多时把列表撑太长 / 拉过多 DOM）；
// 用户要看完整列表走右上「→」详情按钮跳到引流中心。
const rows = computed<Row[]>(() =>
  [...store.jobs]
    .map((j) => ({
      id: j.id,
      keyword: j.keyword,
      videoCount: j.video_count ?? 0,
      commentedCount: j.commented_count ?? 0,
      state: classifyState(j),
    }))
    .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state])
    .slice(0, 15),
);

// 首页大数字 = 所有任务当前实际视频数之和（用后端已过滤删除的 video_count，
// 不再用抓取进度 progress.got —— 用户抓取后删了视频要按实际剩余数显示）。
const totalVideos = computed(() =>
  store.jobs.reduce((acc, j) => acc + (j.video_count ?? 0), 0),
);

// hover 状态 —— 切顶部数字 + 副词
const hoveredIdx = ref<number | null>(null);
const selectedRow = computed<Row | null>(() =>
  hoveredIdx.value === null ? null : rows.value[hoveredIdx.value] ?? null,
);

const heroNumber = computed(() =>
  selectedRow.value
    ? `${selectedRow.value.commentedCount}/${selectedRow.value.videoCount}`
    : String(totalVideos.value),
);
// heroLabel 已彻底下线（用户要求）—— 顶部只保留大数字 30/30，副位文字
// "已抓取"删除。下方行 + 状态 pill 已经把语义说清，副词冗余。

onMounted(async () => {
  try {
    await whenReady();
    await store.loadJobs(50);
  } catch {
    /* 静默 */
  }
});

// 状态 chip 配色。"进行中"用 yellow-soft 跟知乎 warn 同档（主色按
// 约定只保留在按钮 + hover 上）。
function chipStyle(state: Row["state"]) {
  if (state === "running")
    return { background: "rgba(238,106,42,0.12)", color: "var(--primary-deep)" };
  if (state === "in_progress")
    return { background: "var(--yellow-soft)", color: "#7a5400" };
  if (state === "queued")
    return {
      background: "rgba(28,26,23,0.06)",
      color: "var(--ink-2)",
    };
  if (state === "failed")
    return { background: "#f3d3cd", color: "#a3382a" };
  return { background: "#dde7d2", color: "#4d6b2f" };
}

function chipLabel(state: Row["state"]) {
  if (state === "running") return "抓取中";
  if (state === "in_progress") return "进行中";
  if (state === "queued") return "排队";
  if (state === "failed") return "失败";
  return "已完成";
}

// 点击关键词行 → 跳引流中心 + 该 job。MiningView 暂不读 job query，
// 透传留待后续接 job 路由 highlight。
function onRowClick(r: Row) {
  router.push({
    name: "mining",
    query: { job: r.id },
  });
}
</script>

<template>
  <section
    class="card-frosted relative flex h-full flex-col overflow-hidden"
    :style="{ padding: '16px' }"
  >
    <!-- 标题区 -->
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
        视频抓取
      </div>
      <button
        type="button"
        class="trend-detail inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full"
        title="详情"
        @click="router.push({ name: 'mining' })"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <!--
      大数字（hover 行时切到该行 got/target）。
      副词 "已抓取" / 关键词 swap 都按用户要求下线 —— 顶部只展示数字。
    -->
    <div class="mt-2 flex flex-shrink-0 items-baseline gap-2">
      <div
        class="font-display font-bold"
        :style="{
          fontSize: '24px',
          lineHeight: 1,
          letterSpacing: '-0.5px',
          color: 'var(--ink)',
        }"
      >
        {{ heroNumber }}
      </div>
    </div>
    <!-- 用 mt-3 留出跟 KeywordTrendCard sparkline 后 mb-3 同款节奏 -->
    <div class="mt-3 flex-shrink-0"></div>

    <!-- 任务列表 -->
    <div
      v-if="rows.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无抓取任务<br />
      <span class="text-[11px]">前往引流中心新建任务</span>
    </div>
    <div v-else class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <div
        v-for="(r, idx) in rows"
        :key="r.id"
        class="row flex items-center gap-2 rounded-[10px] px-2.5 py-2"
        :class="{ 'row-active': idx === hoveredIdx }"
        @mouseenter="hoveredIdx = idx"
        @mouseleave="hoveredIdx = null"
        @click="onRowClick(r)"
      >
        <div class="min-w-0 flex-1 truncate text-[12px]">
          {{ r.keyword }}
        </div>
        <!--
          got/target 数字已从行中移除：hover 时顶部 hero 已经显示了
          该行的 30/30，行内再重复一份显得吵。状态 pill 单独留着，
          因为它是离散语义（完成/失败/进行中），数字代替不了。
        -->
        <span
          class="inline-flex h-5 flex-shrink-0 items-center rounded-full px-2 text-[10.5px] font-medium"
          :style="
            idx === hoveredIdx
              ? { background: '#ffffff', color: chipStyle(r.state).color }
              : chipStyle(r.state)
          "
        >
          {{ chipLabel(r.state) }}
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.trend-detail {
  background: rgba(28, 26, 23, 0.04);
  color: var(--ink-2);
  border: 1px solid rgba(28, 26, 23, 0.06);
  transition: background-color 0.12s ease;
}
.trend-detail:hover {
  background: rgba(28, 26, 23, 0.08);
}

.row {
  background: transparent;
  color: var(--ink);
  transition:
    background-color 0.12s ease,
    color 0.12s ease,
    box-shadow 0.12s ease;
  cursor: pointer;
}
.row-active {
  background: var(--primary);
  color: #ffffff;
  box-shadow:
    0 6px 16px -2px rgba(238, 106, 42, 0.45),
    0 2px 6px rgba(28, 26, 23, 0.06);
}
</style>
