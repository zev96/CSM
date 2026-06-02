<script setup lang="ts">
/**
 * 各平台卡位 `PlatformStrip` —— 移植 design full-app.jsx。
 * 标题「各平台卡位 · N 个平台」+「查看明细 →」(跳平台对比)。下方 N 列等宽小卡：
 * 顶部 3px 状态色边 + 平台名 + 情感点 + 大字状态(首推#1/提及#2/未提及，色随状态)
 * + 底部小字「引用 N · 情感」。整卡可点跳明细。配色/字号严格照稿。
 */
import {
  cellStatus,
  isFailed,
  sentDotColor,
  sentLabel,
  type PlatformVM,
} from "@/components/monitor/geo/geoDetail";

const props = defineProps<{ platforms: PlatformVM[] }>();
const emit = defineEmits<{ (e: "more"): void }>();

// 平台数过多时小卡自适应：≤5 用 repeat(N,1fr)；>5 也铺 N 列（窄但仍等宽）。
const cols = () => `repeat(${Math.max(props.platforms.length, 1)}, 1fr)`;
</script>

<template>
  <div :style="{ padding: '14px 16px', borderRadius: '16px', background: 'var(--card)', border: '1px solid var(--line)' }">
    <div class="flex items-baseline justify-between" :style="{ marginBottom: '10px' }">
      <div class="font-display" :style="{ fontSize: '13px', fontWeight: 700 }">
        各平台卡位
        <span :style="{ fontSize: '10.5px', fontWeight: 500, color: 'var(--ink-3)' }">· {{ platforms.length }} 个平台</span>
      </div>
      <button
        type="button"
        :style="{ fontSize: '11px', fontWeight: 600, color: 'var(--primary-deep)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }"
        @click="emit('more')"
      >查看明细 →</button>
    </div>

    <div
      v-if="platforms.length"
      :style="{ display: 'grid', gridTemplateColumns: cols(), gap: '8px' }"
    >
      <div
        v-for="p in platforms"
        :key="p.id"
        class="geo-row cursor-pointer"
        :style="{ padding: '10px 11px', borderRadius: '12px', background: 'var(--card-2)', border: '1px solid var(--line)', borderTop: `3px solid ${cellStatus(p).color}` }"
        @click="emit('more')"
      >
        <div class="flex items-center justify-between" :style="{ gap: '4px' }">
          <span
            class="font-display truncate"
            :style="{ fontSize: '12px', fontWeight: 700 }"
          >{{ p.name }}</span>
          <span
            v-if="!isFailed(p)"
            :style="{ width: '8px', height: '8px', borderRadius: '999px', background: sentDotColor(p.sentiment), flexShrink: 0, display: 'inline-block' }"
          />
        </div>
        <div
          class="font-display"
          :style="{ fontSize: '15px', fontWeight: 700, color: cellStatus(p).color, marginTop: '5px' }"
        >{{ cellStatus(p).label }}</div>
        <div :style="{ fontSize: '10px', color: 'var(--ink-3)', marginTop: '3px' }">
          {{ isFailed(p) ? "够不到平台" : `引用 ${p.citations} · ${sentLabel(p.sentiment)}` }}
        </div>
      </div>
    </div>

    <div
      v-else
      :style="{ fontSize: '11.5px', color: 'var(--ink-3)', padding: '8px 2px' }"
    >暂无平台采集结果 · 运行一次后这里显示各平台卡位。</div>
  </div>
</template>
