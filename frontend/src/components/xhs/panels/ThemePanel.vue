<script setup lang="ts">
/**
 * 主题面板（设计稿 §5「主题」/§1 排版主题）。点击应用排版主题，
 * 编辑器工具条随即出现这套主题的小标题/无序/有序/分割线快捷符号。P3 扩到 8 套色系。
 */
import Icon from "@/components/ui/Icon.vue";
import { THEMES } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";
import { orderedMarker } from "@/utils/xhsTheme";

const xhs = useXhs();
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto" :style="{ gap: '10px' }">
    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', flexShrink: 0 }">
      应用后，编辑器顶部工具条会出现这套排版符号的一键插入按钮
    </div>
    <button
      v-for="t in THEMES"
      :key="t.id"
      type="button"
      class="xhs-theme-card"
      :style="{ borderColor: xhs.themeId === t.id ? 'var(--primary)' : 'var(--line-2)' }"
      @click="xhs.applyTheme(t.id)"
    >
      <div class="flex items-center" :style="{ justifyContent: 'space-between', marginBottom: '6px' }">
        <span :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }">{{ t.name }}</span>
        <Icon v-if="xhs.themeId === t.id" name="check" :size="16" :style="{ color: 'var(--primary)' }" />
      </div>
      <div :style="{ fontSize: '13px', color: 'var(--ink)', lineHeight: 1.9 }">
        <div>{{ t.heading }} 小标题示例</div>
        <div>{{ t.bullet }} 无序列表项</div>
        <div>{{ orderedMarker(1, t.ordered) }} 有序列表项</div>
        <div :style="{ color: 'var(--ink-2)' }">{{ t.divider }}</div>
      </div>
    </button>
  </div>
</template>

<style scoped>
.xhs-theme-card {
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 12px;
  padding: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s;
}
.xhs-theme-card:hover {
  border-color: var(--primary);
}
</style>
