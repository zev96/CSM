<script setup lang="ts">
/**
 * 覆盖榜 —— 关键词 × 平台覆盖表（对齐图三）。
 * 列：# / 关键词 / 平台覆盖(格) / 命中 X/N / 曝光分(环比)。按曝光分降序。
 * 点平台格 emit('cell', {keyword, platformId}) → 父组件展开该平台 AI 原文+信源。
 */
import { computed } from "vue";

import {
  cellStatus,
  platformShort,
  type GeoKeywordRow,
  type PlatformVM,
} from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  rows: GeoKeywordRow[];
  platformIds: string[];
}>();

// 点击行（或某平台格）→ 跳转下钻页（父组件接管，不再页内下拉）。
// platformId='' = 整行点击（不定位具体平台）；非空 = 点中的平台置顶高亮。
const emit = defineEmits<{ cell: [payload: { keyword: string; platformId: string }] }>();

function openRow(keyword: string): void {
  emit("cell", { keyword, platformId: "" });
}
function openCell(e: MouseEvent, keyword: string, platformId: string): void {
  e.stopPropagation(); // 别再冒泡触发整行点击
  emit("cell", { keyword, platformId });
}

// 列：# / 关键词(收窄, 让热力图贴近) / 平台覆盖格 / 弹性占位 / 命中 / 曝光分。
// 关键词不再用 1.5fr（会把热力图推到最右、和关键词之间空一大段），改 bounded
// 宽度，多余宽度交给热力图右侧的 1fr 占位，命中/曝光分仍右对齐。
const cols = computed(
  () => `28px minmax(150px, 220px) ${props.platformIds.length * 56}px 1fr 56px 84px`,
);

function bg(cell: PlatformVM | null): string {
  if (!cell) return "var(--card)";
  const k = cellStatus(cell).kind;
  return k === "first"
    ? "var(--green)"
    : k === "hit"
      ? "var(--primary-soft)"
      : k === "fail"
        ? "rgba(216,90,72,.10)"
        : "var(--card)"; // miss / pending —— 浅底 + 描边，避免和卡片背景一致看不见
}
// 格子描边：命中=主色、失败=淡红、首推=无、未提及/未运行/空=暖灰描边（与图例「未提及」一致）。
function bd(cell: PlatformVM | null): string {
  if (!cell) return "1px solid var(--ink-4)";
  const k = cellStatus(cell).kind;
  if (k === "hit") return "1px solid var(--primary-deep)";
  if (k === "fail") return "1px solid rgba(216,90,72,.35)";
  if (k === "first") return "none";
  return "1px solid var(--ink-4)"; // miss / pending
}
function fg(cell: PlatformVM | null): string {
  if (!cell) return "var(--ink-4)";
  const k = cellStatus(cell).kind;
  return k === "first" ? "#fff" : k === "hit" ? "var(--primary-deep)" : "var(--ink-4)";
}
function label(cell: PlatformVM | null): string {
  if (!cell) return "";
  const k = cellStatus(cell).kind;
  if (k === "first") return "★";
  if (k === "hit") return `#${cell.rank}`;
  if (k === "fail") return "!";
  return ""; // miss / pending 留空
}
</script>

<template>
  <div class="flex min-h-0 flex-col">
    <!-- 图例 -->
    <div class="flex flex-shrink-0 items-center justify-end" :style="{ gap: '12px', marginBottom: '8px' }">
      <span class="inline-flex items-center" :style="{ gap: '5px' }">
        <span :style="{ width: '11px', height: '11px', borderRadius: '3px', background: 'var(--green)' }" />
        <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)' }">首位推荐</span>
      </span>
      <span class="inline-flex items-center" :style="{ gap: '5px' }">
        <span :style="{ width: '11px', height: '11px', borderRadius: '3px', background: 'var(--primary-soft)', border: '1px solid var(--primary-deep)' }" />
        <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)' }">榜单</span>
      </span>
      <span class="inline-flex items-center" :style="{ gap: '5px' }">
        <span :style="{ width: '11px', height: '11px', borderRadius: '3px', background: 'var(--card)', border: '1px solid var(--ink-4)' }" />
        <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)' }">未提及</span>
      </span>
    </div>

    <!-- 表头 -->
    <div
      class="grid flex-shrink-0 items-center"
      :style="{ gridTemplateColumns: cols, gap: '8px', padding: '0 10px 8px', borderBottom: '1px solid var(--line)' }"
    >
      <div :style="{ fontSize: '10px', color: 'var(--ink-3)', textAlign: 'center' }">#</div>
      <div :style="{ fontSize: '10px', color: 'var(--ink-3)' }">关键词</div>
      <div class="flex" :style="{ gap: '0px' }">
        <div
          v-for="p in platformIds"
          :key="p"
          :style="{ width: '56px', fontSize: '10.5px', fontWeight: 600, color: 'var(--ink-3)', textAlign: 'center', whiteSpace: 'nowrap' }"
          :title="platformShort(p)"
        >{{ platformShort(p) }}</div>
      </div>
      <div />
      <div :style="{ fontSize: '10px', color: 'var(--ink-3)', textAlign: 'center' }">命中</div>
      <div :style="{ fontSize: '10px', color: 'var(--ink-3)', textAlign: 'right' }">曝光分</div>
    </div>

    <!-- 行（滚动） -->
    <div v-if="!rows.length" class="py-8 text-center" :style="{ fontSize: '12px', color: 'var(--ink-3)' }">暂无关键词数据</div>
    <div v-else class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-for="(row, ri) in rows"
        :key="row.keyword"
        class="geo-kw-row grid items-center"
        role="button"
        tabindex="0"
        :title="`查看「${row.keyword}」各平台原文`"
        :style="{
          gridTemplateColumns: cols, gap: '8px', padding: '9px 10px',
          borderBottom: '1px solid rgba(var(--ink-rgb),0.05)',
        }"
        @click="openRow(row.keyword)"
        @keydown.enter.prevent="openRow(row.keyword)"
      >
        <div class="font-display" :style="{ fontSize: '12px', fontWeight: 700, color: 'var(--ink-4)', textAlign: 'center', fontVariantNumeric: 'tabular-nums' }">{{ ri + 1 }}</div>
        <div class="truncate" :style="{ fontSize: '12.5px', fontWeight: 600, color: 'var(--ink)' }" :title="row.keyword">{{ row.keyword }}</div>
        <!-- 平台覆盖格（每格放进 50px 居中槽，与加宽后的表头对齐）-->
        <div class="flex" :style="{ gap: '0px' }">
          <div
            v-for="(cell, ci) in row.cells"
            :key="ci"
            :style="{ width: '56px', display: 'flex', justifyContent: 'center' }"
          >
            <div
              class="font-display"
              :style="{
                width: '28px', height: '24px', borderRadius: '6px',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '10.5px', fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                background: bg(cell), color: fg(cell),
                border: bd(cell),
                cursor: 'pointer',
              }"
              :title="cell ? `${platformShort(platformIds[ci])} · ${cellStatus(cell).label}` : platformShort(platformIds[ci])"
              @click="cell && openCell($event, row.keyword, platformIds[ci])"
            >{{ label(cell) }}</div>
          </div>
        </div>
        <!-- 弹性占位：把热力图推近关键词、命中/曝光分推到右侧 -->
        <div />
        <!-- 命中 X/N -->
        <div :style="{ textAlign: 'center', fontSize: '11.5px', fontVariantNumeric: 'tabular-nums' }">
          <b :style="{ color: row.mentioned > 0 ? 'var(--ink)' : 'var(--ink-3)' }">{{ row.mentioned }}</b><span :style="{ color: 'var(--ink-3)' }">/{{ row.total }}</span>
        </div>
        <!-- 曝光分 + 环比 -->
        <div class="flex items-center justify-end" :style="{ gap: '6px' }">
          <span class="font-display" :style="{ fontSize: '14px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ row.score }}</span>
          <span
            v-if="row.scoreDelta !== 0"
            class="inline-flex items-center"
            :style="{
              fontSize: '9.5px', fontWeight: 600, padding: '1px 5px', borderRadius: '999px',
              fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap',
              color: row.scoreDelta > 0 ? '#5e7848' : 'var(--red)',
              background: row.scoreDelta > 0 ? 'rgba(122,155,94,.15)' : 'rgba(216,90,72,.12)',
            }"
          >{{ row.scoreDelta > 0 ? "↑" : "↓" }}{{ Math.abs(row.scoreDelta) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 可点击的覆盖榜行 —— 行本身无 inline 背景，scoped :hover 安全（不会压死
   选中态橙底，因为这里已无选中态）。整行 + 平台格都跳转下钻页。 */
.geo-kw-row {
  cursor: pointer;
  transition: background 0.12s ease;
  border-radius: 8px;
}
.geo-kw-row:hover {
  background: rgba(var(--ink-rgb), 0.035);
}
.geo-kw-row:focus-visible {
  outline: none;
  background: rgba(var(--ink-rgb), 0.05);
}
</style>
