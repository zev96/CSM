<script setup lang="ts">
/**
 * 关键词趋势卡 — 三段式可复用卡片（百度 / 知乎 共用）。
 *
 *   ┌─────────────────────────────────────────┐
 *   │ <category>                          [→] │
 *   │                                         │
 *   │ <selected.label 10字截断>     [<badge>] │
 *   │ <subLabel>                              │
 *   │                                         │
 *   │  ╱╲   ╲╱  (sparkline 高 60)              │
 *   │ 周一 周二 ... 今天                       │
 *   │                                         │
 *   │ <kw1>                       [↑ 3]      │  ← hover 整行 → 顶部 +
 *   │ <kw2>                       [↓ 2]      │     折线瞬时切到该行；行
 *   │ <kw3>                       [—]         │     橙底白字 + 阴影凸起
 *   └─────────────────────────────────────────┘
 *
 * 交互：
 *   - selected 默认 = items[0]
 *   - mouseenter 任意一行 → selected 切到该行；行变橙底白字 + box-shadow
 *     模拟悬浮卡片立体感；徽章背景换成白色（icon/文字保留涨跌方向色）
 *   - mouseleave → 复位为 items[0]
 *   - click 行 → emit('itemClick', item)，父组件负责 router.push 跳到
 *     对应任务详情（百度→monitor baidu tab + task，知乎→zhihu tab + task）
 *
 * 实现细节：
 *   - hover 状态用数组下标跟踪（不用 item.id），避免后端 demo 数据 task_id
 *     重复 / null 导致多行同时 highlight
 *   - 顶部大字 10 字截断 + "…"
 *   - badge.icon 空字符串时不渲染 <Icon>（flat 状态用纯文字 "—"）
 *
 * 设计约束：
 *   - 卡壳走 .card-frosted（磨砂玻璃 utility）
 *   - 主色 (--primary) 只在 hover 行的背景上出现；sparkline 走选中徽章
 *     语义色（up=绿、down=红、flat=灰）
 *   - row 的 background/color/box-shadow 由 scoped class .row-active 控制，
 *     不能 inline :style（inline 特异度 1000 会压死 class，
 *     feedback_vue_inline_style_hover_clobber.md）
 */
import { computed, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Sparkline from "@/components/ui/Sparkline.vue";

export type BadgeKind = "up" | "down" | "flat" | "warn" | "alert";

export interface BadgeSpec {
  text: string;
  /** Icon 名（arrowUp / arrowDown / alert ...）；空字符串则不渲染图标。 */
  icon: string;
  kind: BadgeKind;
}

export interface KeywordTrendItem {
  id: string | number;
  label: string;
  /** 折线数据；空则用 fallbackSeries。 */
  series?: number[];
  badge: BadgeSpec;
  /**
   * Y 轴上限（如知乎 Top-N=10）。提供时 sparkline 锁这个 max，曲线
   * 相对"容量"显示；不提供则走数据 auto-scale。每行可以不同（不同
   * 关键词 Top-N 不一样）—— hover 切行时 sparkline Y 轴跟着切。
   */
  yMax?: number;
}

const props = withDefaults(
  defineProps<{
    category: string;
    subLabel?: string;
    axisLabels: string[];
    items: KeywordTrendItem[];
    fallbackSeries?: number[];
    loaded?: boolean;
    emptyTitle?: string;
    emptyHint?: string;
    /** 顶部大字最大字符数，超出截断。默认 10。 */
    labelMaxChars?: number;
  }>(),
  {
    subLabel: "近 7 天",
    loaded: true,
    fallbackSeries: () => [],
    emptyTitle: "暂无数据",
    emptyHint: "",
    labelMaxChars: 10,
  },
);

const emit = defineEmits<{
  detail: [];
  itemClick: [item: KeywordTrendItem];
}>();

const hoveredIndex = ref<number | null>(null);

const selected = computed<KeywordTrendItem | null>(() => {
  if (props.items.length === 0) return null;
  const idx = hoveredIndex.value ?? 0;
  return props.items[idx] ?? props.items[0];
});

const sparkSeries = computed(() =>
  selected.value?.series && selected.value.series.length > 0
    ? selected.value.series
    : props.fallbackSeries,
);

// Y 轴上限跟着选中行走 —— hover 切到 #2 行就用 #2 关键词的 yMax（如
// 各自的 Top-N）。未提供则不传 yMax 让 sparkline 走 auto-scale。
const sparkYMax = computed<number | undefined>(() => {
  const v = selected.value?.yMax;
  return typeof v === "number" && v > 0 ? v : undefined;
});

const SEMANTIC_INK: Record<BadgeKind, string> = {
  up: "#4d6b2f",
  down: "#a3382a",
  flat: "var(--ink-2)",
  warn: "#7a5400",
  alert: "#a3382a",
};

const sparkStroke = computed(() => {
  const k = selected.value?.badge.kind;
  return k ? SEMANTIC_INK[k] : "var(--ink-2)";
});

function badgeNormalStyle(kind: BadgeKind) {
  if (kind === "up") return { background: "#dde7d2", color: "#4d6b2f" };
  if (kind === "down" || kind === "alert")
    return { background: "#f3d3cd", color: "#a3382a" };
  if (kind === "warn")
    return { background: "var(--yellow-soft)", color: "#7a5400" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}

function badgeInverseStyle(kind: BadgeKind) {
  return { background: "#ffffff", color: SEMANTIC_INK[kind] };
}

function trimLabel(label: string): string {
  if (!label) return "";
  return label.length > props.labelMaxChars
    ? label.slice(0, props.labelMaxChars) + "…"
    : label;
}
</script>

<template>
  <section
    class="card-frosted relative flex h-full flex-col overflow-hidden"
    :style="{ padding: '16px' }"
  >
    <!-- 标题区：分类 + 详情入口 -->
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
        {{ category }}
      </div>
      <button
        type="button"
        class="trend-detail inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full"
        title="详情"
        @click="emit('detail')"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <!-- 大标：选中关键词（10 字截断） + 徽章 -->
    <div class="mt-2 flex flex-shrink-0 items-center gap-2">
      <div
        class="font-display min-w-0 flex-1 truncate font-bold"
        :style="{ fontSize: '15px', color: 'var(--ink)' }"
      >
        {{ selected ? trimLabel(selected.label) : category }}
      </div>
      <span
        v-if="selected"
        class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
        :style="badgeNormalStyle(selected.badge.kind)"
      >
        <Icon v-if="selected.badge.icon" :name="selected.badge.icon" :size="9" />
        {{ selected.badge.text }}
      </span>
    </div>
    <div class="mt-0.5 mb-3 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
      {{ subLabel }}
    </div>

    <!-- Sparkline (height 60，比原 38 高，让趋势更易读) -->
    <div class="mb-3 flex-shrink-0">
      <Sparkline
        :points="sparkSeries"
        :axis-labels="axisLabels"
        :height="60"
        :stroke="sparkStroke"
        :show-last="true"
        :y-max="sparkYMax"
        :y-min="0"
        fluid
      />
    </div>

    <!-- 列表 -->
    <div
      v-if="!loaded"
      class="flex min-h-0 flex-1 items-center justify-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      加载中…
    </div>
    <div
      v-else-if="items.length === 0"
      class="flex min-h-0 flex-1 flex-col items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      <div>{{ emptyTitle }}</div>
      <div v-if="emptyHint" class="mt-1 text-[11px]">{{ emptyHint }}</div>
    </div>
    <div v-else class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <div
        v-for="(item, idx) in items"
        :key="item.id ?? idx"
        class="row flex items-center gap-2 rounded-[10px] px-2.5 py-2"
        :class="{ 'row-active': idx === hoveredIndex }"
        @mouseenter="hoveredIndex = idx"
        @mouseleave="hoveredIndex = null"
        @click="emit('itemClick', item)"
      >
        <div class="min-w-0 flex-1 truncate text-[12px]">
          {{ item.label }}
        </div>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="
            idx === hoveredIndex
              ? badgeInverseStyle(item.badge.kind)
              : badgeNormalStyle(item.badge.kind)
          "
        >
          <Icon v-if="item.badge.icon" :name="item.badge.icon" :size="9" />
          {{ item.badge.text }}
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.trend-detail {
  background: rgba(28, 26, 23, 0.04);
  color: var(--ink-2);
  border: 1px solid rgba(28, 26, 23, 0.06);
  transition: background-color 0.12s ease;
}
.trend-detail:hover {
  background: rgba(28, 26, 23, 0.08);
}

/*
 * 行默认透明，hover 时切到主色橙底 + 白字 + 双层阴影"凸起"效果。
 * box-shadow 第一层：主色软光晕（透明度 0.45 的 16px 大模糊 + -2 收缩
 * 让光晕只在底部边缘外溢）；第二层：中性深影（4% 黑色 6px 模糊）补
 * 立体厚度感。模拟悬浮卡片，跟设计稿一致。
 */
.row {
  background: transparent;
  color: var(--ink);
  transition:
    background-color 0.12s ease,
    color 0.12s ease,
    box-shadow 0.12s ease;
  cursor: pointer;
}
.row-active {
  background: var(--primary);
  color: #ffffff;
  box-shadow:
    0 6px 16px -2px rgba(238, 106, 42, 0.45),
    0 2px 6px rgba(28, 26, 23, 0.06);
}
</style>
