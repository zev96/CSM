<script setup lang="ts">
/**
 * Stacked bar chart for "本周字数" — one bar per day, two-tone fill
 * (words drafted + polished). Polished is rendered as a shorter inset
 * bar on top of the words bar, tinted with --primary.
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    items: Array<{ label: string; words: number; polished?: number }>;
    height?: number;
  }>(),
  { height: 80 },
);

const max = computed(() =>
  Math.max(1, ...props.items.map((i) => Math.max(i.words, i.polished ?? 0))),
);
</script>

<template>
  <div class="flex items-end gap-1.5" :style="{ height: `${height}px` }">
    <div
      v-for="(it, i) in items"
      :key="i"
      class="relative flex flex-1 flex-col items-center justify-end"
    >
      <div
        class="w-full rounded-t-sm bg-line-2"
        :style="{ height: `${(it.words / max) * 100}%` }"
      >
        <div
          class="w-full rounded-t-sm"
          :style="{
            height: `${((it.polished ?? 0) / Math.max(1, it.words)) * 100}%`,
            background: 'var(--primary)',
          }"
        />
      </div>
      <span class="mt-1 text-[10px] text-ink-3">{{ it.label }}</span>
    </div>
  </div>
</template>
