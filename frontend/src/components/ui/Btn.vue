<script setup lang="ts">
/**
 * Pill button. Three styles ported from CSM-RE1 ui.jsx::Btn:
 * - ``solid``  filled with --primary, white text
 * - ``ghost``  transparent, ink text on hover (default secondary)
 * - ``soft``   --primary-soft fill, ink text
 * - ``danger`` red destructive action
 */
type BtnVariant = "solid" | "ghost" | "soft" | "dark" | "danger";
defineProps<{
  variant?: BtnVariant;
  small?: boolean;
  disabled?: boolean;
}>();
</script>

<template>
  <button
    :disabled="disabled"
    class="inline-flex items-center justify-center gap-1.5 font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
    :class="[
      small ? 'px-3 py-1.5 text-[12px]' : 'px-4 py-2 text-[13px]',
      variant === 'solid' && 'bg-primary text-white hover:bg-primary-deep',
      variant === 'soft' && 'bg-primary-soft text-ink hover:brightness-95',
      variant === 'dark' && 'bg-dark text-card hover:bg-dark-2',
      variant === 'danger' && 'bg-red text-white hover:brightness-110',
      (!variant || variant === 'ghost') &&
        'bg-transparent text-ink-2 hover:bg-[rgba(28,26,23,0.05)]',
    ]"
    :style="{ borderRadius: 'var(--radius-pill)' }"
  >
    <slot />
  </button>
</template>
