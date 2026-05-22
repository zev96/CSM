<script setup lang="ts">
/**
 * 评论留存率 — Row 2 第 3 张监测卡。
 *
 *   ┌─────────────────────────────────────────┐
 *   │ MONITOR · 评论留存                [详情→]│
 *   │ 57%                                     │
 *   │ ◢ sparkline ◣                            │
 *   │ 周一  周二 ... 今天                       │
 *   │ ┌─ B 站  ████░░░ 8/14  57% ┐            │
 *   │ ┌─ 抖音  ███████ 12/12 100% ┐           │
 *   │ ┌─ 快手  ███████ 5/5  100% ┐            │
 *   └─────────────────────────────────────────┘
 *
 * 数据：GET /api/monitor/summary, 各平台 task.latest.metric.matched 聚合。
 * 留存率 = matched / status==ok 的总数。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

const sidecar = useSidecar();
const router = useRouter();
const { whenReady } = useSidecarReady();

interface Row {
  key: string;
  label: string;
  color: string;
  retained: number;
  total: number;
}

interface PlatformView {
  task_count: number;
  tasks: Array<{
    id: number;
    name: string;
    latest: {
      status: string;
      metric: Record<string, any>;
    } | null;
  }>;
}
const summary = ref<Record<string, PlatformView>>({});
const loaded = ref(false);

const PLATFORM_MAP = [
  { key: "bilibili_comment", label: "B 站", color: "var(--primary)" },
  { key: "douyin_comment", label: "抖音", color: "#1e1c19" },
  { key: "kuaishou_comment", label: "快手", color: "var(--yellow)" },
];

// metric.matched=true ⇒ 该 task 监测的评论仍可见，记 1。status≠ok 不进 total。
function aggregate(p: PlatformView | undefined) {
  if (!p || !p.tasks.length) return null;
  let retained = 0;
  let total = 0;
  for (const t of p.tasks) {
    if (!t.latest) continue;
    if (t.latest.status !== "ok") continue;
    const m = t.latest.metric;
    if (!m) continue;
    total += 1;
    if (m.matched === true) retained += 1;
  }
  if (total === 0) return null;
  return { retained, total };
}

const rows = computed<Row[]>(() => {
  if (!loaded.value) return [];
  return PLATFORM_MAP.map((p) => {
    const agg = aggregate(summary.value[p.key]);
    if (!agg) return null;
    return {
      key: p.key,
      label: p.label,
      color: p.color,
      retained: agg.retained,
      total: agg.total,
    };
  }).filter((r): r is Row => r !== null);
});

const totalRetained = computed(() =>
  rows.value.reduce((a, r) => a + r.retained, 0),
);
const totalAll = computed(() => rows.value.reduce((a, r) => a + r.total, 0));
const pct = computed(() =>
  totalAll.value > 0
    ? Math.round((totalRetained.value / totalAll.value) * 100)
    : 0,
);

// fallback sparkline — 7 个点轻微下行，对应"近 7 天有人删评论"语义。
const SPARK_FALLBACK = [72, 70, 68, 65, 62, 58, 57];
const SPARK_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "今天"];
const sparkColor = computed(() => {
  if (pct.value >= 80) return "var(--green)";
  if (pct.value >= 50) return "var(--primary)";
  return "var(--red)";
});

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/summary");
    summary.value = r.data.platforms ?? {};
  } catch {
    /* 静默 */
  } finally {
    loaded.value = true;
  }
});

function ratio(r: Row) {
  return r.total > 0 ? r.retained / r.total : 0;
}
function rowBarColor(r: Row) {
  return ratio(r) < 0.8 ? "var(--red)" : "var(--green)";
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
    <div class="mb-2 flex flex-shrink-0 items-start justify-between">
      <div class="min-w-0">
        <div
          class="text-[10.5px] font-medium uppercase tracking-[1.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          Monitor · 评论留存
        </div>
        <div
          v-if="rows.length > 0"
          class="font-display mt-1 font-bold"
          :style="{
            fontSize: '26px',
            lineHeight: 1,
            letterSpacing: '-0.5px',
            color: sparkColor,
          }"
        >
          {{ pct }}%
        </div>
        <div
          v-else
          class="font-display mt-1 font-semibold"
          :style="{ fontSize: '13px', color: 'var(--ink-3)' }"
        >
          评论留存率
        </div>
        <div class="mt-0.5 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          近 7 天
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
        @click="router.push({ name: 'monitor', query: { tab: 'comment' } })"
      >
        详情
        <Icon name="arrowRight" :size="10" />
      </button>
    </div>

    <!-- Sparkline -->
    <div class="mb-2 flex-shrink-0">
      <Sparkline
        :points="SPARK_FALLBACK"
        :axis-labels="SPARK_LABELS"
        :height="38"
        :stroke="sparkColor"
        :show-last="true"
        fluid
      />
    </div>

    <!-- 平台列表 -->
    <div
      v-if="!loaded"
      class="flex min-h-0 flex-1 items-center justify-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      加载中…
    </div>
    <div
      v-else-if="rows.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无评论留存数据<br />
      <span class="text-[11px]">接入监测后会自动统计</span>
    </div>
    <div v-else class="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto">
      <div
        v-for="r in rows"
        :key="r.key"
        class="flex items-center gap-2.5 rounded-[10px] px-2.5 py-2"
        :style="{
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
        }"
      >
        <span
          class="flex-shrink-0"
          :style="{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: r.color,
          }"
        />
        <span class="w-8 flex-shrink-0 text-[12px] font-semibold">{{
          r.label
        }}</span>
        <div
          class="relative flex-1"
          :style="{
            height: '5px',
            background: 'var(--line-2)',
            borderRadius: '999px',
          }"
        >
          <div
            :style="{
              width: `${ratio(r) * 100}%`,
              height: '100%',
              background: rowBarColor(r),
              borderRadius: '999px',
            }"
          />
        </div>
        <span
          class="font-mono flex-shrink-0 text-[11px] tabular-nums"
          :style="{
            color: 'var(--ink-2)',
            width: '46px',
            textAlign: 'right',
          }"
        >
          {{ r.retained }}/{{ r.total }}
        </span>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center rounded-full px-2 text-[10.5px] font-medium"
          :style="{
            background:
              ratio(r) < 0.8
                ? '#f3d3cd'
                : '#dde7d2',
            color: ratio(r) < 0.8 ? '#a3382a' : '#4d6b2f',
            minWidth: '40px',
            justifyContent: 'center',
          }"
        >
          {{ Math.round(ratio(r) * 100) }}%
        </span>
      </div>
    </div>
  </section>
</template>
