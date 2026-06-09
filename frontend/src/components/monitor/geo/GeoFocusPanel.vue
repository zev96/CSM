<script setup lang="ts">
/**
 * GEO「重点」视图（对齐图二）。
 * 左：待优化关键词（关键词 + 缺失平台，盲区优先排序）；
 * 右：各平台覆盖率·近 5 周横向对比（每平台一条折线）。
 */
import { computed } from "vue";

import {
  platformShort,
  type GeoImproveRow,
  type PlatformWeeklySeries,
} from "@/components/monitor/geo/geoDetail";
import LineChart from "@/components/monitor/history/LineChart.vue";

const props = defineProps<{
  toImprove: GeoImproveRow[];
  platformWeekly: PlatformWeeklySeries;
}>();

// 逐平台折线配色（与信源榜区分，平台专属冷暖交替）。
const PLAT_COLORS = ["#ee6a2a", "#3a7ca5", "#7a9b5e", "#c2962f", "#9b6a9e", "#d85a48"];
const color = (i: number) => PLAT_COLORS[i % PLAT_COLORS.length];

const chartSeries = computed(() =>
  props.platformWeekly.series.map((s, i) => ({
    label: platformShort(s.platformId),
    color: color(i),
    data: s.rates,
  })),
);
const hasWeekly = computed(() =>
  props.platformWeekly.series.some((s) => s.rates.some((r) => r !== null)),
);

function bandDot(band: GeoImproveRow["band"]): string {
  return band === "blind" ? "var(--red)" : "var(--primary)";
}
function bandLabel(band: GeoImproveRow["band"]): string {
  return band === "blind" ? "盲区" : "部分";
}
</script>

<template>
  <div class="grid min-h-0 flex-1" :style="{ gridTemplateColumns: '0.85fr 1.15fr', gap: '20px' }">
    <!-- 待优化关键词 -->
    <div class="flex min-h-0 min-w-0 flex-col">
      <div class="flex flex-shrink-0 items-center" :style="{ gap: '8px', marginBottom: '8px' }">
        <span :style="{ fontSize: '11.5px', fontWeight: 600, color: 'var(--ink)' }">待优化关键词</span>
        <span
          class="inline-flex items-center justify-center"
          :style="{ minWidth: '18px', height: '18px', padding: '0 5px', borderRadius: '999px', background: 'var(--primary-soft)', color: 'var(--primary-deep)', fontSize: '11px', fontWeight: 700 }"
        >{{ toImprove.length }}</span>
        <span class="ml-auto" :style="{ fontSize: '10px', color: 'var(--ink-3)' }">按缺口排序</span>
      </div>
      <div v-if="!toImprove.length" class="flex flex-1 items-center justify-center text-center" :style="{ fontSize: '12px', color: 'var(--ink-3)' }">
        全部关键词覆盖良好 🎉
      </div>
      <div v-else class="min-h-0 flex-1 overflow-y-auto" :style="{ paddingRight: '2px' }">
        <div
          v-for="row in toImprove"
          :key="row.keyword"
          :style="{ padding: '10px 12px', borderRadius: '10px', background: 'var(--card)', border: '1px solid var(--line)', marginBottom: '7px' }"
        >
          <div class="flex items-center" :style="{ gap: '7px' }">
            <span :style="{ width: '7px', height: '7px', borderRadius: '999px', background: bandDot(row.band), flexShrink: 0 }" />
            <span class="truncate" :style="{ fontSize: '12.5px', fontWeight: 600, color: 'var(--ink)' }" :title="row.keyword">{{ row.keyword }}</span>
            <span class="ml-auto flex-shrink-0" :style="{ fontSize: '9.5px', color: bandDot(row.band), fontWeight: 600 }">{{ bandLabel(row.band) }}</span>
          </div>
          <div :style="{ fontSize: '11px', color: 'var(--ink-3)', marginTop: '5px' }">
            缺失 <span :style="{ color: 'var(--ink-2)' }">{{ row.missing.map(platformShort).join(" / ") || "—" }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 各平台覆盖率·近 5 周 -->
    <div class="flex min-h-0 min-w-0 flex-col">
      <div class="flex flex-shrink-0 items-baseline" :style="{ gap: '8px', marginBottom: '8px' }">
        <span :style="{ fontSize: '11.5px', fontWeight: 600, color: 'var(--ink)' }">各平台覆盖率</span>
        <span :style="{ fontSize: '10px', color: 'var(--ink-3)' }">近 5 周 · 横向对比</span>
      </div>
      <div class="min-h-0 flex-1" :style="{ overflow: 'hidden' }">
        <div v-if="!hasWeekly" class="flex h-full items-center justify-center text-center" :style="{ fontSize: '11.5px', color: 'var(--ink-3)' }">
          历史不足 —— 跑几周后这里会成横向对比线。
        </div>
        <LineChart
          v-else
          height="100%"
          :labels="platformWeekly.weekLabels"
          :series="chartSeries"
          :y-max="100"
          :point-radius="3"
          :padding="12"
          :y-axis-formatter="(v) => `${v}%`"
        />
      </div>
      <!-- 平台图例（居中）-->
      <div class="flex flex-shrink-0 flex-wrap justify-center" :style="{ gap: '10px', marginTop: '8px' }">
        <span v-for="(s, i) in platformWeekly.series" :key="s.platformId" class="inline-flex items-center" :style="{ gap: '5px' }">
          <span :style="{ width: '10px', height: '3px', borderRadius: '999px', background: color(i), display: 'inline-block' }" />
          <span :style="{ fontSize: '10.5px', color: 'var(--ink-2)' }">{{ platformShort(s.platformId) }}</span>
        </span>
      </div>
    </div>
  </div>
</template>
