<script setup lang="ts">
/**
 * 曝光趋势 —— 近 7 天日历轴上的「单值柱状图」。
 *
 * 设计（按用户要求精简）：
 *   - 左侧 Y 轴（0/50/100 刻度 + 浅网格），柱顶直接标数值 —— 不再靠 hover。
 *   - 去掉图例（未/首/强曝光）、灰色「未曝光」背景段、右上角大数值。
 *   - 横轴恒为近 7 天（今天最右），有运行的天画柱，空天只留浅日期。
 *   - 底部切换：曝光 SoC / 首推率（柱高 = 选中指标当天值）。
 *   - 响应式 viewBox（ResizeObserver）铺满容器。
 *
 * 入参 history[] = {date:"M/D", soc, first}（按时间正序；仅含有运行的天）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import type { HistoryPoint } from "@/components/monitor/geo/geoDetail";
import { pct } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{ history: HistoryPoint[] }>();

const metric = ref<"soc" | "first">("soc");

// ── 响应式尺寸：viewBox = 容器真实像素，铺满 ──────────────────────────────
const wrap = ref<HTMLElement | null>(null);
const vw = ref(480);
const vh = ref(150);
let ro: ResizeObserver | null = null;
onMounted(() => {
  const el = wrap.value;
  if (!el || typeof ResizeObserver === "undefined") return;
  ro = new ResizeObserver((entries) => {
    const r = entries[0]?.contentRect;
    if (!r) return;
    if (r.width > 0) vw.value = r.width;
    if (r.height > 0) vh.value = r.height;
  });
  ro.observe(el);
});
onBeforeUnmount(() => {
  ro?.disconnect();
  ro = null;
});

const padL = 30; // 留给 Y 轴刻度
const padR = 12;
const padT = 18; // 留给柱顶数值
const padB = 20; // 留给日期轴
const innerL = 16; // 首日柱不压在 Y 轴上
const innerR = 8;
const plotW = computed(() => Math.max(20, vw.value - padL - padR));
const plotH = computed(() => Math.max(20, vh.value - padT - padB));

interface P {
  date: string;
  soc: number;
  first: number;
}
const pts = computed<P[]>(() =>
  props.history.map((h) => {
    const soc = Math.max(0, Math.min(1, h.soc));
    const first = Math.max(0, Math.min(soc, h.first));
    return { date: h.date, soc, first };
  }),
);

// ── 近 7 天日历轴（今天最右；有数据落柱，其余空天）─────────────────────────
interface Slot {
  label: string;
  point: P | null;
}
const slots = computed<Slot[]>(() => {
  const byLabel = new Map(pts.value.map((p) => [p.date, p]));
  const today = new Date();
  const matched = new Set<string>();
  const out: Slot[] = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
    const label = `${d.getMonth() + 1}/${d.getDate()}`;
    const point = byLabel.get(label) ?? null;
    if (point) matched.add(label);
    out.push({ label, point });
  }
  const extra = pts.value
    .filter((p) => !matched.has(p.date))
    .map((p) => ({ label: p.date, point: p }));
  return [...extra, ...out];
});
const nSlots = computed(() => slots.value.length);
const slotX = (i: number): number => {
  const x0 = padL + innerL;
  const w = Math.max(10, plotW.value - innerL - innerR);
  return nSlots.value > 1 ? x0 + (i * w) / (nSlots.value - 1) : x0 + w / 2;
};
const y = (v: number): number => padT + (1 - v) * plotH.value;

const realCols = computed(() =>
  slots.value
    .map((s, i) => ({ i, label: s.label, point: s.point }))
    .filter((c): c is { i: number; label: string; point: P } => c.point != null),
);
const nReal = computed(() => realCols.value.length);

const barColor = computed(() =>
  metric.value === "soc" ? "var(--primary-deep)" : "var(--green)",
);

// 单值柱：柱高 = 当天选中指标值，柱顶标数值。
const bars = computed(() =>
  realCols.value.map((c) => {
    const val = metric.value === "soc" ? c.point.soc : c.point.first;
    const cx = slotX(c.i);
    const slotW =
      nSlots.value > 1
        ? Math.max(10, plotW.value - innerL - innerR) / (nSlots.value - 1)
        : plotW.value;
    const w = Math.max(16, Math.min(36, slotW * 0.5));
    const topY = y(val);
    return {
      cx,
      x: cx - w / 2,
      w,
      topY,
      h: Math.max(1, y(0) - topY),
      label: pct(val),
    };
  }),
);

// Y 轴：刻度线 0/25/50/75/100，标签 0/50/100。
const yGrid = [0, 0.25, 0.5, 0.75, 1];
const yLabels = [
  { v: 1, t: "100" },
  { v: 0.5, t: "50" },
  { v: 0, t: "0" },
];
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 头：标题（右上角大数值已按要求去掉）-->
    <div class="flex flex-shrink-0 items-baseline gap-2" :style="{ marginBottom: '8px' }">
      <span class="font-display" :style="{ fontSize: '13px', fontWeight: 700 }">曝光趋势</span>
      <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)', whiteSpace: 'nowrap' }">近 7 天</span>
    </div>

    <!-- 图表（响应式铺满；min-height 防止自适应详情页里被压塌，但要足够小，
         让 默认 800px 窗口的矮卡片也放得下 header+chart+toggle 不溢出）-->
    <div ref="wrap" class="min-h-0 flex-1" :style="{ overflow: 'hidden', minHeight: '78px' }">
      <div v-if="!nReal" class="flex h-full items-center justify-center" :style="{ fontSize: '12px', color: 'var(--ink-3)' }">
        还没有运行历史 —— 跑几次采集后这里会成趋势。
      </div>
      <svg
        v-else
        width="100%"
        height="100%"
        preserveAspectRatio="xMidYMid meet"
        :viewBox="`0 0 ${vw} ${vh}`"
        :style="{ display: 'block' }"
      >
        <!-- Y 轴网格线 -->
        <line
          v-for="(t, gi) in yGrid"
          :key="'yg' + gi"
          :x1="padL"
          :x2="vw - padR"
          :y1="y(t)"
          :y2="y(t)"
          :stroke="t === 0 ? 'var(--line-2)' : 'var(--line)'"
          stroke-width="1"
        />
        <!-- Y 轴竖线 -->
        <line :x1="padL" :x2="padL" :y1="y(1)" :y2="y(0)" stroke="var(--line-2)" stroke-width="1" />
        <!-- Y 轴刻度标签 -->
        <text
          v-for="(yl, li) in yLabels"
          :key="'yl' + li"
          :x="padL - 6"
          :y="y(yl.v) + 3"
          text-anchor="end"
          :style="{ fontSize: '9px', fill: 'var(--ink-3)', fontVariantNumeric: 'tabular-nums' }"
        >{{ yl.t }}</text>

        <!-- 单值柱 + 柱顶数值 -->
        <template v-for="(b, bi) in bars" :key="'b' + bi">
          <rect :x="b.x" :y="b.topY" :width="b.w" :height="b.h" :fill="barColor" opacity="0.9" rx="3" />
          <text
            :x="b.cx"
            :y="b.topY - 5"
            text-anchor="middle"
            :style="{ fontSize: '10.5px', fontWeight: 700, fill: barColor, fontVariantNumeric: 'tabular-nums' }"
          >{{ b.label }}</text>
        </template>

        <!-- 日期轴（有数据的天加粗深色，空天浅色）-->
        <text
          v-for="(s, di) in slots"
          :key="'d' + di"
          :x="slotX(di)"
          :y="vh - 5"
          text-anchor="middle"
          :style="{
            fontSize: '9px',
            fill: s.point ? 'var(--ink)' : 'var(--ink-4)',
            fontWeight: s.point ? 700 : 400,
            fontVariantNumeric: 'tabular-nums',
          }"
        >{{ s.label }}</text>
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
          color: metric === m.k ? 'var(--card)' : 'var(--ink-2)',
        }"
        @click="metric = m.k as 'soc' | 'first'"
      >{{ m.t }}</button>
    </div>
  </div>
</template>
