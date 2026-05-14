<script setup lang="ts">
/**
 * 通用折线图 —— 封装 vue-chartjs 的 Line，统一应用色板和默认 tooltip 行为。
 *
 * 用法（评论留存率页 / 知乎排名页共用）：
 *   <LineChart
 *     :labels="['5/8','5/9','5/10',...]"
 *     :series="[
 *       { label:'B 站', color:'#ee6a2a', data:[80,75,72,...] },
 *       { label:'抖音', color:'#1e1c19', data:[90,90,88,...] },
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
  data: number[];
}

const props = defineProps<{
  labels: string[];
  series: Series[];
  yAxisFormatter?: (v: number) => string;
  dualAxis?: boolean;
}>();

const data = computed(() => ({
  labels: props.labels,
  datasets: props.series.map((s, i) => ({
    label: s.label,
    borderColor: s.color,
    backgroundColor: s.color + "20",  // 12% alpha 填充
    data: s.data,
    borderWidth: 2.2,
    tension: 0.25,
    pointRadius: 0,
    pointHoverRadius: 4,
    fill: false,
    yAxisID: props.dualAxis && i === 1 ? "y1" : "y",
  })),
}));

const options = computed<any>(() => {
  const base = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },  // 外部 legend 由父组件绘，更可控
      tooltip: {
        backgroundColor: "#1c1a17",
        titleColor: "#fbf7ec",
        bodyColor: "#fbf7ec",
        borderColor: "rgba(255,255,255,0.1)",
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
        grid: { color: "rgba(28,26,23,0.05)" },
        ticks: { color: "#7a7569", font: { size: 10 } },
      },
      y: {
        beginAtZero: true,
        grid: { color: "rgba(28,26,23,0.05)" },
        ticks: {
          color: props.dualAxis ? props.series[0]?.color || "#7a7569" : "#7a7569",
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
        color: props.series[1]?.color || "#7a7569",
        font: { size: 10 },
      },
    };
  }
  return base;
});
</script>

<template>
  <div style="position: relative; height: 170px;">
    <Line :data="data" :options="options" />
  </div>
</template>
