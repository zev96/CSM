<script setup lang="ts">
/**
 * 竞品 × 平台 排名热力矩阵 `RankHeatmap` —— 移植 design full-app.jsx。
 * 行 = 竞品 + 你；列 = 各平台。格子 = 该品牌在该平台位次(#1/#2…或 · 未上榜)。
 * 配色：竞品橙系深浅(#1 实心橙、渐浅)；你=绿系(#1 实心绿、渐浅)，与竞品拉开。
 * `·` 浅边空格。几何/配色严格照稿。
 *
 * 入参：platforms[]（VM，提供 id/name + recommended）、competitors[]（聚合名+序）、
 *       targetTerms（你的品牌名+别名，用于在 recommended 里识别 is_target 行）。
 */
import { computed } from "vue";

import {
  platformShort,
  targetRankOnPlatform,
  competitorRankOnPlatform,
  type PlatformVM,
  type CompetitorVM,
} from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  platforms: PlatformVM[];
  competitors: CompetitorVM[];
  targetName: string;
}>();

interface Row {
  name: string;
  isYou: boolean;
}
// 行：竞品（聚合顺序，已按 appears/avgRank 排）+ 末行「你」。最多取前 5 个竞品
// 避免矩阵过高（散点已展示全部）。
const rows = computed<Row[]>(() => {
  const comp = props.competitors.slice(0, 5).map((c) => ({ name: c.name, isYou: false }));
  return [...comp, { name: `${props.targetName}（你）`, isYou: true }];
});

// 某品牌在某平台的位次（0 = 未上榜）。你 → 用 cell 权威判定（mentioned+rank，
// targetRankOnPlatform），与概览一致，避免 recommended 里残留的 is_target 位次
// 与「未提及」自相矛盾；竞品 → competitorRankOnPlatform（归一化键 + 取该平台最优位次），
// 与竞品聚合 / 竞争结论文案共用同一口径。
function rankOf(p: PlatformVM, row: Row): number {
  return row.isYou ? targetRankOnPlatform(p) : competitorRankOnPlatform(p, row.name);
}

interface CellStyle {
  bg: string;
  color: string;
  txt: string;
}
function cellStyleOf(rank: number, isYou: boolean): CellStyle {
  if (rank === 0) return { bg: "transparent", color: "var(--ink-4)", txt: "·" };
  const o: Record<number, [string, string]> = {
    1: ["var(--primary)", "#fff"],
    2: ["var(--primary-soft)", "var(--primary-deep)"],
    3: ["rgba(238,106,42,.14)", "var(--primary-deep)"],
  };
  const g: Record<number, [string, string]> = {
    1: ["var(--green)", "#fff"],
    2: ["rgba(122,155,94,.30)", "var(--green)"],
    3: ["rgba(122,155,94,.16)", "var(--green)"],
  };
  const fallback: [string, string] = isYou
    ? ["rgba(122,155,94,.10)", "var(--green)"]
    : ["rgba(238,106,42,.07)", "var(--primary-deep)"];
  const m = (isYou ? g : o)[rank] ?? fallback;
  return { bg: m[0], color: m[1], txt: "#" + rank };
}

const cols = computed(() => `94px repeat(${props.platforms.length}, 1fr)`);
</script>

<template>
  <div>
    <!-- 表头：空 + 平台短名 -->
    <div :style="{ display: 'grid', gridTemplateColumns: cols, gap: '4px', marginBottom: '4px' }">
      <div />
      <div
        v-for="p in platforms"
        :key="p.id"
        :style="{ textAlign: 'center', fontSize: '9.5px', fontWeight: 600, color: 'var(--ink-3)', whiteSpace: 'nowrap' }"
      >{{ platformShort(p.id) }}</div>
    </div>
    <!-- 行 -->
    <div
      v-for="row in rows"
      :key="row.name"
      :style="{ display: 'grid', gridTemplateColumns: cols, gap: '4px', marginBottom: '4px', alignItems: 'center' }"
    >
      <div
        class="font-display truncate"
        :style="{ fontSize: '11.5px', fontWeight: row.isYou ? 700 : 600, color: row.isYou ? 'var(--primary-deep)' : 'var(--ink)', whiteSpace: 'nowrap' }"
        :title="row.name"
      >{{ row.name }}</div>
      <div
        v-for="p in platforms"
        :key="p.id"
        class="font-display"
        :style="{
          textAlign: 'center',
          padding: '5px 0',
          fontSize: '11.5px',
          fontWeight: 700,
          borderRadius: '7px',
          fontVariantNumeric: 'tabular-nums',
          background: cellStyleOf(rankOf(p, row), row.isYou).bg,
          color: cellStyleOf(rankOf(p, row), row.isYou).color,
          border: cellStyleOf(rankOf(p, row), row.isYou).txt === '·' ? '1px solid var(--line)' : 'none',
        }"
      >{{ cellStyleOf(rankOf(p, row), row.isYou).txt }}</div>
    </div>
  </div>
</template>
