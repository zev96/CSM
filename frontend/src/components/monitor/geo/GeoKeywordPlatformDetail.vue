<script setup lang="ts">
/**
 * GEO「单关键词 · 多平台详情」可复用块 —— 同一份模板被两处复用：
 *   1. GeoTaskModule L1 右侧（单关键词任务，详情内联在 KPI/信源榜下方）。
 *   2. GeoTaskDetailPage L2 右侧（多关键词任务，点左侧某关键词后右侧渲染该词）。
 *
 * 入参 = 一个关键词 + 该关键词在各平台的 cells（已由父组件按 keyword 过滤）。
 * 每个平台渲染一张卡：平台名 + 状态（采集失败 / 提及✓·#rank·情感 / 未提及），
 * 内联展开 AI 原文 / 推荐顺序（高亮 is_target=你的品牌）/ 引用信源。
 *
 * 自身不拉数据、不 emit —— 纯展示。视觉沿用 GeoTaskDetailPage / BaiduRankingPage
 * 的设计系统 idiom（card-2 + Pill + var(--*) 色），不另造观感。
 */
import { computed } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import { GEO_PLATFORMS } from "@/utils/monitor-types";

interface RecommendedEntity {
  name: string;
  position: number;
  is_target: boolean;
}
interface CellCitation {
  url: string;
  title: string;
  domain: string;
  source_type: string;
}
// /api/monitor/geo/{id}/latest-cells 的 cells[] 元素（geo_storage 水合后）。
export interface GeoCellRow {
  platform: string;
  keyword: string;
  mentioned: boolean | number;
  rank: number;
  sentiment: string;
  status: string;
  answer_text: string;
  citations: CellCitation[];
  recommended: RecommendedEntity[];
  summary: string;
}

const props = defineProps<{
  keyword: string;
  // 该关键词在各平台的 cell（父组件已过滤好；顺序即展示顺序）。
  cells: GeoCellRow[];
}>();

// ── 平台标签 ─────────────────────────────────────────────────────────────
const PLATFORM_LABEL: Record<string, string> = Object.fromEntries(
  GEO_PLATFORMS.map((p) => [p.value, p.label]),
);
function platformLabel(value: string): string {
  return PLATFORM_LABEL[value] ?? value;
}

// 按平台排好序的 cell（稳定展示顺序：先 GEO_PLATFORMS 既定顺序，再其余）。
const orderedCells = computed<GeoCellRow[]>(() => {
  const order = new Map<string, number>(GEO_PLATFORMS.map((p, i) => [p.value, i]));
  return [...props.cells].sort((a, b) => {
    const ia = order.has(a.platform) ? order.get(a.platform)! : 999;
    const ib = order.has(b.platform) ? order.get(b.platform)! : 999;
    if (ia !== ib) return ia - ib;
    return a.platform.localeCompare(b.platform);
  });
});

// ── cell 展示工具（与 GeoTaskDetailPage 同口径）──────────────────────────
function isMentioned(c: GeoCellRow): boolean {
  return c.mentioned === true || c.mentioned === 1;
}
function isFailed(c: GeoCellRow): boolean {
  return c.status === "error" || c.status === "blocked";
}
function sentimentDot(sentiment: string): string {
  if (sentiment === "pos") return "var(--green)";
  if (sentiment === "neg") return "var(--red, #d85a48)";
  if (sentiment === "neu") return "var(--ink-3)";
  return "transparent";
}
function sentimentLabel(sentiment: string): string {
  if (sentiment === "pos") return "正面";
  if (sentiment === "neg") return "负面";
  if (sentiment === "neu") return "中性";
  return "未判定";
}
function statusLabel(status: string): string {
  if (status === "ok") return "正常";
  if (status === "blocked") return "被拦截";
  if (status === "error") return "采集失败";
  if (status === "empty") return "空回答";
  return status;
}
function statusTone(status: string): "ok" | "warn" | "alert" | "info" {
  if (status === "ok") return "ok";
  if (status === "blocked") return "warn";
  if (status === "error") return "alert";
  return "info";
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 该关键词这次没有任何平台 cell（config 里有但没跑 / 都失败丢了）-->
    <div
      v-if="orderedCells.length === 0"
      class="rounded text-center text-[12px]"
      :style="{ color: 'var(--ink-3)', background: 'var(--card-2)', border: '1px solid var(--line)', padding: '18px 12px' }"
    >
      该关键词暂无平台采集结果 · 点「运行」采集一次后会显示各平台卡位详情。
    </div>

    <!-- 每个平台一张卡 -->
    <div
      v-for="c in orderedCells"
      :key="c.platform"
      class="flex flex-col"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: '12px',
        padding: '14px 16px',
        gap: '10px',
      }"
    >
      <!-- 平台头：平台名 + 状态条（提及/未提及/#rank/情感/状态）-->
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <span class="font-display text-[13.5px] font-semibold">{{ platformLabel(c.platform) }}</span>
          <Pill :tone="statusTone(c.status)">{{ statusLabel(c.status) }}</Pill>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <!-- 采集失败 / 被拦：不展示提及态 -->
          <template v-if="isFailed(c)">
            <span
              class="inline-flex items-center gap-1 text-[11.5px] font-medium"
              :style="{ color: c.status === 'blocked' ? 'var(--primary-deep, #c9521f)' : 'var(--red, #d85a48)' }"
            >
              <Icon name="warn" :size="11" />
              采集失败
            </span>
          </template>
          <template v-else>
            <!-- 提及态 + 顺位 -->
            <span
              class="inline-flex items-center gap-1.5 rounded-full text-[11.5px] font-medium"
              :style="{ background: 'var(--card)', border: '1px solid var(--line)', padding: '3px 10px' }"
            >
              <template v-if="isMentioned(c)">
                <span :style="{ color: 'var(--green)' }">提及</span>
                <span class="font-display font-bold" :style="{ color: 'var(--ink)' }">
                  {{ c.rank > 0 ? `#${c.rank}` : "—" }}
                </span>
              </template>
              <template v-else>
                <span :style="{ color: 'var(--ink-3)' }">未提及</span>
              </template>
            </span>
            <!-- 情感点 -->
            <span
              class="inline-flex items-center gap-1.5 rounded-full text-[11.5px]"
              :style="{ background: 'var(--card)', border: '1px solid var(--line)', padding: '3px 10px' }"
            >
              <span
                :style="{ width: '8px', height: '8px', borderRadius: '999px', background: sentimentDot(c.sentiment) }"
              />
              <span :style="{ color: 'var(--ink-2)' }">{{ sentimentLabel(c.sentiment) }}</span>
            </span>
          </template>
        </div>
      </div>

      <!-- 推荐顺序（高亮 is_target = 你的品牌）—— 仅非失败 cell 显示 -->
      <div v-if="!isFailed(c)">
        <div class="mb-1.5 text-[11.5px] font-semibold">推荐顺序 · 谁排在你前面</div>
        <div
          v-if="c.recommended.length === 0"
          class="text-[11.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >这次回答未给出明确的推荐列表。</div>
        <div v-else class="flex flex-col gap-1.5">
          <div
            v-for="r in c.recommended"
            :key="r.position + ' ' + r.name"
            class="flex items-center gap-2.5"
            :style="{
              padding: '7px 10px',
              borderRadius: '9px',
              background: r.is_target ? 'var(--primary-soft)' : 'var(--card)',
              border: r.is_target ? '1px solid var(--primary)' : '1px solid var(--line)',
            }"
          >
            <span
              class="inline-flex flex-shrink-0 items-center justify-center font-display text-[11.5px] font-bold"
              :style="{
                width: '20px',
                height: '20px',
                borderRadius: '999px',
                background: r.is_target ? 'var(--primary)' : 'var(--card-2)',
                color: r.is_target ? '#fff' : 'var(--ink-2)',
              }"
            >{{ r.position }}</span>
            <span
              class="truncate text-[12.5px]"
              :style="{ color: r.is_target ? 'var(--primary-deep, #c9521f)' : 'var(--ink)', fontWeight: r.is_target ? 700 : 500 }"
              :title="r.name"
            >{{ r.name }}</span>
            <span
              v-if="r.is_target"
              class="ml-auto flex-shrink-0 rounded-full text-[10px] font-medium"
              :style="{ background: 'var(--primary)', color: '#fff', padding: '1px 7px' }"
            >你的品牌</span>
          </div>
        </div>
      </div>

      <!-- AI 原文 -->
      <div v-if="!isFailed(c)">
        <div class="mb-1.5 flex items-center gap-2">
          <div class="text-[11.5px] font-semibold">AI 原文</div>
          <span v-if="c.summary" class="text-[11px]" :style="{ color: 'var(--ink-3)' }">· {{ c.summary }}</span>
        </div>
        <div
          class="whitespace-pre-wrap text-[12px] leading-relaxed"
          :style="{
            color: 'var(--ink-2)',
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderRadius: '9px',
            padding: '10px 12px',
            maxHeight: '220px',
            overflowY: 'auto',
          }"
        >{{ c.answer_text || "（无原文 —— 该平台未返回可见回答）" }}</div>
      </div>

      <!-- 引用信源 -->
      <div v-if="!isFailed(c)">
        <div class="mb-1.5 text-[11.5px] font-semibold">
          引用信源
          <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">（{{ c.citations.length }}）</span>
        </div>
        <div
          v-if="c.citations.length === 0"
          class="text-[11.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >这次回答未引用可识别的来源。</div>
        <div v-else class="flex flex-col gap-1.5">
          <a
            v-for="(ct, ci) in c.citations"
            :key="ci"
            :href="ct.url || undefined"
            target="_blank"
            rel="noopener noreferrer"
            class="flex flex-col gap-0.5"
            :style="{
              padding: '8px 10px',
              borderRadius: '9px',
              background: 'var(--card)',
              border: '1px solid var(--line)',
              textDecoration: 'none',
            }"
          >
            <div class="flex items-center gap-2">
              <Pill tone="info">{{ ct.source_type }}</Pill>
              <span class="truncate text-[12px] font-medium" :style="{ color: 'var(--ink)' }" :title="ct.domain">
                {{ ct.domain || "—" }}
              </span>
            </div>
            <span
              v-if="ct.title"
              class="truncate text-[11.5px]"
              :style="{ color: 'var(--ink-2)' }"
              :title="ct.title"
            >{{ ct.title }}</span>
            <span class="truncate text-[10.5px]" :style="{ color: 'var(--ink-3)' }" :title="ct.url">{{ ct.url }}</span>
          </a>
        </div>
      </div>
    </div>
  </div>
</template>
