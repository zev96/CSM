<script setup lang="ts">
/**
 * Status / label chip. Tone selects the colour scheme.
 *   ok    → green
 *   warn  → yellow
 *   alert → red
 *   info  → ink-3 (default neutral)
 */
type PillTone = "ok" | "warn" | "alert" | "info" | "primary";
defineProps<{ tone?: PillTone }>();
</script>

<template>
  <span
    class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium leading-none"
    :class="[
      tone === 'ok' && 'bg-green/15 text-green',
      tone === 'warn' && 'bg-yellow-soft text-[#a07a18]',
      tone === 'alert' && 'bg-red/15 text-red',
      tone === 'primary' && 'bg-primary-soft text-primary-deep',
      (!tone || tone === 'info') && 'bg-card-2 text-ink-3',
    ]"
    :style="{ borderRadius: 'var(--radius-pill)' }"
  >
    <slot />
  </span>
</template>
