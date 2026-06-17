<script setup lang="ts">
/**
 * 素材面板通用「分类标签条」（设计稿 §5 多面板共用）。
 * 受控组件：v-model 绑定当前分类 key；分类自动换行，最多显示三行、超出再竖向滚动；激活项橙色高亮。
 */
defineProps<{ tabs: { key: string; name: string }[]; modelValue: string }>();
defineEmits<{ (e: "update:modelValue", key: string): void }>();
</script>

<template>
  <!-- 换行铺满，最多三行高度（约 96px），超出才出现竖向滚动条 -->
  <div
    class="flex"
    :style="{
      gap: '6px',
      flexWrap: 'wrap',
      alignContent: 'flex-start',
      maxHeight: '96px',
      overflowY: 'auto',
      flexShrink: 0,
      paddingBottom: '2px',
    }"
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
