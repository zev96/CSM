<script setup lang="ts">
/**
 * 素材面板通用「分类标签条」（设计稿 §5 多面板共用）。
 * 受控组件：v-model 绑定当前分类 key；横向可滚动，激活项橙色高亮。
 */
defineProps<{ tabs: { key: string; name: string }[]; modelValue: string }>();
defineEmits<{ (e: "update:modelValue", key: string): void }>();
</script>

<template>
  <div
    class="flex"
    :style="{ gap: '6px', overflowX: 'auto', flexWrap: 'nowrap', flexShrink: 0, paddingBottom: '2px' }"
  >
    <button
      v-for="t in tabs"
      :key="t.key"
      type="button"
      :style="{
        flexShrink: 0,
        fontSize: '12px',
        padding: '5px 12px',
        borderRadius: '999px',
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        border: '1px solid transparent',
        background: modelValue === t.key ? 'var(--primary)' : 'rgba(var(--ink-rgb),0.05)',
        color: modelValue === t.key ? '#fff' : 'var(--ink-2)',
      }"
      @click="$emit('update:modelValue', t.key)"
    >
      {{ t.name }}
    </button>
  </div>
</template>
