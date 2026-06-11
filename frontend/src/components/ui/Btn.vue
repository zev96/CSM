<script setup lang="ts">
/**
 * Pill button. Five variants ported from CSM-RE1 ui.jsx::Btn, now
 * driven by `class-variance-authority` so the variant × size matrix
 * lives in one declarative table instead of a `:class` ternary chain.
 *
 *   - solid   filled with --primary, white text
 *   - ghost   transparent, ink text on hover (default — picked when
 *             `variant` is omitted)
 *   - soft    --primary-soft fill, ink text
 *   - dark    --dark fill, card text (used by BatchImportTaskModal
 *             submit + a couple of other "weighty" actions)
 *   - danger  red destructive action
 *
 * Public API unchanged from the hand-rolled version:
 *   <Btn variant="solid" small>提交</Btn>
 *
 * The `small` prop is kept as a convenience flag because every caller
 * in the codebase already uses it; internally it maps to the cva
 * `size: "small"` variant.
 */
import { cva, type VariantProps } from "class-variance-authority";

const btnVariants = cva(
  "inline-flex items-center justify-center gap-1.5 font-medium transition disabled:opacity-50 disabled:cursor-not-allowed",
  {
    variants: {
      variant: {
        solid: "bg-primary text-white hover:bg-primary-deep",
        ghost: "bg-transparent text-ink-2 hover:bg-[rgba(var(--ink-rgb),0.05)]",
        soft: "bg-primary-soft text-ink hover:brightness-95",
        dark: "bg-dark text-card hover:bg-dark-2",
        danger: "bg-red text-white hover:brightness-110",
      },
      size: {
        default: "px-4 py-2 text-[13px]",
        small: "px-3 py-1.5 text-[12px]",
      },
    },
    defaultVariants: {
      variant: "ghost",
      size: "default",
    },
  },
);

type BtnVariant = NonNullable<VariantProps<typeof btnVariants>["variant"]>;

defineProps<{
  variant?: BtnVariant;
  /** Convenience flag — equivalent to selecting the "small" size. */
  small?: boolean;
  disabled?: boolean;
}>();
</script>

<template>
  <button
    :disabled="disabled"
    :class="btnVariants({ variant: variant ?? 'ghost', size: small ? 'small' : 'default' })"
    :style="{ borderRadius: 'var(--radius-pill)' }"
  >
    <slot />
  </button>
</template>
