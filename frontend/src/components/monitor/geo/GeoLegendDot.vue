<script setup lang="ts">
/**
 * 散点图下方图例小点 `LegendDot` —— 移植 design full-app.jsx。
 * ring=true 时点外再描半透明同色环（你/榜首带环），否则实心。配色/尺寸照稿。
 */
defineProps<{
  color: string;
  ring?: boolean;
  label: string;
}>();
</script>

<template>
  <span class="inline-flex items-center" :style="{ gap: '5px', fontSize: '10.5px', color: 'var(--ink-2)' }">
    <span
      class="relative inline-flex items-center justify-center"
      :style="{ width: '11px', height: '11px' }"
    >
      <span
        v-if="ring"
        :style="{ position: 'absolute', width: '11px', height: '11px', borderRadius: '999px', border: `1.5px solid ${color}`, opacity: 0.35 }"
      />
      <span
        :style="{
          width: ring ? '7px' : '8px',
          height: ring ? '7px' : '8px',
          borderRadius: '999px',
          background: color,
          border: ring ? '1.5px solid #fff' : 'none',
          boxShadow: ring ? `0 0 0 1px ${color}` : 'none',
        }"
      />
    </span>
    {{ label }}
  </span>
</template>
