<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    modelValue: string | number | null | undefined;
    placeholder?: string;
    type?: "text" | "password" | "number";
    /** Save on blur instead of every keystroke — for fields that hit the API. */
    debounce?: "blur" | "live";
    disabled?: boolean;
    width?: string | number;
  }>(),
  { type: "text", debounce: "blur" },
);

const emit = defineEmits<{
  (e: "update:modelValue", v: string | number | null): void;
  (e: "commit", v: string | number | null): void;
}>();

const proxy = computed({
  get: () => (props.modelValue == null ? "" : String(props.modelValue)),
  set: (v) => emit("update:modelValue", coerce(v)),
});

function coerce(v: string): string | number | null {
  if (props.type === "number") {
    if (v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return v;
}

function onBlur() {
  if (props.debounce === "blur") emit("commit", coerce(proxy.value));
}
function onChange() {
  if (props.debounce === "live") emit("commit", coerce(proxy.value));
}
</script>

<template>
  <input
    v-model="proxy"
    :type="type"
    :placeholder="placeholder"
    :disabled="disabled"
    class="bg-card-2 px-3 py-2 text-[13px] outline-none transition-colors focus:bg-card-white"
    :style="{
      borderRadius: 'var(--radius-inner)',
      border: '1px solid var(--line)',
      width: typeof width === 'number' ? `${width}px` : width || '100%',
    }"
    @blur="onBlur"
    @input="onChange"
  />
</template>
