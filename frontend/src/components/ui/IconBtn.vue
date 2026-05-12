<script setup lang="ts">
import Icon from "./Icon.vue";

defineProps<{
  name: string;
  badge?: boolean;
  title?: string;
}>();
</script>

<template>
  <button
    :title="title"
    class="relative inline-flex items-center justify-center transition hover:bg-[rgba(28,26,23,0.05)]"
    :style="{
      width: '36px',
      height: '36px',
      borderRadius: 'var(--radius-pill)',
      color: 'var(--ink-2)',
    }"
  >
    <Icon :name="name" :size="16" />
    <span
      v-if="badge"
      class="absolute"
      :style="{
        top: '8px',
        right: '8px',
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: 'var(--red)',
        boxShadow: '0 0 0 2px var(--bg-inner)',
      }"
    />
  </button>
</template>
