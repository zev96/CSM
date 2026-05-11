<script setup lang="ts">
/**
 * Label + (optional) sub-text + slot for the input. All form atoms
 * compose via this so spacing/typography stays uniform across sections.
 */
defineProps<{
  label?: string;
  hint?: string;
  /** Stack horizontally (label on the left). Default is vertical (label above). */
  inline?: boolean;
}>();
</script>

<template>
  <div :class="inline ? 'flex items-center justify-between gap-4' : 'flex flex-col gap-1.5'">
    <div :class="inline ? 'flex-1 min-w-0' : ''">
      <div v-if="label" class="text-[12.5px] text-ink-2">{{ label }}</div>
      <div v-if="hint" class="mt-0.5 text-[11.5px] text-ink-3 leading-snug">
        {{ hint }}
      </div>
    </div>
    <div :class="inline ? 'flex-shrink-0' : ''">
      <slot />
    </div>
  </div>
</template>
