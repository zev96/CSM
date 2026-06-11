<script setup lang="ts">
import { useToast, type Toast } from "@/composables/useToast";

import Icon from "./Icon.vue";

const { toasts, dismiss } = useToast();

const TONES: Record<string, { bg: string; fg: string; icon: string }> = {
  info:    { bg: "var(--dark)",         fg: "#fbf7ec",      icon: "wand" },
  success: { bg: "#3f6b48",             fg: "#eaf5ec",      icon: "check" },
  warn:    { bg: "var(--yellow)",       fg: "#3f3315",      icon: "wand" },
  error:   { bg: "var(--red)",          fg: "#fff",         icon: "x" },
};

function onAction(t: Toast, ev: Event) {
  // Stop the click bubbling up to the pill (which would dismiss via the
  // outer @click) BEFORE we trigger the action, so the dismiss + action
  // both still fire — but we want to control the order: action first,
  // then dismiss, so callers can e.g. navigate before the toast disappears.
  ev.stopPropagation();
  try {
    t.onAction?.();
  } finally {
    dismiss(t.id);
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      class="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex flex-col items-center gap-2 px-4"
    >
      <div
        v-for="t in toasts"
        :key="t.id"
        class="anim-up pointer-events-auto inline-flex max-w-[560px] items-center gap-2.5 px-4 py-2 text-[12.5px] shadow-lg"
        :style="{
          background: TONES[t.tone].bg,
          color: TONES[t.tone].fg,
          borderRadius: '999px',
          boxShadow: '0 12px 30px -10px rgba(var(--ink-rgb),0.4)',
        }"
        role="status"
        @click="dismiss(t.id)"
      >
        <Icon :name="TONES[t.tone].icon" :size="14" />
        <span>{{ t.message }}</span>
        <button
          v-if="t.actionLabel"
          type="button"
          class="ml-1 inline-flex items-center font-semibold transition"
          :style="{
            height: '22px',
            padding: '0 10px',
            borderRadius: '999px',
            fontSize: '11.5px',
            background: 'rgba(255,255,255,0.18)',
            color: TONES[t.tone].fg,
            border: '1px solid rgba(255,255,255,0.28)',
          }"
          @click="onAction(t, $event)"
        >{{ t.actionLabel }}</button>
      </div>
    </div>
  </Teleport>
</template>
