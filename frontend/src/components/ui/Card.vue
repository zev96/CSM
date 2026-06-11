<script setup lang="ts">
/**
 * Base card surface。Variants 用 cva（与 Btn.vue 同范式）：
 *   surface: default(纸面) / muted(深一档) / dark(暗底亮字, 无边框)
 *   padding: default(--density-pad) / none(自定义布局)
 * 公开 prop 不变：muted / padless / dark。
 */
import { cva } from "class-variance-authority";

const cardVariants = cva("transition-colors", {
  variants: {
    surface: {
      default: "bg-card border border-line",
      muted: "bg-card-2 border border-line",
      dark: "bg-dark text-card",
    },
    padding: { default: "pad-d", none: "" },
  },
  defaultVariants: { surface: "default", padding: "default" },
});

defineProps<{ muted?: boolean; padless?: boolean; dark?: boolean }>();
</script>

<template>
  <section
    :class="cardVariants({ surface: dark ? 'dark' : muted ? 'muted' : 'default', padding: padless ? 'none' : 'default' })"
    :style="{ borderRadius: 'var(--radius-card)' }"
  >
    <slot />
  </section>
</template>
