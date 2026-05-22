<script setup lang="ts">
/**
 * 视频抓取 — 首页 Row 2 第 4 张监测卡。
 *
 *   ┌─────────────────────────────────────────┐
 *   │ MINING · 视频抓取                  [→]  │
 *   │ 218                                     │
 *   │ 已抓取 · 2 任务运行中                    │
 *   ├─────────────────────────────────────────┤
 *   │ 宠物家庭吸尘器     124/150     [进行中] │
 *   │ 母婴加湿器          52/52     [完成]   │
 *   │ 投影仪家用           0/60     [排队]   │
 *   │ 千元降噪耳机        42/80     [进行中] │
 *   └─────────────────────────────────────────┘
 *
 * 数据：useMiningStore — jobs[] + 每个 job.progress.{platform:{got,target}}。
 * 大数字 = 所有 job 已抓取视频累加（progress.got 之和），任务列表按状态排序
 * （running > pending/queued > done/failed），最多 4 条。
 */
import { computed, onMounted } from "vue";
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
  got: number;
  target: number;
  state: "running" | "queued" | "done" | "failed";
}

// MiningJob.progress 是平台 → {got,target} 的 map。聚合到 job 级要 sum 一下。
function aggregateJob(j: MiningJob): { got: number; target: number } {
  let got = 0;
  let target = 0;
  for (const p of j.platforms) {
    const pr = j.progress?.[p];
    if (pr) {
      got += Number(pr.got ?? 0);
      target += Number(pr.target ?? 0);
    } else {
      target += j.target_per_platform;
    }
  }
  return { got, target };
}

function classifyState(j: MiningJob): Row["state"] {
  const s = j.status?.toLowerCase() ?? "";
  if (s === "running") return "running";
  if (s === "pending" || s === "queued") return "queued";
  if (s === "failed" || s === "cancelled") return "failed";
  return "done"; // done / partial_done / 其它终态
}

const STATE_ORDER: Record<Row["state"], number> = {
  running: 0,
  queued: 1,
  done: 2,
  failed: 3,
};

const rows = computed<Row[]>(() =>
  [...store.jobs]
    .map((j) => {
      const agg = aggregateJob(j);
      return {
        id: j.id,
        keyword: j.keyword,
        got: agg.got,
        target: agg.target,
        state: classifyState(j),
      };
    })
    .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state])
    .slice(0, 4),
);

const totalScraped = computed(() =>
  store.jobs.reduce((acc, j) => acc + aggregateJob(j).got, 0),
);

const runningCount = computed(
  () => store.jobs.filter((j) => classifyState(j) === "running").length,
);

const subLabel = computed(() => {
  if (store.jobs.length === 0) return "暂无抓取任务";
  if (runningCount.value === 0) return "已抓取 · 全部任务已完成";
  return `已抓取 · ${runningCount.value} 任务运行中`;
});

onMounted(async () => {
  try {
    await whenReady();
    await store.loadJobs(50);
  } catch {
    /* 静默：空状态文案撑起占位 */
  }
});

// 状态 chip 配色，对齐 Design.md §2 "派生色"。
function chipStyle(state: Row["state"]) {
  if (state === "running")
    return { background: "var(--primary-soft)", color: "var(--primary-deep)" };
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
  if (state === "running") return "进行中";
  if (state === "queued") return "排队";
  if (state === "failed") return "失败";
  return "完成";
}
</script>

<template>
  <section
    class="relative flex h-full flex-col overflow-hidden"
    :style="{
      background: 'var(--card)',
      borderRadius: 'var(--radius-card)',
      border: '1px solid var(--line)',
      padding: '16px',
    }"
  >
    <!-- 标题区 -->
    <div class="mb-2 flex flex-shrink-0 items-start justify-between gap-2">
      <div class="min-w-0">
        <div
          class="text-[10.5px] font-medium uppercase tracking-[1.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          Mining · 视频抓取
        </div>
        <div class="mt-1 flex items-baseline gap-2">
          <div
            class="font-display font-bold"
            :style="{
              fontSize: '26px',
              lineHeight: 1,
              letterSpacing: '-0.5px',
            }"
          >
            {{ totalScraped }}
          </div>
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
            {{ subLabel }}
          </div>
        </div>
      </div>
      <button
        type="button"
        class="inline-flex h-7 flex-shrink-0 items-center gap-1 rounded-full px-2.5 text-[11.5px]"
        :style="{
          background: 'var(--card-2)',
          color: 'var(--ink-2)',
          border: '1px solid var(--line)',
        }"
        @click="router.push({ name: 'mining' })"
      >
        详情
        <Icon name="arrowRight" :size="10" />
      </button>
    </div>

    <!-- 任务列表 -->
    <div
      v-if="rows.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无抓取任务<br />
      <span class="text-[11px]">前往引流中心新建任务</span>
    </div>
    <div v-else class="mt-2 flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto">
      <div
        v-for="r in rows"
        :key="r.id"
        class="flex items-center gap-2.5 rounded-[10px] p-2.5"
        :style="{
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
        }"
      >
        <div class="min-w-0 flex-1 truncate text-[12px] font-semibold">
          {{ r.keyword }}
        </div>
        <span
          class="font-mono flex-shrink-0 tabular-nums text-[11px]"
          :style="{ color: 'var(--ink-2)' }"
        >
          {{ r.got }}/{{ r.target }}
        </span>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center rounded-full px-2 text-[10.5px] font-medium"
          :style="chipStyle(r.state)"
        >
          {{ chipLabel(r.state) }}
        </span>
      </div>
    </div>
  </section>
</template>
