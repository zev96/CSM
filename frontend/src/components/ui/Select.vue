<script setup lang="ts" generic="T extends string | number">
/**
 * Styled select primitive — wraps the native &lt;select&gt; so we keep OS
 * a11y / keyboard nav for free, but the chrome matches the warm-paper
 * card aesthetic instead of the browser default.
 *
 * Targets the 21 bare ``&lt;select&gt;`` sites flagged in the v0.5.2 audit.
 * FormSelect remains the form-layout wrapper (label + helper text); use
 * Select when you just need the control, e.g. inside toolbars / chips.
 *
 * Generic over the option value type — ``Select&lt;number&gt;`` works just
 * as well as ``Select&lt;string&gt;``.
 *
 * Example
 *   &lt;Select
 *     v-model="month"
 *     :options="[{ value: 'jan', label: '一月' }, ...]"
 *   /&gt;
 */
import { computed } from "vue";

import Icon from "./Icon.vue";

interface SelectOption<V> {
  value: V;
  label: string;
  disabled?: boolean;
}

const props = withDefaults(
  defineProps<{
    modelValue: T | null;
    options: SelectOption<T>[];
    placeholder?: string;
    disabled?: boolean;
    /** sm: 28px height / md: 32px (default) / lg: 36px */
    size?: "sm" | "md" | "lg";
    /** 下拉最小宽度，默认 120px；窄容器（如评论页左栏工具栏）传更小值防溢出 */
    minWidth?: string;
  }>(),
  { size: "md", placeholder: "", minWidth: "120px" },
);

const emit = defineEmits<{
  (e: "update:modelValue", v: T): void;
}>();

const HEIGHTS = { sm: "28px", md: "32px", lg: "36px" } as const;

const stringValue = computed(() =>
  props.modelValue === null || props.modelValue === undefined
    ? ""
    : String(props.modelValue),
);

function onChange(e: Event) {
  const raw = (e.target as HTMLSelectElement).value;
  // Map back to the original option value (preserves number vs string).
  const opt = props.options.find((o) => String(o.value) === raw);
  if (opt) emit("update:modelValue", opt.value);
}
</script>

<template>
  <div
    class="relative inline-flex items-center"
    :style="{ height: HEIGHTS[size], opacity: disabled ? 0.55 : 1 }"
  >
    <select
      :value="stringValue"
      :disabled="disabled"
      class="appearance-none outline-none"
      :style="{
        height: '100%',
        padding: '0 28px 0 12px',
        borderRadius: '8px',
        background: 'var(--card)',
        border: '1px solid var(--line)',
        color: 'var(--ink)',
        fontSize: '12.5px',
        fontFamily: 'inherit',
        cursor: disabled ? 'not-allowed' : 'pointer',
        minWidth: props.minWidth,
      }"
      @change="onChange"
    >
      <option v-if="placeholder" value="" disabled :selected="modelValue == null">
        {{ placeholder }}
      </option>
      <option
        v-for="opt in options"
        :key="String(opt.value)"
        :value="String(opt.value)"
        :disabled="opt.disabled"
      >
        {{ opt.label }}
      </option>
    </select>
    <Icon
      name="arrowDown"
      :size="12"
      class="pointer-events-none absolute"
      :style="{ right: '10px', color: 'var(--ink-3)' }"
    />
  </div>
</template>
