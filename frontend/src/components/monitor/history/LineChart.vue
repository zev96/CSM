<script setup lang="ts">
/**
 * 通用折线图 —— 封装 vue-chartjs 的 Line，统一应用色板和默认 tooltip 行为。
 *
 * 用法（评论留存率页 / 知乎排名页共用）：
 *   <LineChart
 *     :labels="['5/8','5/9','5/10',...]"
 *     :series="[
 *       { label:'B 站', color:'#ee6a2a', data:[80,75,72,...] },
 *       { label:'抖音', color:'var(--ink)', data:[90,90,88,...] },
 *     ]"
 *     :y-axis-formatter="(v) => `${v}%`"
 *   />
 *
 * dualAxis 模式（知乎页占有率% + 异动数）：
 *   <LineChart :labels="..." :series="..." dual-axis />
 *   第一条线绑左轴，第二条线绑右轴。
 *
 * 我们只 register 真正用到的 controllers/elements/scales —— chart.js v4
 * tree-shake 友好，避免引入完整 ~150KB 的非压缩 bundle。
 */
import { computed } from "vue";
import { Line } from "vue-chartjs";
import { useChartTheme } from "@/composables/useChartTheme";
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler,
} from "chart.js";

Chart.register(
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler,
);

interface Series {
  label: string;
  color: string;
  // null 表示该 x 位置无数据 —— chart.js 默认 spanGaps=false，会在该点
  // 断线，符合"那天没监测"的视觉语义（vs. 0 = 那天监测了但卡位为 0）。
  data: (number | null)[];
}

const { theme, resolveColor } = useChartTheme();

const props = defineProps<{
  labels: string[];
  series: Series[];
  yAxisFormatter?: (v: number) => string;
  dualAxis?: boolean;
  /**
   * 强制 y 轴上限 —— 百分比类图表传 100 给出固定刻度（0/20/40/60/80/100），
   * 避免 chart.js auto-scale 把 60% 数据点顶到最顶（导致曲线视觉上"压在
   * 天花板"）。不传 = 走默认 auto-scale。
   */
  yMax?: number;
  /** 容器高度 —— 默认固定 170px；传 "100%" 让图表填满 flex 父容器（避免溢出遮挡）。 */
  height?: string;
  /**
   * 数据点圆点半径 —— 默认 0（只在 hover 显示，留存/知乎页保持原样）。传 >0 让
   * 每个数据点常显小圆点（GEO 覆盖率图用，避免必须 hover 才看得到值）。
   */
  pointRadius?: number;
  /**
   * 画布内边距(px) —— 默认 0。给百分比图留顶/右边距，避免 100% 数据点贴边被裁。
   */
  padding?: number;
}>();

const data = computed(() => {
  const t = theme.value; // track theme so datasets recompute on flip
  return {
    labels: props.labels,
    datasets: props.series.map((s, i) => {
      const c = resolveColor(s.color);
      return {
        label: s.label,
        borderColor: c,
        backgroundColor: c + "20", // 12% alpha fill
        data: s.data,
        borderWidth: 2.2,
        tension: 0.25,
        pointRadius: props.pointRadius ?? 0,
        pointHoverRadius: Math.max(4, (props.pointRadius ?? 0) + 1),
        pointBackgroundColor: c,
        pointBorderColor: t.pointBorder,
        pointBorderWidth: props.pointRadius ? 1 : 0,
        // 常显圆点时关闭裁剪 —— chart.js 默认把数据集裁到 chartArea，导致正好
        // 落在 100%（轴顶）的点被切成半圆。配合 layout.padding 留白即可完整显示。
        clip: props.pointRadius ? (false as const) : undefined,
        fill: false,
        yAxisID: props.dualAxis && i === 1 ? "y1" : "y",
      };
    }),
  };
});

const options = computed<any>(() => {
  const t = theme.value;
  const base = {
    responsive: true,
    maintainAspectRatio: false,
    layout: { padding: props.padding ?? 0 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false }, // 外部 legend 由父组件绘，更可控
      tooltip: {
        backgroundColor: t.tooltipBg,
        titleColor: t.tooltipFg,
        bodyColor: t.tooltipFg,
        borderColor: t.tooltipBorder,
        borderWidth: 1,
        padding: 10,
        boxPadding: 4,
        callbacks: props.yAxisFormatter
          ? { label: (ctx: any) => `${ctx.dataset.label}: ${props.yAxisFormatter!(ctx.parsed.y)}` }
          : undefined,
      },
    },
    scales: {
      x: {
        grid: { color: t.grid },
        ticks: { color: t.tick, font: { size: 10 } },
      },
      y: {
        beginAtZero: true,
        // yMax 显式 set 时强制上限（百分比固定 0-100 是典型场景）
        ...(typeof props.yMax === "number" ? { max: props.yMax } : {}),
        grid: { color: t.grid },
        ticks: {
          color: props.dualAxis ? resolveColor(props.series[0]?.color || "var(--ink-3)") : t.tick,
          font: { size: 10 },
          callback: props.yAxisFormatter
            ? function (this: any, v: any) { return props.yAxisFormatter!(Number(v)); }
            : undefined,
        },
      },
    } as Record<string, any>,
  };
  if (props.dualAxis) {
    base.scales.y1 = {
      position: "right",
      beginAtZero: true,
      grid: { drawOnChartArea: false },
      ticks: {
        color: resolveColor(props.series[1]?.color || "var(--ink-3)"),
        font: { size: 10 },
      },
    };
  }
  return base;
});
</script>

<template>
  <div :style="{ position: 'relative', height: height ?? '170px' }">
    <Line :data="data" :options="options" />
  </div>
</template>
