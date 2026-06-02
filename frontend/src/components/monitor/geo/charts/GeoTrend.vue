<script setup lang="ts">
/**
 * 曝光趋势折线图 —— 移植 design version-b.jsx `BTrend`。
 * 背景按 未露出/弱/强 三色带，折线穿带爬升；头部当前值 + 涨跌 pp 徽章；
 * 底部可切 曝光 SoC / 首推率。几何/色带/配色严格照稿。
 *
 * 入参 history[] = {date, soc, first}（按时间正序；近 N 次运行）。
 */
import { computed, ref } from "vue";

import type { HistoryPoint } from "@/components/monitor/geo/geoDetail";
import { pct } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{ history: HistoryPoint[] }>();

const metric = ref<"soc" | "first">("soc");

// 画布与留白（照 jsx 原值）。
const W = 482;
const H = 150;
const padL = 6;
const padR = 10;
const padT = 12;
const padB = 22;
const plotW = W - padL - padR;
const plotH = H - padT - padB;

const series = computed(() =>
  props.history.map((h) => ({ date: h.date, v: metric.value === "soc" ? h.soc : h.first })),
);
const n = computed(() => series.value.length);
const cur = computed(() => (n.value ? series.value[n.value - 1].v : 0));
const prev = computed(() => (n.value >= 2 ? series.value[n.value - 2].v : cur.value));
const delta = computed(() => cur.value - prev.value);

const x = (i: number) => padL + (n.value > 1 ? (i * plotW) / (n.value - 1) : plotW / 2);
const y = (v: number) => padT + (1 - v) * plotH;

const bands = [
  { lo: 0, hi: 1 / 3, label: "未露出", fill: "rgba(216,90,72,.07)", text: "var(--red)" },
  { lo: 1 / 3, hi: 2 / 3, label: "弱曝光", fill: "rgba(238,106,42,.08)", text: "var(--primary-deep)" },
  { lo: 2 / 3, hi: 1, label: "强曝光", fill: "rgba(122,155,94,.10)", text: "var(--green)" },
];

const linePts = computed(() =>
  series.value.map((s, i) => `${x(i).toFixed(1)},${y(s.v).toFixed(1)}`).join(" "),
);
const areaPts = computed(
  () => `${padL},${padT + plotH} ${linePts.value} ${padL + plotW},${padT + plotH}`,
);
const lineColor = computed(() => (metric.value === "soc" ? "var(--primary)" : "var(--ink-2)"));
const areaFill = computed(() =>
  metric.value === "soc" ? "rgba(238,106,42,.10)" : "rgba(28,26,23,.05)",
);
</script>

<template>
  <div>
    <!-- 头：标题 + 当前值 + 涨跌 -->
    <div class="flex items-baseline justify-between gap-2" :style="{ marginBottom: '8px' }">
      <div class="flex items-baseline gap-2">
        <span class="font-display" :style="{ fontSize: '13px', fontWeight: 700 }">曝光趋势</span>
        <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)', whiteSpace: 'nowrap' }">
          近 {{ n }} 次运行
        </span>
      </div>
      <div class="flex items-center gap-2">
        <span
          class="font-display"
          :style="{ fontSize: '16px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }"
        >{{ pct(cur) }}</span>
        <span
          class="inline-flex items-center"
          :style="{
            gap: '2px',
            whiteSpace: 'nowrap',
            fontSize: '11px',
            fontWeight: 700,
            padding: '2px 7px',
            borderRadius: '999px',
            fontVariantNumeric: 'tabular-nums',
            color: delta >= 0 ? 'var(--green)' : 'var(--red)',
            background: delta >= 0 ? 'rgba(122,155,94,.14)' : 'rgba(216,90,72,.14)',
          }"
        >
          {{ delta >= 0 ? "↑" : "↓" }} {{ Math.abs(Math.round(delta * 100)) }}pp
        </span>
      </div>
    </div>

    <svg width="100%" :viewBox="`0 0 ${W} ${H}`" :style="{ display: 'block' }">
      <!-- 色带 -->
      <g v-for="b in bands" :key="b.label">
        <rect :x="padL" :y="y(b.hi)" :width="plotW" :height="(b.hi - b.lo) * plotH" :fill="b.fill" />
        <text
          :x="padL + plotW - 3"
          :y="y(b.hi) + 11"
          text-anchor="end"
          :style="{ fontSize: '8.5px', fontWeight: 600, fill: b.text, opacity: 0.75 }"
        >{{ b.label }}</text>
      </g>
      <!-- 分带线 -->
      <line
        v-for="g in [1 / 3, 2 / 3]"
        :key="g"
        :x1="padL"
        :y1="y(g)"
        :x2="padL + plotW"
        :y2="y(g)"
        stroke="var(--line-2)"
        stroke-width="1"
        stroke-dasharray="3 3"
      />
      <!-- 面积 + 折线 -->
      <polygon :points="areaPts" :fill="areaFill" />
      <polyline :points="linePts" fill="none" :stroke="lineColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" />
      <!-- 数据点 -->
      <circle
        v-for="(s, i) in series"
        :key="i"
        :cx="x(i)"
        :cy="y(s.v)"
        :r="i === n - 1 ? 4.5 : 2.8"
        :fill="i === n - 1 ? lineColor : '#fff'"
        :stroke="lineColor"
        :stroke-width="i === n - 1 ? 2 : 1.8"
      />
      <!-- 日期轴 -->
      <text
        v-for="(s, i) in series"
        :key="'d' + i"
        :x="x(i)"
        :y="H - 6"
        text-anchor="middle"
        :style="{ fontSize: '8.5px', fill: i === n - 1 ? 'var(--ink)' : 'var(--ink-3)', fontWeight: i === n - 1 ? 700 : 400, fontVariantNumeric: 'tabular-nums' }"
      >{{ s.date }}</text>
    </svg>

    <!-- 指标切换 -->
    <div class="flex gap-1.5" :style="{ marginTop: '8px' }">
      <button
        v-for="m in [{ k: 'soc', t: '曝光 SoC' }, { k: 'first', t: '首推率' }]"
        :key="m.k"
        type="button"
        :style="{
          padding: '4px 11px',
          fontSize: '11px',
          fontWeight: 600,
          borderRadius: '999px',
          cursor: 'pointer',
          fontFamily: 'inherit',
          border: `1px solid ${metric === m.k ? 'transparent' : 'var(--line)'}`,
          background: metric === m.k ? 'var(--ink)' : 'var(--card)',
          color: metric === m.k ? '#fff' : 'var(--ink-2)',
        }"
        @click="metric = m.k as 'soc' | 'first'"
      >{{ m.t }}</button>
    </div>
  </div>
</template>
