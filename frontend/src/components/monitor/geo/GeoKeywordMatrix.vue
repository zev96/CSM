<script setup lang="ts">
/**
 * 关键词 × AI 平台 矩阵 —— 行 = 关键词，列 = 平台。
 * 格子用 cellStatus 着色；点有数据的格子 emit('cell', {keyword, platformId})。
 */
import { computed } from "vue";

import { cellStatus, platformShort, type PlatformVM } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  keywords: string[];
  platformIds: string[];
  matrix: Record<string, Record<string, PlatformVM>>;
}>();

const emit = defineEmits<{
  cell: [payload: { keyword: string; platformId: string }];
}>();

const cols = computed(() => `120px repeat(${props.platformIds.length}, 1fr)`);
</script>

<template>
  <div>
    <!-- 表头：空 + 平台短名 -->
    <div :style="{ display: 'grid', gridTemplateColumns: cols, gap: '4px', marginBottom: '4px' }">
      <div />
      <div
        v-for="p in platformIds"
        :key="p"
        :style="{ textAlign: 'center', fontSize: '9.5px', fontWeight: 600, color: 'var(--ink-3)', whiteSpace: 'nowrap' }"
      >{{ platformShort(p) }}</div>
    </div>
    <!-- 行 -->
    <div
      v-for="kw in keywords"
      :key="kw"
      :style="{ display: 'grid', gridTemplateColumns: cols, gap: '4px', marginBottom: '4px', alignItems: 'center' }"
    >
      <!-- 行头：关键词 -->
      <div
        class="font-display truncate"
        :style="{ fontSize: '11.5px', fontWeight: 600, color: 'var(--ink)', whiteSpace: 'nowrap' }"
        :title="kw"
      >{{ kw }}</div>
      <!-- 格子 -->
      <div
        v-for="p in platformIds"
        :key="p"
        class="font-display"
        :style="{
          textAlign: 'center',
          padding: '5px 0',
          fontSize: '11.5px',
          fontWeight: 700,
          borderRadius: '7px',
          fontVariantNumeric: 'tabular-nums',
          background: matrix[kw]?.[p] ? (cellStatus(matrix[kw][p]).kind === 'first' ? 'var(--green)' : cellStatus(matrix[kw][p]).kind === 'hit' ? 'var(--primary-soft)' : cellStatus(matrix[kw][p]).kind === 'fail' ? 'rgba(216,90,72,.12)' : 'transparent') : 'transparent',
          color: matrix[kw]?.[p] ? cellStatus(matrix[kw][p]).color : 'var(--ink-4)',
          border: matrix[kw]?.[p] ? 'none' : '1px solid var(--line)',
          cursor: matrix[kw]?.[p] ? 'pointer' : 'default',
        }"
        @click="matrix[kw]?.[p] ? emit('cell', { keyword: kw, platformId: p }) : undefined"
      >{{ matrix[kw]?.[p] ? cellStatus(matrix[kw][p]).short : '·' }}</div>
    </div>
  </div>
</template>
