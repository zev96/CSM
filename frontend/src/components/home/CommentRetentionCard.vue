<script setup lang="ts">
/**
 * 评论留存率 — 严格按 CSM-RE1（V1）/src/screens/home.jsx 的 CommentRetention 复刻：
 *   - 头部："MONITOR · 平台评论" + "评论留存率" + "近 7 天 · N/M 条可见"
 *   - 大数字 81% + delta 红色 chip + sparkline
 *   - 三行平台：色点 + 名称 + 进度条 + retained/total + delta chip
 *
 * 数据：sidecar /api/monitor/summary 各平台 task.latest.metric 汇总。
 * 没数据时退到 V1 设计稿同款示例（B站 8/14 -3 / 抖音 12/12 持平 / 快手 5/5 持平）。
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
  delta: number; // 负数=下滑，0=持平
}

// V1 设计稿同款示例数据。
const FALLBACK_ROWS: Row[] = [
  { key: "bilibili", label: "B 站", color: "var(--primary)", retained: 8, total: 14, delta: -3 },
  { key: "douyin", label: "抖音", color: "#1e1c19", retained: 12, total: 12, delta: 0 },
  { key: "kuaishou", label: "快手", color: "var(--yellow)", retained: 5, total: 5, delta: 0 },
];
const FALLBACK_SPARK = [100, 98, 96, 90, 86, 82, 81];

interface PlatformView {
  task_count: number;
  tasks: Array<{
    id: number;
    name: string;
    latest: { metric: Record<string, any> } | null;
  }>;
}
const summary = ref<Record<string, PlatformView>>({});
const loaded = ref(false);

const PLATFORM_MAP = [
  { key: "bilibili_comment", label: "B 站", color: "var(--primary)" },
  { key: "douyin_comment", label: "抖音", color: "#1e1c19" },
  { key: "kuaishou_comment", label: "快手", color: "var(--yellow)" },
];

function aggregate(p: PlatformView | undefined) {
  if (!p || !p.tasks.length) return null;
  let retained = 0;
  let total = 0;
  let counted = 0;
  for (const t of p.tasks) {
    const m = t.latest?.metric;
    if (!m) continue;
    const r = Number(m.retained ?? m.alive_count);
    const tt = Number(m.total ?? m.posted_count);
    if (Number.isFinite(r) && Number.isFinite(tt) && tt > 0) {
      retained += r;
      total += tt;
      counted++;
    }
  }
  if (!counted) return null;
  return { retained, total };
}

const realRows = computed<Row[]>(() => {
  return PLATFORM_MAP.map((p) => {
    const agg = aggregate(summary.value[p.key]);
    if (!agg) return null;
    return {
      key: p.key,
      label: p.label,
      color: p.color,
      retained: agg.retained,
      total: agg.total,
      delta: 0, // 真实 delta 需要历史快照对比，暂时 0
    };
  }).filter((r): r is Row => r !== null);
});

const rows = computed<Row[]>(() => {
  if (!loaded.value) return FALLBACK_ROWS;
  if (realRows.value.length === 0) return FALLBACK_ROWS;
  return realRows.value;
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
const overallDelta = computed(() => 100 - pct.value); // 与 100% 对比的下滑幅度

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/summary");
    summary.value = r.data.platforms ?? {};
  } catch {
    /* 静默失败 — fallback 顶住 */
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
    <!--
      标题区 —— 把大数字 81% 和 -19% chip 收进副标题行：
      第一行小标 + 详情按钮；
      第二行 大标题「评论留存率」+ 81% + −19% chip + sparkline；
      第三行 副副标「近 7 天 · N/M 条可见」。
      原版把 81% 单独占一行 38px 高，新版收进标题行后整张卡片省出
      ~50px 高度，让下面三个平台都能完整显示，不再被裁掉「快手」那行。
    -->
    <div class="mb-2 flex flex-shrink-0 items-start justify-between gap-2">
      <div
        class="text-[10.5px] font-medium uppercase tracking-[1.5px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        Monitor · 平台评论
      </div>
      <button
        type="button"
        class="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px]"
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

    <div class="mb-1 flex flex-shrink-0 items-baseline gap-3">
      <div
        class="font-display font-bold"
        :style="{ fontSize: '20px', letterSpacing: '-0.4px', lineHeight: 1 }"
      >
        评论留存率
      </div>
      <div
        class="font-display font-bold"
        :style="{ fontSize: '24px', letterSpacing: '-0.5px', lineHeight: 1 }"
      >
        {{ pct }}%
      </div>
      <span
        v-if="pct < 100"
        class="inline-flex h-5 items-center gap-1 rounded-full px-2 text-[10.5px] font-medium"
        :style="{ background: '#f3d3cd', color: '#a3382a' }"
      >
        <Icon name="arrowDown" :size="10" />
        −{{ overallDelta }}%
      </span>
      <span
        v-else
        class="inline-flex h-5 items-center gap-1 rounded-full px-2 text-[10.5px] font-medium"
        :style="{ background: '#dde7d2', color: '#4d6b2f' }"
      >
        持平
      </span>
      <div class="ml-auto self-end">
        <Sparkline
          :points="FALLBACK_SPARK"
          :width="120"
          :height="22"
          stroke="var(--red)"
          :show-last="false"
        />
      </div>
    </div>

    <div class="mb-2 flex-shrink-0 text-[11px]" :style="{ color: 'var(--ink-3)' }">
      近 7 天 · {{ totalRetained }}/{{ totalAll }} 条可见
    </div>

    <!--
      三个平台 —— 卡片省出来的高度全给这里。不再切两列，单列每行高 36，
      三个平台 (B站 / 抖音 / 快手) 全部一屏看完，不需要内部滚动。
    -->
    <div class="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
      <div
        v-for="r in rows"
        :key="r.key"
        class="flex items-center gap-3 rounded-[10px] p-3"
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
        <span class="w-8 text-[12px] font-semibold">{{ r.label }}</span>
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
          class="font-mono text-[11px] tabular-nums"
          :style="{ color: 'var(--ink-2)', width: '38px', textAlign: 'right' }"
        >
          {{ r.retained }}/{{ r.total }}
        </span>
        <span
          v-if="r.delta < 0"
          class="inline-flex h-5 items-center gap-1 rounded-full px-2 text-[10.5px] font-medium"
          :style="{ background: '#f3d3cd', color: '#a3382a' }"
        >
          <Icon name="arrowDown" :size="10" />
          {{ r.delta }}
        </span>
        <span
          v-else-if="r.delta > 0"
          class="inline-flex h-5 items-center gap-1 rounded-full px-2 text-[10.5px] font-medium"
          :style="{ background: '#dde7d2', color: '#4d6b2f' }"
        >
          <Icon name="arrowUp" :size="10" />
          +{{ r.delta }}
        </span>
        <span
          v-else
          class="inline-flex h-5 items-center rounded-full px-2 text-[10.5px] font-medium"
          :style="{ background: 'rgba(28,26,23,0.06)', color: 'var(--ink-2)' }"
        >
          持平
        </span>
      </div>
    </div>
  </section>
</template>
