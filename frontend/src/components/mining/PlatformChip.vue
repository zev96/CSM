<script setup lang="ts">
import type { Platform } from "@/stores/mining";

const props = withDefaults(
  defineProps<{ k: Platform; size?: "sm" | "md" }>(),
  { size: "sm" },
);

const META: Record<Platform, { l: string; letter: string; color: string; dark: string }> = {
  bilibili: { l: "B 站", letter: "B", color: "#fb7299", dark: "#a13a5e" },
  douyin: { l: "抖音", letter: "D", color: "#1c1a17", dark: "#1c1a17" },
  kuaishou: { l: "快手", letter: "K", color: "#ff6633", dark: "#a13d1f" },
};

const m = () => META[props.k];
const h = () => (props.size === "sm" ? 22 : 26);
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 font-medium"
    :style="{
      height: h() + 'px',
      padding: '0 9px',
      borderRadius: '999px',
      background: 'rgba(255,255,255,0.92)',
      color: m().dark,
      fontSize: size === 'sm' ? '11px' : '12px',
      boxShadow: '0 1px 2px rgba(var(--ink-rgb),0.08)',
      border: '1px solid rgba(var(--ink-rgb),0.04)',
    }"
  >
    <span
      :style="{
        width: '14px', height: '14px', borderRadius: '4px',
        background: m().color, color: '#fff',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        fontSize: '9px', fontWeight: 800,
      }"
    >{{ m().letter }}</span>
    {{ m().l }}
  </span>
</template>
