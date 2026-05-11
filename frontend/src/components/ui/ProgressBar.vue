<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    /** 0–1 ratio. Pass null for indeterminate (shimmer). */
    value: number | null;
    height?: number;
    tone?: "primary" | "ink" | "green" | "red";
  }>(),
  { height: 6, tone: "primary" },
);

const fillColor = computed(() => {
  switch (props.tone) {
    case "green":
      return "var(--green)";
    case "red":
      return "var(--red)";
    case "ink":
      return "var(--ink-2)";
    default:
      return "var(--primary)";
  }
});

const widthPct = computed(() => {
  if (props.value == null) return "100%";
  const v = Math.max(0, Math.min(1, props.value));
  return `${(v * 100).toFixed(1)}%`;
});
</script>

<template>
  <div
    class="overflow-hidden"
    :style="{
      width: '100%',
      height: `${height}px`,
      borderRadius: '999px',
      background: 'var(--card-2)',
    }"
  >
    <div
      class="h-full transition-[width] duration-300 ease-out"
      :class="{ 'progress-indeterminate': value == null }"
      :style="{
        width: widthPct,
        background: fillColor,
        borderRadius: '999px',
      }"
    />
  </div>
</template>

<style scoped>
@keyframes progressIndet {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}
.progress-indeterminate {
  animation: progressIndet 1.4s ease-in-out infinite;
}
</style>
