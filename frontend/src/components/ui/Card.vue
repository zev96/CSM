<script setup lang="ts">
/**
 * Base card surface — paper-coloured background, soft shadow, density
 * padding driven by --density-pad. Mirrors the ``Card`` primitive in
 * CSM-RE1（V1）/src/ui.jsx.
 */
defineProps<{
  /** Use the deeper ``--card-2`` shade (for nested or "muted" cards). */
  muted?: boolean;
  /** Drop the inner padding — for cards that want their own layout. */
  padless?: boolean;
}>();
</script>

<template>
  <section
    class="border border-line transition-colors"
    :class="[
      muted ? 'bg-card-2' : 'bg-card',
      padless ? '' : 'pad-d',
    ]"
    :style="{ borderRadius: 'var(--radius-card)' }"
  >
    <slot />
  </section>
</template>
