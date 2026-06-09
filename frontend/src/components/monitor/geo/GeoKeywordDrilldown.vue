<script setup lang="ts">
/**
 * 覆盖榜「关键词」下钻页 —— 替代原页内下拉（布局错乱），作为 GEO 区的下一级页面。
 *   顶部：返回 + 关键词 + 品牌 + 覆盖统计（覆盖带 / 命中 X/N / 曝光分）
 *   正文：masonry 两列各平台原文 + 引用信源（复用 GeoPlatformBlock，唯一滚动区）
 * 从覆盖榜点中的平台（highlightPlatformId）置顶，便于直达；整行点击则按平台顺序。
 */
import { computed } from "vue";

import GeoPlatformBlock from "@/components/monitor/geo/GeoPlatformBlock.vue";
import type { GeoKeywordRow, PlatformVM } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  keyword: string;
  row: GeoKeywordRow | null;
  /** 该关键词全部平台（按 platformIds 顺序，缺采集的已补占位卡）。 */
  platforms: PlatformVM[];
  brand: string;
  brandTerms: string[];
  /** 覆盖榜点中的平台 id；'' / 不传 = 整行点击，不置顶。 */
  highlightPlatformId?: string;
}>();

const emit = defineEmits<{ back: [] }>();

const displayBrand = computed(
  () => props.brandTerms.find((t) => t && t.trim()) ?? props.brand ?? "",
);

// 点中的平台置顶（masonry 第一列顶部 = 第一眼可见），其余保持原顺序。
const ordered = computed<PlatformVM[]>(() => {
  const hl = props.highlightPlatformId;
  if (!hl) return props.platforms;
  const idx = props.platforms.findIndex((p) => p.id === hl);
  if (idx < 0) return props.platforms;
  return [
    props.platforms[idx],
    ...props.platforms.slice(0, idx),
    ...props.platforms.slice(idx + 1),
  ];
});

// 覆盖带（CoverageBand → 中文/色）。dominated 霸屏 · partial 部分覆盖 · blind 盲区。
const bandText = computed(() => {
  const b = props.row?.band;
  return b === "dominated" ? "霸屏" : b === "partial" ? "部分覆盖" : b === "blind" ? "盲区" : "—";
});
const bandColor = computed(() => {
  const b = props.row?.band;
  return b === "dominated"
    ? "var(--green)"
    : b === "partial"
      ? "var(--primary-deep)"
      : "var(--red)";
});
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- ── 顶部：返回 + 关键词 + 覆盖统计 ─────────────────────────────── -->
    <div
      class="flex flex-shrink-0 items-center justify-between"
      :style="{ gap: '12px', marginBottom: '14px' }"
    >
      <div class="flex min-w-0 items-center" :style="{ gap: '12px' }">
        <button
          type="button"
          class="geo-back inline-flex flex-shrink-0 items-center"
          :style="{
            gap: '5px', fontSize: '12px', fontWeight: 600, color: 'var(--ink-2)',
            background: 'var(--card)', border: '1px solid var(--line)', borderRadius: '999px',
            padding: '6px 13px', cursor: 'pointer', fontFamily: 'inherit',
          }"
          @click="emit('back')"
        >
          <span :style="{ fontSize: '14px', lineHeight: 1, marginTop: '-1px' }">←</span>
          <span>返回</span>
        </button>
        <div class="min-w-0">
          <div
            class="font-display truncate"
            :style="{ fontSize: '15.5px', fontWeight: 700, color: 'var(--ink)' }"
            :title="keyword"
          >{{ keyword }}</div>
          <div :style="{ fontSize: '11px', color: 'var(--ink-3)', marginTop: '1px' }">
            {{ displayBrand }} · 各 AI 平台原文与引用信源
          </div>
        </div>
      </div>

      <div v-if="row" class="flex flex-shrink-0 items-center" :style="{ gap: '12px' }">
        <span
          class="inline-flex items-center"
          :style="{
            gap: '5px', fontSize: '11px', fontWeight: 600, padding: '4px 11px',
            borderRadius: '999px', color: bandColor, background: 'var(--card)',
            border: '1px solid var(--line)',
          }"
        >
          <span :style="{ width: '7px', height: '7px', borderRadius: '999px', background: bandColor }" />
          {{ bandText }}
        </span>
        <span :style="{ fontSize: '11.5px', color: 'var(--ink-3)', whiteSpace: 'nowrap' }">
          命中
          <b :style="{ color: 'var(--ink)', fontVariantNumeric: 'tabular-nums' }">{{ row.mentioned }}</b>/{{ row.total }}
        </span>
        <span class="inline-flex items-baseline" :style="{ gap: '4px' }">
          <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)' }">曝光分</span>
          <span class="font-display" :style="{ fontSize: '16px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ row.score }}</span>
        </span>
      </div>
    </div>

    <!-- ── 正文：masonry 两列平台原文（唯一滚动区）─────────────────────── -->
    <div class="geo-scroll min-h-0 flex-1 overflow-y-auto" :style="{ paddingRight: '2px' }">
      <div
        v-if="!ordered.length"
        class="py-12 text-center"
        :style="{ fontSize: '12px', color: 'var(--ink-3)' }"
      >该关键词暂无平台采集结果 · 运行一次后这里显示各平台原文与信源。</div>
      <div v-else :style="{ columnCount: 2, columnGap: '14px' }">
        <GeoPlatformBlock
          v-for="p in ordered"
          :key="p.id"
          :platform="p"
          :brand="brand"
          :brand-terms="brandTerms"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.geo-back {
  transition: background 0.12s ease;
}
.geo-back:hover {
  background: var(--card-2);
}
</style>
