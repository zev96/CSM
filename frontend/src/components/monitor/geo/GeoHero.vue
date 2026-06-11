<script setup lang="ts">
/**
 * 诊断头 `BHero` —— 移植 design version-b.jsx：横向布局 = 半圆仪表盘 `BGauge`
 * (曝光评级) + 三块数字 `BStatTile`(SoC/首推率/情感) + 下方黄色结论条。
 * wide=横向铺开（概览页用）。配色/字号/间距严格照稿。
 */
import GeoGauge from "@/components/monitor/geo/charts/GeoGauge.vue";
import {
  pct,
  sentimentText,
  bandColor,
  bandLabel,
  type KeywordMetric,
} from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  metric: KeywordMetric | null;
  conclusion: string;
}>();

// 空 metric（未跑）时给 0 值占位，仪表盘点亮到 0、数字显 —。
const soc = () => props.metric?.soc ?? 0;
const band = () => props.metric?.status_band;
</script>

<template>
  <div>
    <div class="flex items-center" :style="{ gap: '18px' }">
      <!-- 半圆仪表盘 -->
      <div :style="{ flexShrink: 0, width: '230px' }">
        <div :style="{ fontSize: '9.5px', letterSpacing: '1px', textTransform: 'uppercase', color: 'var(--ink-3)' }">曝光评级</div>
        <GeoGauge
          :value="soc()"
          :score="Math.round(soc() * 100)"
          :label="bandLabel(band())"
          :color="bandColor(band())"
        />
      </div>

      <!-- 三块数字 -->
      <div class="flex" :style="{ gap: '8px', flex: 1 }">
        <!-- 曝光 SoC（带色条，色随档位）-->
        <div
          :style="{ flex: 1, minWidth: 0, padding: '10px 13px', borderRadius: '12px', background: 'var(--card)', border: '1px solid var(--line)' }"
        >
          <div :style="{ fontSize: '9.5px', letterSpacing: '0.6px', textTransform: 'uppercase', color: 'var(--ink-3)' }">曝光 SoC</div>
          <div
            class="font-display"
            :style="{ fontSize: '24px', fontWeight: 700, color: bandColor(band()), marginTop: '4px', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }"
          >{{ metric ? pct(metric.soc) : "—" }}</div>
          <div :style="{ marginTop: '9px' }">
            <div :style="{ height: '5px', borderRadius: '999px', background: 'rgba(var(--ink-rgb),.08)', overflow: 'hidden' }">
              <div :style="{ width: `${Math.max(0, Math.min(1, soc())) * 100}%`, height: '100%', background: bandColor(band()), borderRadius: '999px' }" />
            </div>
          </div>
        </div>
        <!-- 首推率（橙条）-->
        <div
          :style="{ flex: 1, minWidth: 0, padding: '10px 13px', borderRadius: '12px', background: 'var(--card)', border: '1px solid var(--line)' }"
        >
          <div :style="{ fontSize: '9.5px', letterSpacing: '0.6px', textTransform: 'uppercase', color: 'var(--ink-3)' }">首推率</div>
          <div
            class="font-display"
            :style="{ fontSize: '24px', fontWeight: 700, color: 'var(--primary)', marginTop: '4px', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }"
          >{{ metric ? pct(metric.first_rank_rate) : "—" }}</div>
          <div :style="{ marginTop: '9px' }">
            <div :style="{ height: '5px', borderRadius: '999px', background: 'rgba(var(--ink-rgb),.08)', overflow: 'hidden' }">
              <div :style="{ width: `${Math.max(0, Math.min(1, metric?.first_rank_rate ?? 0)) * 100}%`, height: '100%', background: 'var(--primary)', borderRadius: '999px' }" />
            </div>
          </div>
        </div>
        <!-- 情感得分（绿，无色条）-->
        <div
          :style="{ flex: 1, minWidth: 0, padding: '10px 13px', borderRadius: '12px', background: 'var(--card)', border: '1px solid var(--line)' }"
        >
          <div :style="{ fontSize: '9.5px', letterSpacing: '0.6px', textTransform: 'uppercase', color: 'var(--ink-3)' }">情感得分</div>
          <div
            class="font-display"
            :style="{ fontSize: '24px', fontWeight: 700, color: 'var(--green)', marginTop: '4px', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }"
          >{{ metric ? sentimentText(metric.sentiment_score) : "—" }}</div>
        </div>
      </div>
    </div>

    <!-- 黄色结论条 -->
    <div
      class="flex items-center"
      :style="{ marginTop: '12px', gap: '10px', padding: '10px 14px', borderRadius: '12px', background: 'var(--yellow-soft)', border: '1px solid rgba(245,192,66,.45)' }"
    >
      <span :style="{ width: '7px', height: '7px', borderRadius: '999px', background: 'var(--yellow)', flexShrink: 0 }" />
      <span :style="{ fontSize: '12px', color: '#8a6a1a', lineHeight: 1.5 }">{{ conclusion }}</span>
    </div>
  </div>
</template>
