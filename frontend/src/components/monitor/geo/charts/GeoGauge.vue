<script setup lang="ts">
/**
 * 曝光评级半圆刻度仪表盘 —— 移植 design version-b.jsx `BGauge`。
 * 0–100 半圆刻度，按 未露出(红)/弱(橙)/强(绿) 三段着色，点亮到当前分值；
 * 中心大数字 score /100 + 档位文字。几何/配色严格照稿。
 *
 * 入参：value(0–1 点亮比例) / score(0–100 显示数) / label(档位文字) / color(档位色)。
 */
const props = defineProps<{
  value: number;
  score: number;
  label: string;
  color: string;
}>();

// 画布与几何（照 jsx 原值）。
const W = 212;
const H = 132;
const cx = 106;
const cy = 112;
const ro = 94; // 外半径
const ri = 76; // 内半径
const N = 46; // 刻度数

const rad = (a: number) => (a * Math.PI) / 180;
const ang = (t: number) => 180 - t * 180; // t=0 左, t=1 右, 过顶部
const at = (r: number, t: number): [number, number] => [
  cx + r * Math.cos(rad(ang(t))),
  cy - r * Math.sin(rad(ang(t))),
];
const zoneColor = (t: number) =>
  t < 1 / 3 ? "var(--red)" : t < 2 / 3 ? "var(--primary)" : "var(--green)";

interface Tick {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  c: string;
  op: number;
}
function buildTicks(value: number): Tick[] {
  const ticks: Tick[] = [];
  for (let i = 0; i < N; i++) {
    const t = i / (N - 1);
    const on = t <= value + 1e-9;
    const [x1, y1] = at(ri, t);
    const [x2, y2] = at(ro, t);
    ticks.push({ x1, y1, x2, y2, c: zoneColor(t), op: on ? 1 : 0.16 });
  }
  return ticks;
}
</script>

<template>
  <svg
    width="100%"
    :viewBox="`0 0 ${W} ${H}`"
    :style="{ display: 'block', maxWidth: '236px' }"
  >
    <line
      v-for="(tk, i) in buildTicks(props.value)"
      :key="i"
      :x1="tk.x1"
      :y1="tk.y1"
      :x2="tk.x2"
      :y2="tk.y2"
      :stroke="tk.c"
      :stroke-opacity="tk.op"
      stroke-width="3.2"
      stroke-linecap="round"
    />
    <text
      :x="cx"
      :y="cy - 28"
      text-anchor="middle"
      class="font-display"
      :style="{ fontVariantNumeric: 'tabular-nums' }"
    >
      <tspan :style="{ fontSize: '40px', fontWeight: 700, fill: 'var(--ink)' }">{{ props.score }}</tspan>
      <tspan dx="3" :style="{ fontSize: '13px', fontWeight: 600, fill: 'var(--ink-3)' }">/100</tspan>
    </text>
    <text
      :x="cx"
      :y="cy - 8"
      text-anchor="middle"
      class="font-display"
      :style="{ fontSize: '14px', fontWeight: 700, fill: props.color }"
    >{{ props.label }}</text>
    <text
      :x="cx - ro + 2"
      :y="cy + 14"
      text-anchor="middle"
      :style="{ fontSize: '9px', fill: 'var(--ink-4)' }"
    >0</text>
    <text
      :x="cx + ro - 2"
      :y="cy + 14"
      text-anchor="middle"
      :style="{ fontSize: '9px', fill: 'var(--ink-4)' }"
    >100</text>
  </svg>
</template>
