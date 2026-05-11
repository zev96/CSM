<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: number;
    min?: number;
    max?: number;
    step?: number;
    suffix?: string;
  }>(),
  { min: 0, max: 100, step: 1 },
);

const emit = defineEmits<{
  (e: "update:modelValue", v: number): void;
  (e: "commit", v: number): void;
}>();

function onInput(e: Event) {
  emit("update:modelValue", Number((e.target as HTMLInputElement).value));
}
function onChange(e: Event) {
  emit("commit", Number((e.target as HTMLInputElement).value));
}
</script>

<template>
  <div class="flex items-center gap-3" :style="{ minWidth: '220px' }">
    <input
      type="range"
      :min="min"
      :max="max"
      :step="step"
      :value="modelValue"
      class="flex-1 accent-primary"
      @input="onInput"
      @change="onChange"
    />
    <span class="font-mono shrink-0 text-[12px] text-ink-2 tabular-nums">
      {{ modelValue }}{{ suffix ?? "" }}
    </span>
  </div>
</template>
