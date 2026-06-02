<script setup lang="ts">
/**
 * 竞争·信源速览 `HighlightTeasers` —— 移植 design full-app.jsx，紧凑单行：
 * 头号对手(primary-deep) | 分隔线 | 高权重信源(green) | 右侧「查看竞争·信源 →」。
 * 整条可点跳竞争·信源页签。配色/字号严格照稿。无数据时给占位文案。
 */
defineProps<{
  headCompetitor: string;
  topSource: string;
}>();
const emit = defineEmits<{ (e: "compete"): void }>();
</script>

<template>
  <div
    class="geo-row flex items-center cursor-pointer"
    :style="{ gap: '14px', padding: '12px 16px', borderRadius: '14px', background: 'var(--card)', border: '1px solid var(--line)' }"
    @click="emit('compete')"
  >
    <div class="flex items-baseline" :style="{ gap: '7px', flexShrink: 0 }">
      <span :style="{ fontSize: '9.5px', letterSpacing: '0.6px', textTransform: 'uppercase', color: 'var(--ink-3)' }">头号对手</span>
      <span
        class="font-display"
        :style="{ fontSize: '13.5px', fontWeight: 700, color: 'var(--primary-deep)' }"
      >{{ headCompetitor || "暂无" }}</span>
    </div>
    <span :style="{ width: '1px', height: '16px', background: 'var(--line-2)', flexShrink: 0 }" />
    <div class="flex items-baseline" :style="{ gap: '7px', flexShrink: 0 }">
      <span :style="{ fontSize: '9.5px', letterSpacing: '0.6px', textTransform: 'uppercase', color: 'var(--ink-3)' }">高权重信源</span>
      <span
        class="font-display truncate"
        :style="{ fontSize: '13.5px', fontWeight: 700, color: 'var(--green)' }"
      >{{ topSource || "暂无" }}</span>
    </div>
    <span :style="{ marginLeft: 'auto', fontSize: '11px', fontWeight: 600, color: 'var(--primary-deep)', flexShrink: 0 }">查看竞争 · 信源 →</span>
  </div>
</template>
