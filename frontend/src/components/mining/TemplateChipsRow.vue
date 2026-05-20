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
  /** Max chip count (excluding "更多" button). Default 5. */
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
    const items = await store.listTopChips(props.limit ?? 5)
    chips.value = items
    // Quick total fetch — we need the "更多 (N)" badge
    await store.list({ limit: 1, offset: 0 })
    total.value = store.total
  } finally {
    loaded.value = true
  }
})

function truncate(text: string, n = 12): string {
  return text.length > n ? text.slice(0, n) + "…" : text
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
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--card-2, #fff5dc);
  border: 1px solid var(--line, #e8d6a8);
  border-radius: 12px;
  padding: 3px 9px;
  font-size: 11px;
  color: var(--ink, #6a5520);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  font-family: inherit;
}
.chip:hover {
  background: var(--card-3, #ffe8a3);
}
.chip.starred {
  border-color: var(--accent, #e0a020);
}
.chip.more {
  background: transparent;
  border-style: dashed;
  color: var(--ink-3, #8a7848);
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
