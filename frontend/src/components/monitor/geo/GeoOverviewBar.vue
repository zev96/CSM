<script setup lang="ts">
/**
 * GEO 概览条 —— 替换原 KPI 四格（对齐图二/三顶部）。
 * 左：监测关键词数 + 覆盖分布（已霸屏/部分覆盖/盲区）stacked bar；
 * 右：平均曝光率（近 7 天环比）+ 平均情感（近 7 天环比）。
 */
import { computed } from "vue";

import type { CoverageDist } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  kwCount: number;
  coverage: CoverageDist;
  socPct: number; // 0–100
  socDelta: number; // 分数（soc 近 7 天首末差）
  sentiment: number;
  sentimentDelta: number;
}>();

const segs = computed(() => {
  const { dominated, partial, blind } = props.coverage;
  const total = Math.max(1, dominated + partial + blind);
  return [
    { key: "dominated", label: "已霸屏", n: dominated, color: "var(--green)", w: (dominated / total) * 100 },
    { key: "partial", label: "部分覆盖", n: partial, color: "var(--primary)", w: (partial / total) * 100 },
    { key: "blind", label: "盲区", n: blind, color: "var(--red)", w: (blind / total) * 100 },
  ];
});

const sentimentText = computed(() =>
  props.sentiment > 0.05 ? "积极" : props.sentiment < -0.05 ? "消极" : "中性",
);

function deltaTone(v: number) {
  return v > 0 ? "up" : v < 0 ? "down" : "flat";
}
const deltaStyle = (v: number) => ({
  color: v > 0 ? "#5e7848" : v < 0 ? "var(--red)" : "var(--ink-3)",
  background: v > 0 ? "rgba(122,155,94,.15)" : v < 0 ? "rgba(216,90,72,.12)" : "rgba(28,26,23,.05)",
});
const socDeltaText = computed(() => {
  const pp = Math.round(props.socDelta * 100);
  return `${pp > 0 ? "↑" : pp < 0 ? "↓" : ""}${Math.abs(pp)}%`;
});
const sentDeltaText = computed(() => {
  const d = props.sentimentDelta;
  const a = Math.abs(d).toFixed(2);
  return `${d > 0 ? "↑" : d < 0 ? "↓" : ""}${a}`;
});
</script>

<template>
  <div
    class="flex flex-shrink-0 items-center"
    :style="{
      gap: '20px',
      background: 'var(--card-2)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-inner, 10px)',
      padding: '14px 18px',
    }"
  >
    <!-- 关键词数 + 覆盖分布 -->
    <div class="min-w-0 flex-1">
      <div class="flex items-center" :style="{ gap: '6px', marginBottom: '9px' }">
        <span :style="{ fontSize: '11px', color: 'var(--ink-3)' }">监测关键词</span>
        <span class="font-display" :style="{ fontSize: '19px', fontWeight: 700, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }">{{ kwCount }}</span>
        <span :style="{ fontSize: '11px', color: 'var(--ink-3)' }">个 · 覆盖分布</span>
        <!-- 图例 -->
        <div class="ml-auto flex items-center" :style="{ gap: '12px' }">
          <span v-for="s in segs" :key="s.key" class="inline-flex items-center" :style="{ gap: '5px' }">
            <span :style="{ width: '8px', height: '8px', borderRadius: '999px', background: s.color, display: 'inline-block' }" />
            <span :style="{ fontSize: '11px', color: 'var(--ink-2)' }">{{ s.label }}</span>
            <b class="font-display" :style="{ fontSize: '12px', fontVariantNumeric: 'tabular-nums' }">{{ s.n }}</b>
          </span>
        </div>
      </div>
      <!-- stacked bar -->
      <div class="flex" :style="{ height: '10px', borderRadius: '999px', overflow: 'hidden', background: 'rgba(28,26,23,.06)' }">
        <div
          v-for="s in segs"
          :key="s.key"
          :style="{ width: s.w + '%', height: '100%', background: s.color, transition: 'width .3s ease' }"
        />
      </div>
    </div>

    <div :style="{ width: '1px', height: '40px', background: 'var(--line)', flexShrink: 0 }" />

    <!-- 平均曝光率 -->
    <div :style="{ flexShrink: 0, minWidth: '120px' }">
      <div :style="{ fontSize: '10px', color: 'var(--ink-3)', marginBottom: '4px', letterSpacing: '0.4px' }">平均曝光率</div>
      <div class="flex items-baseline" :style="{ gap: '7px' }">
        <span class="font-display" :style="{ fontSize: '22px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ socPct }}%</span>
        <span
          class="inline-flex items-center"
          :style="{ fontSize: '10.5px', fontWeight: 600, padding: '2px 7px', borderRadius: '999px', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums', ...deltaStyle(socDelta) }"
          :title="`近 7 天${deltaTone(socDelta) === 'up' ? '上升' : deltaTone(socDelta) === 'down' ? '下降' : '持平'}`"
        >{{ socDeltaText }}</span>
      </div>
    </div>

    <div :style="{ width: '1px', height: '40px', background: 'var(--line)', flexShrink: 0 }" />

    <!-- 平均情感 -->
    <div :style="{ flexShrink: 0, minWidth: '120px' }">
      <div :style="{ fontSize: '10px', color: 'var(--ink-3)', marginBottom: '4px', letterSpacing: '0.4px' }">平均情感</div>
      <div class="flex items-baseline" :style="{ gap: '7px' }">
        <span class="font-display" :style="{ fontSize: '22px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ sentiment.toFixed(2) }}</span>
        <span :style="{ fontSize: '11px', color: 'var(--ink-3)' }">{{ sentimentText }}</span>
        <span
          class="inline-flex items-center"
          :style="{ fontSize: '10.5px', fontWeight: 600, padding: '2px 7px', borderRadius: '999px', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums', ...deltaStyle(sentimentDelta) }"
        >{{ sentDeltaText }}</span>
      </div>
    </div>
  </div>
</template>
