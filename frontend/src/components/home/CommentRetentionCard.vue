<script setup lang="ts">
/**
 * 评论留存率 — Row 2 第 3 张监测卡。
 *
 *   ┌─────────────────────────────────────────┐
 *   │ 评论留存                          [→]   │
 *   │ 57%  留存率                              │
 *   │ 近 7 天                                  │
 *   │  ╱╲   ╲╱  (sparkline 高 60)              │
 *   │                                          │
 *   │ ● B 站   8/14   [↓ 43%]                 │  ← hover 切换顶部 pct
 *   │ ● 抖音  12/12   [—]                     │     + sparkline 颜色
 *   │ ● 快手   5/5   [—]                      │     行橙底白字 + 阴影
 *   └─────────────────────────────────────────┘
 *
 * 交互：
 *   - 默认顶部显示聚合 pct（所有平台合并），副词 "留存率"
 *   - hover 某行 → 顶部 pct 切到 ratio(r)*100，副词切到平台名
 *   - sparkColor 跟 displayPct 走（绿/琥珀/红 三档健康度）
 *   - 点击行 → router.push 监测中心评论 tab + 平台 subtab
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

function ratio(r: Row) {
  return r.total > 0 ? r.retained / r.total : 0;
}

// 按留存率升序展示（worst first），让最差的平台稳定排在列表最上。
const sortedRows = computed(() =>
  [...rows.value].sort((a, b) => ratio(a) - ratio(b)),
);

// hover 状态 —— 切顶部 pct + sparkline 颜色
const hoveredIdx = ref<number | null>(null);
const selectedRow = computed<Row | null>(() =>
  hoveredIdx.value === null ? null : sortedRows.value[hoveredIdx.value] ?? null,
);
const displayPct = computed(() =>
  selectedRow.value ? Math.round(ratio(selectedRow.value) * 100) : pct.value,
);

const SPARK_FALLBACK = [72, 70, 68, 65, 62, 58, 57];
// 横轴标签：7 天日（"22"），不带月份；今天在最末。跟首页其它监测卡一致。
const SPARK_LABELS = ((): string[] => {
  const out: string[] = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
    out.push(String(d.getDate()));
  }
  return out;
})();

// sparkline 按健康度走"绿 / 琥珀 / 红"三档；中档不再用主色（主色按
// 约定保留在按钮 + hover），改用 amber 跟绿/红保持温度梯度。
const sparkColor = computed(() => {
  const p = displayPct.value;
  if (p >= 80) return "var(--green)";
  if (p >= 50) return "#e8a04a";
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

function rowChipText(r: Row) {
  const p = Math.round(ratio(r) * 100);
  if (p === 100) return "—";
  return `${100 - p}%`;
}
function rowChipKind(r: Row): "down" | "flat" {
  return ratio(r) < 1 ? "down" : "flat";
}
function rowChipStyle(r: Row) {
  if (rowChipKind(r) === "down")
    return { background: "#f3d3cd", color: "#a3382a" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}

// 点击平台行 → 跳监测中心评论 tab + 该平台 subtab
function onRowClick(r: Row) {
  const platform =
    r.key === "bilibili_comment"
      ? "bilibili"
      : r.key === "douyin_comment"
        ? "douyin"
        : "kuaishou";
  router.push({
    name: "monitor",
    query: { tab: "comment", platform },
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
        评论留存
      </div>
      <button
        type="button"
        class="trend-detail inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full"
        title="详情"
        @click="router.push({ name: 'monitor', query: { tab: 'comment' } })"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <!--
      大标：聚合留存率（hover 平台行时切到该平台 ratio + 平台名）。
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
        {{ rows.length > 0 ? displayPct + "%" : "—" }}
      </div>
      <div class="text-[11.5px]" :style="{ color: 'var(--ink-2)' }">
        {{ selectedRow ? selectedRow.label : "留存率" }}
      </div>
    </div>
    <div class="mt-0.5 mb-3 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
      近 7 天
    </div>

    <!-- Sparkline (height 60，跟 KeywordTrendCard 对齐) -->
    <!--
      Y 轴锁 0-100：留存率本质是百分比，没有 yMin/yMax 时 Sparkline
      自适应数据 min-max（57-72%），让一个轻微的 15pt 下滑显示成
      "从顶冲到底"的暴跌曲线，跟实际语义不符。锁 0-100 后曲线相对
      "满分" 显示，57% 就是真的位于中下部，符合用户直觉。
    -->
    <div class="mb-3 flex-shrink-0">
      <Sparkline
        :points="SPARK_FALLBACK"
        :axis-labels="SPARK_LABELS"
        :height="60"
        :stroke="sparkColor"
        :show-last="true"
        :y-min="0"
        :y-max="100"
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
    <div v-else class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <div
        v-for="(r, idx) in sortedRows"
        :key="r.key"
        class="row flex items-center gap-2 rounded-[10px] px-2.5 py-2"
        :class="{ 'row-active': idx === hoveredIdx }"
        @mouseenter="hoveredIdx = idx"
        @mouseleave="hoveredIdx = null"
        @click="onRowClick(r)"
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
        <span class="min-w-0 flex-1 truncate text-[12px]">{{ r.label }}</span>
        <span
          class="font-mono flex-shrink-0 text-[11px] tabular-nums"
          :style="{
            color: idx === hoveredIdx ? '#ffffff' : 'var(--ink-2)',
          }"
        >
          {{ r.retained }}/{{ r.total }}
        </span>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="
            idx === hoveredIdx
              ? {
                  background: '#ffffff',
                  color: rowChipKind(r) === 'down' ? '#a3382a' : 'var(--ink-2)',
                }
              : rowChipStyle(r)
          "
        >
          <Icon v-if="rowChipKind(r) === 'down'" name="arrowDown" :size="9" />
          {{ rowChipText(r) }}
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
