<script setup lang="ts">
import { useToast } from "@/composables/useToast";

import Icon from "./Icon.vue";

const { toasts, dismiss } = useToast();

const TONES: Record<string, { bg: string; fg: string; icon: string }> = {
  info:    { bg: "var(--dark)",         fg: "#fbf7ec",      icon: "wand" },
  success: { bg: "#3f6b48",             fg: "#eaf5ec",      icon: "check" },
  warn:    { bg: "var(--yellow)",       fg: "#3f3315",      icon: "wand" },
  error:   { bg: "var(--red)",          fg: "#fff",         icon: "x" },
};
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
          boxShadow: '0 12px 30px -10px rgba(28,26,23,0.4)',
        }"
        role="status"
        @click="dismiss(t.id)"
      >
        <Icon :name="TONES[t.tone].icon" :size="14" />
        <span>{{ t.message }}</span>
      </div>
    </div>
  </Teleport>
</template>
