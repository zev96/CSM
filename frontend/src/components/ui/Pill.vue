<script setup lang="ts">
/**
 * Status / label chip. Tone selects the colour scheme.
 *   ok    → green        warn → yellow      alert → red
 *   primary → primary    info → neutral（默认）
 * Variants 用 class-variance-authority，与 Btn.vue 同范式。
 */
import { cva, type VariantProps } from "class-variance-authority";

const pillVariants = cva(
  "inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium leading-none",
  {
    variants: {
      tone: {
        ok: "bg-green-soft text-green-deep",
        warn: "bg-yellow-soft text-yellow-deep",
        alert: "bg-red-soft text-red-deep",
        primary: "bg-primary-soft text-primary-deep",
        info: "bg-card-2 text-ink-3",
      },
    },
    defaultVariants: { tone: "info" },
  },
);

type PillTone = NonNullable<VariantProps<typeof pillVariants>["tone"]>;
defineProps<{ tone?: PillTone }>();
</script>

<template>
  <span :class="pillVariants({ tone })" :style="{ borderRadius: 'var(--radius-pill)' }">
    <slot />
  </span>
</template>
