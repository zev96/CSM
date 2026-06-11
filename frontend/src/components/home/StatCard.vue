<script setup lang="ts">
/**
 * 大数字统计卡（首页 Row 1）—— 纯展示组件。
 *   ┌──────────────────────────┐
 *   │ 百度 SEO            [→]  │
 *   │                          │
 *   │ 5            [↑ 2]       │  ← 大数字 + 较上周净增减 pill
 *   │ 近 7 天异动               │
 *   └──────────────────────────┘
 * value = 最近 7 天异动（升+降）关键词/问题数；delta = 较上一个 7 天的净增减
 * （null = 无对比基准，不显示 pill）。
 */
import Icon from "@/components/ui/Icon.vue";

defineProps<{
  category: string;
  value: number;
  delta: number | null;
  loaded?: boolean;
}>();
const emit = defineEmits<{ detail: [] }>();

function pillStyle(d: number) {
  if (d > 0) return { background: "var(--green-soft)", color: "var(--green-deep)" };
  if (d < 0) return { background: "var(--red-soft)", color: "var(--red-deep)" };
  return { background: "rgba(var(--ink-rgb), 0.06)", color: "var(--ink-2)" };
}
</script>

<template>
  <section
    class="card-frosted relative flex h-full flex-col overflow-hidden"
    :style="{ padding: '16px', containerType: 'size' }"
  >
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">{{ category }}</div>
      <button
        type="button"
        class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情"
        @click="emit('detail')"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <div class="mt-auto flex items-end justify-between gap-2">
      <!-- 左：涨跌徽章 + 近7天异动（左对齐、上下叠） -->
      <div class="flex min-w-0 flex-col gap-1">
        <span
          v-if="loaded && delta !== null"
          class="inline-flex h-5 w-fit items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="pillStyle(delta)"
        >
          <Icon v-if="delta > 0" name="arrowUp" :size="9" />
          <Icon v-else-if="delta < 0" name="arrowDown" :size="9" />
          {{ Math.abs(delta) }}
        </span>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">近 7 天异动</div>
      </div>
      <!-- 右：大数字 -->
      <div
        class="font-display flex-shrink-0 font-bold"
        :style="{ fontSize: 'clamp(26px, 24cqh, 96px)', lineHeight: 1, letterSpacing: '-1px', color: 'var(--ink)' }"
      >
        {{ loaded ? value : "—" }}
      </div>
    </div>
  </section>
</template>

<style scoped>
.trend-detail {
  background: rgba(var(--ink-rgb), 0.04);
  color: var(--ink-2);
  border: 1px solid rgba(var(--ink-rgb), 0.06);
  transition: background-color 0.12s ease;
}
.trend-detail:hover {
  background: rgba(var(--ink-rgb), 0.08);
}
</style>
