<script setup lang="ts">
/**
 * 通用散点定位图 —— 移植 design version-b.jsx `BScatter`。
 * points 用归一化坐标 nx/ny(0–1)，右上角高亮「高价值象限」+ 阈值中线 + 坐标轴。
 * 几何/留白/配色严格照稿。本页用法 showLabels=false（点不写字，用下方图例）。
 *
 * point: { nx, ny, r?, fill, ring?, isYou?, label? }
 *   ring/isYou → 点外再描一圈半透明同色环 + 白描边（你=橙环 / 榜首=蓝环）。
 */
interface ScatterPoint {
  nx: number;
  ny: number;
  r?: number;
  fill: string;
  ring?: boolean;
  isYou?: boolean;
  label?: string;
}
const props = withDefaults(
  defineProps<{
    points: ScatterPoint[];
    xTitle: string;
    yTitle: string;
    zone: string;
    yTop?: string;
    yBot?: string;
    showLabels?: boolean;
  }>(),
  { showLabels: true },
);

// 画布与留白（照 jsx 原值）。
const W = 466;
const H = 188;
const padL = 22;
const padR = 14;
const padT = 18;
const padB = 26;
const pw = W - padL - padR;
const ph = H - padT - padB;

// 内缩 4%~96%，给边缘点和标签留白。
const X = (n: number) => padL + (0.04 + n * 0.92) * pw;
const Y = (n: number) => padT + (1 - (0.05 + n * 0.9)) * ph;

const zx = X(0.5);
const zyTop = Y(1);
const zyMid = Y(0.5);

interface Plotted {
  cx: number;
  cy: number;
  r: number;
  ring: boolean;
  fill: string;
  isYou: boolean;
  label?: string;
  anchor: "start" | "middle" | "end";
  lx: number;
  labelY: number;
}
function plot(points: ScatterPoint[]): Plotted[] {
  return points.map((p) => {
    const cx = X(p.nx);
    const cy = Y(p.ny);
    const r = p.r ?? 6.5;
    const ring = Boolean(p.ring || p.isYou);
    const labelY = Math.max(10, cy - r - 4);
    const anchor: "start" | "middle" | "end" =
      p.nx > 0.82 ? "end" : p.nx < 0.16 ? "start" : "middle";
    const lx = anchor === "end" ? cx + r : anchor === "start" ? cx - r : cx;
    return { cx, cy, r, ring, fill: p.fill, isYou: Boolean(p.isYou), label: p.label, anchor, lx, labelY };
  });
}
</script>

<template>
  <svg width="100%" :viewBox="`0 0 ${W} ${H}`" :style="{ display: 'block' }">
    <!-- 高价值象限（右上）+ 标签 -->
    <rect :x="zx" :y="zyTop" :width="X(1) - zx" :height="zyMid - zyTop" fill="rgba(238,106,42,.07)" />
    <text
      :x="X(0.98)"
      :y="Y(0.93)"
      text-anchor="end"
      :style="{ fontSize: '9px', fontWeight: 700, fill: 'var(--primary-deep)', opacity: 0.65 }"
    >{{ zone }}</text>
    <!-- 阈值中线 -->
    <line :x1="zx" :y1="padT" :x2="zx" :y2="padT + ph" stroke="var(--line-2)" stroke-width="1" stroke-dasharray="3 3" />
    <line :x1="padL" :y1="zyMid" :x2="padL + pw" :y2="zyMid" stroke="var(--line-2)" stroke-width="1" stroke-dasharray="3 3" />
    <!-- 坐标轴 -->
    <line :x1="padL" :y1="padT" :x2="padL" :y2="padT + ph" stroke="var(--line-2)" stroke-width="1.2" />
    <line :x1="padL" :y1="padT + ph" :x2="padL + pw" :y2="padT + ph" stroke="var(--line-2)" stroke-width="1.2" />
    <!-- y 轴极值标注 -->
    <text v-if="yTop" :x="padL - 4" :y="Y(1) + 3" text-anchor="end" :style="{ fontSize: '8.5px', fill: 'var(--ink-4)' }">{{ yTop }}</text>
    <text v-if="yBot" :x="padL - 4" :y="Y(0) + 3" text-anchor="end" :style="{ fontSize: '8.5px', fill: 'var(--ink-4)' }">{{ yBot }}</text>
    <!-- 数据点 -->
    <g v-for="(p, i) in plot(props.points)" :key="i">
      <circle
        v-if="p.ring"
        :cx="p.cx"
        :cy="p.cy"
        :r="p.r + 3.5"
        fill="none"
        :stroke="p.fill"
        :stroke-opacity="0.28"
        stroke-width="2"
      />
      <circle
        :cx="p.cx"
        :cy="p.cy"
        :r="p.r"
        :fill="p.fill"
        :fill-opacity="p.ring ? 1 : 0.8"
        :stroke="p.ring ? '#fff' : 'rgba(255,255,255,.6)'"
        :stroke-width="p.ring ? 2.4 : 1.2"
      />
      <text
        v-if="props.showLabels && p.label"
        :x="p.lx"
        :y="p.labelY"
        :text-anchor="p.anchor"
        class="font-display"
        :style="{ fontSize: '10px', fontWeight: p.isYou ? 700 : 600, fill: p.isYou ? 'var(--primary-deep)' : 'var(--ink-2)' }"
      >{{ p.label }}</text>
    </g>
    <!-- 轴标题 -->
    <text :x="padL + pw / 2" :y="H - 4" text-anchor="middle" :style="{ fontSize: '9.5px', fill: 'var(--ink-3)' }">{{ xTitle }} →</text>
    <text :x="padL - 2" :y="padT - 6" text-anchor="start" :style="{ fontSize: '9.5px', fill: 'var(--ink-3)' }">↑ {{ yTitle }}</text>
  </svg>
</template>
