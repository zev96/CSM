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
    /**
     * 强制 Y 轴范围。传 yMax 让曲线相对"容量上限"显示（例如知乎卡位
     * 数 / Top-N），而不是数据本身的 min-max 自适应——后者会把 0-2 的
     * 微小波动放大到全图，视觉上比实际趋势夸张。
     * 同时传 yMin 默认 0（卡位 / 排名都是非负值）。
     */
    yMax?: number;
    yMin?: number;
  }>(),
  { width: 220, height: 60, stroke: "var(--primary)", showLast: true, yMin: 0 },
);

/*
 * 平滑曲线：Catmull-Rom → Cubic Bezier，tension 0.25 跟数据中心
 * LineChart 的 chart.js tension 一致，让首页监测卡的折线在数据拐点
 * 圆滑过渡，视觉跟数据中心曲线对齐（用户反馈：希望首页趋势图跟
 * 数据中心的"动效流畅一点"）。
 *
 * 实现：对每对相邻点 p1→p2，用 p0/p3（外侧邻居）算两个 cubic 控制点，
 * 让曲线在 p1 出/入 p2 时方向连续。两端点用自身作为缺失邻居，曲线在
 * 端点处自然收敛而不外推。
 */

// 上下内边距 —— 留出 4px 给笔画 + 末点圆点的半径，避免：
//   - v=yMin 时整条线落在 y=height，1.8px 笔画下半被 SVG 视口裁掉
//     （用户反馈：曲线"超出底线被遮挡"）
//   - v=yMax 时落在 y=0，笔画上半同样被裁
//   - 末点圆点 r=2.4 在 y=0/height 时半圆裁掉
// 4px 是 (max(stroke/2, circle r) + 1) 的最近整数，刚好兜住。
const PAD_TOP = 4;
const PAD_BOTTOM = 4;

/** 把数据值 v 映射到 SVG y 坐标，带上下 padding；min/max/range 由调用方算好。 */
function valueToY(v: number, min: number, range: number): number {
  const usableH = props.height - PAD_TOP - PAD_BOTTOM;
  return PAD_TOP + usableH - ((v - min) / range) * usableH;
}

const path = computed(() => {
  const pts = props.points;
  if (pts.length === 0) return "";
  // yMax/yMin 显式 set 时，强制 Y 轴范围（不被数据 outlier 拉跨）。否则
  // 走传统 auto-scale。
  const dataMax = Math.max(...pts);
  const dataMin = Math.min(...pts);
  const max = typeof props.yMax === "number" ? props.yMax : dataMax;
  const min = typeof props.yMin === "number" ? props.yMin : dataMin;
  const range = max - min || 1;
  const stepX = props.width / Math.max(1, pts.length - 1);
  const xy = pts.map((v, i) => ({
    x: i * stepX,
    y: valueToY(v, min, range),
  }));
  if (xy.length === 1)
    return `M${xy[0].x.toFixed(2)} ${xy[0].y.toFixed(2)}`;

  const t = 0.25;
  let d = `M${xy[0].x.toFixed(2)} ${xy[0].y.toFixed(2)}`;
  for (let i = 0; i < xy.length - 1; i++) {
    const p0 = xy[i - 1] ?? xy[i];
    const p1 = xy[i];
    const p2 = xy[i + 1];
    const p3 = xy[i + 2] ?? p2;
    const cp1x = p1.x + (p2.x - p0.x) * t;
    const cp1y = p1.y + (p2.y - p0.y) * t;
    const cp2x = p2.x - (p3.x - p1.x) * t;
    const cp2y = p2.y - (p3.y - p1.y) * t;
    d +=
      ` C${cp1x.toFixed(2)} ${cp1y.toFixed(2)},` +
      ` ${cp2x.toFixed(2)} ${cp2y.toFixed(2)},` +
      ` ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
  }
  return d;
});

const lastPoint = computed(() => {
  const pts = props.points;
  if (!pts.length) return null;
  const dataMax = Math.max(...pts);
  const dataMin = Math.min(...pts);
  const max = typeof props.yMax === "number" ? props.yMax : dataMax;
  const min = typeof props.yMin === "number" ? props.yMin : dataMin;
  const range = max - min || 1;
  const stepX = props.width / Math.max(1, pts.length - 1);
  const i = pts.length - 1;
  return {
    x: i * stepX,
    y: valueToY(pts[i], min, range),
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
      :style="{ width: '100%', height: 'auto', overflow: 'visible' }"
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
