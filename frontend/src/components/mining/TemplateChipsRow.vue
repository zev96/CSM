<script setup lang="ts">
/**
 * Top-N starred/recent template chips above the comment textarea.
 *
 * Loads top 5 via templatesStore.listTopChips() on mount.
 * Emits "pick" with the template; parent decides replace/append.
 * Emits "openDrawer" when user clicks "更多 →" button.
 */
import { onMounted, ref } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useTemplatesStore, type Template } from "@/stores/templates"

const props = defineProps<{
  /** Max chip count (excluding "更多" button). Default 2 per user spec —
   *  让 chips + 更多按钮挤在右栏 textarea 顶部的一行内，不换行。 */
  limit?: number
}>()
const emit = defineEmits<{
  (e: "pick", template: Template): void
  (e: "openDrawer"): void
}>()

const store = useTemplatesStore()
const chips = ref<Template[]>([])
const loaded = ref(false)
const total = ref(0)

onMounted(async () => {
  try {
    const { items, total: t } = await store.listTopChips(props.limit ?? 2)
    chips.value = items
    total.value = t
  } catch (e) {
    // Non-critical UI: empty-state copy is the fallback if API fails.
    // Drawer (T11) will surface real errors with toasts.
    console.warn("Failed to load template chips:", e)
  } finally {
    loaded.value = true
  }
})

function truncate(text: string, n = 10): string {
  // Use Array.from to split into grapheme-like units so emoji + ZWJ
  // sequences don't get sliced mid-codepoint (would render as �).
  // 10 字上限按用户要求 —— 长模板在 chip 上只看个大概，完整文本通过
  // title 属性 hover 显示，点击后填进 textarea 才看全。
  const chars = Array.from(text)
  return chars.length > n ? chars.slice(0, n).join("") + "…" : text
}
</script>

<template>
  <div v-if="loaded && (chips.length > 0 || total > 0)" class="chips-row">
    <button
      v-for="tpl in chips"
      :key="tpl.id"
      class="chip"
      :class="{ starred: tpl.starred }"
      :title="tpl.text"
      @click="emit('pick', tpl)"
    >
      <Icon v-if="tpl.starred" name="skills" :size="11" />
      <span>{{ truncate(tpl.text) }}</span>
    </button>
    <button class="chip more" @click="emit('openDrawer')">
      <Icon name="stack" :size="12" />
      <span>更多 ({{ total }})</span>
    </button>
  </div>
  <div v-else-if="loaded && total === 0" class="chips-empty">
    <Icon name="info" :size="12" />
    <span>还没有模板。在设置里"评论模板库"添加，或者发一条评论它会自动入库。</span>
  </div>
</template>

<style scoped>
.chips-row {
  display: flex;
  gap: 6px;
  /* 不允许换行 —— 2 个 chip + 「更多」按钮一定要在同一行
     （按用户要求）。chip 自身 truncate 到 10 字，更多按钮固定宽度，
     右栏 textarea 宽度足够放下三者。 */
  flex-wrap: nowrap;
  margin-bottom: 8px;
}
/*
 * chip 视觉按用户最新要求"不做差异化" —— 回到统一灰色框 + ink 文字色，
 * 跟「更多」按钮长一样（card-2 实底 + 实线边框 + ink-3 文字）。starred
 * 精选态边框颜色保留 accent 做轻量差异，不再换文字色。
 */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--card-2, #fff5dc);
  border: 1px solid var(--line, #e8d6a8);
  border-radius: 12px;
  padding: 3px 9px;
  font-size: 11px;
  color: var(--ink-3, #8a7848);
  max-width: 140px;
  min-width: 0; /* 允许 truncate 在 flex 容器内生效 */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  font-family: inherit;
  flex-shrink: 1; /* 列宽不够时优先压缩 chip，保留「更多」按钮可见 */
}
.chip.more {
  flex-shrink: 0; /* 更多按钮永远完整可见 */
}
.chip:hover {
  background: var(--card-3, #ffe8a3);
}
.chip.starred {
  border-color: var(--accent, #e0a020);
}
.chips-empty {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-4, #9c8a6a);
  margin-bottom: 8px;
  padding: 4px 8px;
}
</style>
