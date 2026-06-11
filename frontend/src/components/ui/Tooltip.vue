<script setup lang="ts">
/**
 * Hover/focus tooltip — replaces the HTML ``title`` attribute for cases
 * where we want styled, multi-line, brand-consistent hints. ``title``
 * is fine for cheap labels; reach for Tooltip when the hint is long,
 * contains rich text, or needs to read well against the warm-paper UI.
 *
 * Positioning is naïve — fixed-position floating panel anchored to the
 * trigger's bounding rect, no flipping or shifting on overflow. That's
 * enough for icons / buttons in dense toolbars; if you need smart
 * placement, reach for floating-ui directly.
 *
 * Example
 *   &lt;Tooltip content="复制完整路径到剪贴板" placement="bottom"&gt;
 *     &lt;IconBtn name="copy" /&gt;
 *   &lt;/Tooltip&gt;
 */
import { onBeforeUnmount, ref } from "vue";

const props = withDefaults(
  defineProps<{
    content: string;
    placement?: "top" | "bottom" | "left" | "right";
    /** Show delay in ms. Default 150 — feels intentional, not flickery. */
    delay?: number;
  }>(),
  { placement: "top", delay: 150 },
);

const show = ref(false);
const triggerEl = ref<HTMLElement | null>(null);
const pos = ref<{ top: number; left: number } | null>(null);
let showTimer: number | null = null;

const ARROW_GAP = 8; // px between trigger edge and tooltip

function computePos() {
  if (!triggerEl.value) return;
  const r = triggerEl.value.getBoundingClientRect();
  // Approximate width/height before the panel mounts; CSS clamps it
  // anyway. These don't have to be exact — they only feed the initial
  // top/left; transform handles fine alignment.
  switch (props.placement) {
    case "bottom":
      pos.value = { top: r.bottom + ARROW_GAP, left: r.left + r.width / 2 };
      break;
    case "left":
      pos.value = { top: r.top + r.height / 2, left: r.left - ARROW_GAP };
      break;
    case "right":
      pos.value = { top: r.top + r.height / 2, left: r.right + ARROW_GAP };
      break;
    default:
      pos.value = { top: r.top - ARROW_GAP, left: r.left + r.width / 2 };
  }
}

function onEnter() {
  if (showTimer !== null) window.clearTimeout(showTimer);
  showTimer = window.setTimeout(() => {
    computePos();
    show.value = true;
  }, props.delay);
}

function onLeave() {
  if (showTimer !== null) {
    window.clearTimeout(showTimer);
    showTimer = null;
  }
  show.value = false;
}

onBeforeUnmount(() => {
  if (showTimer !== null) window.clearTimeout(showTimer);
});

const transformByPlacement: Record<string, string> = {
  top: "translate(-50%, -100%)",
  bottom: "translate(-50%, 0)",
  left: "translate(-100%, -50%)",
  right: "translate(0, -50%)",
};
</script>

<template>
  <span
    ref="triggerEl"
    class="inline-flex"
    @mouseenter="onEnter"
    @mouseleave="onLeave"
    @focusin="onEnter"
    @focusout="onLeave"
  >
    <slot />
  </span>

  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="show && pos"
        role="tooltip"
        class="pointer-events-none"
        :style="{
          position: 'fixed',
          top: `${pos.top}px`,
          left: `${pos.left}px`,
          transform: transformByPlacement[placement],
          background: 'var(--dark)',
          color: 'var(--card)',
          fontSize: '11.5px',
          lineHeight: 1.45,
          padding: '6px 10px',
          borderRadius: '6px',
          maxWidth: '240px',
          whiteSpace: 'pre-wrap',
          boxShadow: '0 8px 24px rgba(0,0,0,0.24)',
          zIndex: 70,
        }"
      >{{ content }}</div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.14s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
