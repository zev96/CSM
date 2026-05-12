<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    points: number[];
    width?: number;
    height?: number;
    stroke?: string;
    fill?: string;
    /** Show a dot on the latest point. */
    showLast?: boolean;
    /**
     * 可选 X 轴标签（一般是日期）。提供时，sparkline 会用 flex 在底下排
     * 一行小字，等距分布。建议 3–6 条，太密会挤。长度无需等于 points
     * —— 标签只是给视觉锚点，不要求一一对应。
     */
    axisLabels?: string[];
    /**
     * 撑满父容器宽度 —— 用于嵌在卡片列里且卡片宽度随窗口变。SVG 通过
     * viewBox 自动等比缩放，所以路径不会被挤扁；保留 width prop 用作
     * viewBox 的逻辑宽度。
     */
    fluid?: boolean;
  }>(),
  { width: 220, height: 60, stroke: "var(--primary)", showLast: true },
);

const path = computed(() => {
  const pts = props.points;
  if (pts.length === 0) return "";
  const max = Math.max(...pts);
  const min = Math.min(...pts);
  const range = max - min || 1;
  const stepX = props.width / Math.max(1, pts.length - 1);
  return pts
    .map((v, i) => {
      const x = i * stepX;
      const y = props.height - ((v - min) / range) * props.height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
});

const lastPoint = computed(() => {
  const pts = props.points;
  if (!pts.length) return null;
  const max = Math.max(...pts);
  const min = Math.min(...pts);
  const range = max - min || 1;
  const stepX = props.width / Math.max(1, pts.length - 1);
  const i = pts.length - 1;
  return {
    x: i * stepX,
    y: props.height - ((pts[i] - min) / range) * props.height,
  };
});
</script>

<template>
  <div :style="{ width: fluid ? '100%' : `${width}px`, maxWidth: '100%' }">
    <svg
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      class="block"
      :style="{ width: '100%', height: 'auto' }"
    >
      <path
        class="sparkline"
        :d="path"
        :stroke="stroke"
        stroke-width="1.8"
        fill="none"
      />
      <circle
        v-if="showLast && lastPoint"
        :cx="lastPoint.x"
        :cy="lastPoint.y"
        r="2.4"
        :fill="stroke"
      />
    </svg>
    <div
      v-if="axisLabels && axisLabels.length"
      class="mt-1 flex justify-between text-[10px]"
      :style="{ color: 'var(--ink-3)', fontVariantNumeric: 'tabular-nums' }"
    >
      <span v-for="(l, i) in axisLabels" :key="i">{{ l }}</span>
    </div>
  </div>
</template>
