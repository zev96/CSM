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
  /** Dark hero treatment — used by OutreachHero. */
  dark?: boolean;
}>();
</script>

<template>
  <section
    class="transition-colors"
    :class="[
      dark
        ? 'bg-dark text-card border-transparent'
        : muted
          ? 'bg-card-2 border-line'
          : 'bg-card border-line',
      padless ? '' : 'pad-d',
      !dark && 'border',
    ]"
    :style="{ borderRadius: 'var(--radius-card)' }"
  >
    <slot />
  </section>
</template>
