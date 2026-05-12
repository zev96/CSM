<script setup lang="ts">
/**
 * 多选下拉 — 用于 BlockEditor 段落筛选的 value 字段。
 *
 *   - options 非空 → 渲染勾选下拉，多选行为复用 link 下拉那套 cream + dark hover；
 *   - options 空 → 回退为 free-text input（适用于 value_count > 20 的 key，或还没扫
 *     vault 时的兜底）。
 *
 * 对外契约：value 是逗号 / 中文逗号 / 顿号 分隔的字符串（与现有 commitFilters 兼容）。
 * 内部展开成数组维护勾选态。
 */
import { computed, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: string[];
    placeholder?: string;
    /** Force free-text mode even if options.length > 0. Used for low-cardinality but
     * still typing-friendly keys when caller wants to bypass the dropdown. */
    allowFreeText?: boolean;
  }>(),
  { placeholder: "如：引言乱象", allowFreeText: false },
);

const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

const useDropdown = computed(() => props.options.length > 0 && !props.allowFreeText);

function parseSelected(s: string): string[] {
  return (s ?? "")
    .split(/[,，、]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

const selected = computed<string[]>(() => parseSelected(props.modelValue));

function commit(arr: string[]) {
  emit("update:modelValue", arr.join(", "));
}

function toggle(v: string) {
  const set = new Set(selected.value);
  if (set.has(v)) set.delete(v);
  else set.add(v);
  commit([...set]);
}

const open = ref(false);

const buttonText = computed(() => {
  if (selected.value.length === 0) return props.placeholder;
  const joined = selected.value.join("、");
  return joined.length > 24 ? joined.slice(0, 22) + "…" : joined;
});
</script>

<template>
  <!-- Dropdown path -->
  <div v-if="useDropdown" class="relative" :style="{ minWidth: '0' }">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-2 px-3 py-2 text-[12.5px]"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-inner)',
        color: selected.length ? 'var(--ink)' : 'var(--ink-3)',
      }"
      @click="open = !open"
    >
      <span class="truncate text-left">{{ buttonText }}</span>
      <Icon name="arrowDown" :size="12" />
    </button>
    <div
      v-if="open"
      class="absolute z-10 mt-1 max-h-[240px] w-full overflow-y-auto p-1.5"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-inner)',
        boxShadow: '0 6px 18px rgba(28,26,23,0.10)',
      }"
      @click.stop
    >
      <button
        v-for="opt in options"
        :key="opt"
        type="button"
        class="mvp-row flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left text-[12.5px]"
        :style="{
          borderRadius: '6px',
          background: selected.includes(opt) ? 'var(--primary-soft)' : 'transparent',
          color: selected.includes(opt) ? 'var(--primary-deep)' : 'var(--ink)',
        }"
        @click="toggle(opt)"
      >
        <span class="flex-1 truncate">{{ opt }}</span>
        <Icon
          v-if="selected.includes(opt)"
          name="check"
          :size="11"
          :style="{ color: 'var(--primary-deep)' }"
        />
      </button>
      <div class="flex justify-end pt-1">
        <button
          type="button"
          class="px-2 py-1 text-[11px]"
          :style="{ color: 'var(--ink-3)' }"
          @click="open = false"
        >
          完成
        </button>
      </div>
    </div>
  </div>

  <!-- Free-text fallback path -->
  <input
    v-else
    :value="modelValue"
    :placeholder="placeholder"
    class="bg-card-2 w-full px-3 py-2 text-[12.5px] outline-none"
    :style="{
      borderRadius: 'var(--radius-inner)',
      border: '1px solid var(--line)',
      minWidth: '0',
    }"
    @blur="(e) => emit('update:modelValue', (e.target as HTMLInputElement).value)"
  />
</template>

<style scoped>
.mvp-row:hover {
  background: var(--dark) !important;
  color: #fbf7ec !important;
}
.mvp-row:hover :deep(svg) {
  color: #fbf7ec !important;
}
</style>
