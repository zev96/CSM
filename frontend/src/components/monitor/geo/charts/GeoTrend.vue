<script setup lang="ts">
/**
 * 曝光趋势 —— 三段堆叠面积（强曝光 / 首曝光 / 未曝光）+ 头部当前值 + 近 7 天
 * 首末环比 pp 徽章 + 底部 曝光SoC / 首推率 切换。
 *
 *   强曝光 = first_rank_rate（你被首推的占比，绿）
 *   首曝光 = soc − first_rank_rate（提及但非首推，橙）
 *   未曝光 = 1 − soc（没提及你，灰）
 *
 * 入参 history[] = {date, soc, first}（按时间正序；近 N 天每天一点）。
 */
import { computed, ref } from "vue";

import type { HistoryPoint } from "@/components/monitor/geo/geoDetail";
import { pct } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{ history: HistoryPoint[] }>();

const metric = ref<"soc" | "first">("soc");

const W = 482;
const H = 150;
const padL = 6;
const padR = 10;
const padT = 12;
const padB = 22;
const plotW = W - padL - padR;
const plotH = H - padT - padB;

interface P {
  date: string;
  soc: number;
  first: number;
}
const pts = computed<P[]>(() =>
  props.history.map((h) => {
    const soc = Math.max(0, Math.min(1, h.soc));
    const first = Math.max(0, Math.min(soc, h.first)); // 首推率 ≤ 曝光率，防止反带
    return { date: h.date, soc, first };
  }),
);
const n = computed(() => pts.value.length);
const x = (i: number) => padL + (n.value > 1 ? (i * plotW) / (n.value - 1) : plotW / 2);
const y = (v: number) => padT + (1 - v) * plotH;

const curV = computed(() => {
  const a = pts.value;
  if (!a.length) return 0;
  const p = a[a.length - 1];
  return metric.value === "soc" ? p.soc : p.first;
});
const firstV = computed(() => {
  const a = pts.value;
  if (!a.length) return 0;
  return metric.value === "soc" ? a[0].soc : a[0].first;
});
const delta = computed(() => curV.value - firstV.value);

/** 上边界 upper → 下边界 lower 之间的堆叠面积 polygon（左→右上边界 + 右→左下边界）。 */
function poly(upper: (p: P) => number, lower: (p: P) => number): string {
  const a = pts.value;
  if (!a.length) return "";
  const up = a.map((p, i) => `${x(i).toFixed(1)},${y(upper(p)).toFixed(1)}`);
  const lo = a.map((p, i) => `${x(i).toFixed(1)},${y(lower(p)).toFixed(1)}`).reverse();
  return [...up, ...lo].join(" ");
}
const strongArea = computed(() => poly((p) => p.first, () => 0)); // 强曝光 0→first
const firstArea = computed(() => poly((p) => p.soc, (p) => p.first)); // 首曝光 first→soc
const hiddenArea = computed(() => poly(() => 1, (p) => p.soc)); // 未曝光 soc→1
const socLine = computed(() =>
  pts.value.map((p, i) => `${x(i).toFixed(1)},${y(p.soc).toFixed(1)}`).join(" "),
);
const firstLine = computed(() =>
  pts.value.map((p, i) => `${x(i).toFixed(1)},${y(p.first).toFixed(1)}`).join(" "),
);
const activePts = computed(() =>
  pts.value.map((p) => (metric.value === "soc" ? p.soc : p.first)),
);

const legend = [
  { label: "未曝光", color: "var(--ink-3)" },
  { label: "首曝光", color: "var(--primary-deep)" },
  { label: "强曝光", color: "var(--green)" },
];
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 头：标题 + 当前值 + 涨跌 + 图例 -->
    <div class="flex flex-shrink-0 items-baseline justify-between gap-2" :style="{ marginBottom: '6px' }">
      <div class="flex items-baseline gap-2">
        <span class="font-display" :style="{ fontSize: '13px', fontWeight: 700 }">曝光趋势</span>
        <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)', whiteSpace: 'nowrap' }">近 7 天</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="font-display" :style="{ fontSize: '16px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ pct(curV) }}</span>
        <span
          v-if="n >= 2"
          class="inline-flex items-center"
          :style="{
            gap: '2px', whiteSpace: 'nowrap', fontSize: '11px', fontWeight: 700,
            padding: '2px 7px', borderRadius: '999px', fontVariantNumeric: 'tabular-nums',
            color: delta >= 0 ? 'var(--green)' : 'var(--red)',
            background: delta >= 0 ? 'rgba(122,155,94,.14)' : 'rgba(216,90,72,.14)',
          }"
        >{{ delta >= 0 ? "↑" : "↓" }} {{ Math.abs(Math.round(delta * 100)) }}pp</span>
      </div>
    </div>

    <!-- 图例 -->
    <div class="flex flex-shrink-0 items-center gap-3" :style="{ marginBottom: '4px' }">
      <span v-for="b in legend" :key="b.label" class="inline-flex items-center" :style="{ gap: '4px' }">
        <span :style="{ width: '8px', height: '8px', borderRadius: '2px', background: b.color, opacity: 0.85, display: 'inline-block' }" />
        <span :style="{ fontSize: '10px', color: 'var(--ink-3)' }">{{ b.label }}</span>
      </span>
    </div>

    <div class="min-h-0 flex-1" :style="{ overflow: 'hidden' }">
    <div v-if="!n" class="flex h-full items-center justify-center" :style="{ fontSize: '12px', color: 'var(--ink-3)' }">
      还没有运行历史 —— 跑几次采集后这里会成趋势。
    </div>
    <svg v-else width="100%" height="100%" preserveAspectRatio="xMidYMid meet" :viewBox="`0 0 ${W} ${H}`" :style="{ display: 'block' }">
      <!-- 三段堆叠面积（自下而上：强 / 首 / 未） -->
      <polygon :points="strongArea" fill="rgba(122,155,94,.22)" />
      <polygon :points="firstArea" fill="rgba(238,106,42,.20)" />
      <polygon :points="hiddenArea" fill="rgba(28,26,23,.05)" />
      <!-- 边界线（soc 实、first 虚） -->
      <polyline :points="socLine" fill="none" stroke="var(--primary-deep)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" :opacity="metric === 'soc' ? 1 : 0.45" />
      <polyline :points="firstLine" fill="none" stroke="var(--green)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" :opacity="metric === 'first' ? 1 : 0.45" />
      <!-- 当前指标数据点 -->
      <circle
        v-for="(v, i) in activePts"
        :key="i"
        :cx="x(i)"
        :cy="y(v)"
        :r="i === n - 1 ? 4.5 : 2.6"
        :fill="i === n - 1 ? (metric === 'soc' ? 'var(--primary-deep)' : 'var(--green)') : '#fff'"
        :stroke="metric === 'soc' ? 'var(--primary-deep)' : 'var(--green)'"
        :stroke-width="i === n - 1 ? 2 : 1.6"
      />
      <!-- 日期轴 -->
      <text
        v-for="(p, i) in pts"
        :key="'d' + i"
        :x="x(i)"
        :y="H - 6"
        text-anchor="middle"
        :style="{ fontSize: '8.5px', fill: i === n - 1 ? 'var(--ink)' : 'var(--ink-3)', fontWeight: i === n - 1 ? 700 : 400, fontVariantNumeric: 'tabular-nums' }"
      >{{ p.date }}</text>
    </svg>
    </div>

    <!-- 指标切换 -->
    <div class="flex flex-shrink-0 gap-1.5" :style="{ marginTop: '8px' }">
      <button
        v-for="m in [{ k: 'soc', t: '曝光 SoC' }, { k: 'first', t: '首推率' }]"
        :key="m.k"
        type="button"
        :style="{
          padding: '4px 11px', fontSize: '11px', fontWeight: 600, borderRadius: '999px',
          cursor: 'pointer', fontFamily: 'inherit',
          border: `1px solid ${metric === m.k ? 'transparent' : 'var(--line)'}`,
          background: metric === m.k ? 'var(--ink)' : 'var(--card)',
          color: metric === m.k ? '#fff' : 'var(--ink-2)',
        }"
        @click="metric = m.k as 'soc' | 'first'"
      >{{ m.t }}</button>
    </div>
  </div>
</template>
