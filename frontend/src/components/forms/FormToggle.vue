<script setup lang="ts">
defineProps<{ modelValue: boolean; disabled?: boolean }>();
defineEmits<{ (e: "update:modelValue", v: boolean): void }>();
</script>

<template>
  <button
    type="button"
    :disabled="disabled"
    class="relative inline-flex shrink-0 items-center transition disabled:opacity-50"
    :style="{
      width: '38px',
      height: '22px',
      borderRadius: '999px',
      background: modelValue ? 'var(--primary)' : 'var(--line-2)',
    }"
    @click="$emit('update:modelValue', !modelValue)"
  >
    <span
      class="absolute bg-white shadow-sm transition-transform"
      :style="{
        width: '16px',
        height: '16px',
        borderRadius: '50%',
        top: '3px',
        left: '3px',
        transform: modelValue ? 'translateX(16px)' : 'translateX(0)',
      }"
    />
  </button>
</template>
