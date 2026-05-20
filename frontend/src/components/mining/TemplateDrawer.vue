<script setup lang="ts">
/**
 * Right-side slide-out drawer for browsing the full template library.
 *
 * Features:
 *   - Search by text (debounced)
 *   - Multi-select tag filter (intersection)
 *   - List with inline actions: pick / star / hide / edit
 *   - Keyboard: ↑↓ select, Enter pick, Esc close
 *   - No hard delete + no bulk import (those live in settings)
 */
import { onMounted, onUnmounted, ref, watch } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useTemplatesStore, type Template } from "@/stores/templates"

const emit = defineEmits<{
  (e: "close"): void
  (e: "pick", tpl: Template): void
}>()

const store = useTemplatesStore()
const search = ref("")
const selectedTags = ref<string[]>([])
const editingId = ref<number | null>(null)
const editText = ref("")
const activeIndex = ref(0)

let searchTimer: number | undefined

watch([search, selectedTags], () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refresh, 200)
})

async function refresh() {
  await store.list({
    search: search.value || undefined,
    tags: selectedTags.value.length ? selectedTags.value : undefined,
  })
  activeIndex.value = 0
}

function toggleTag(tag: string) {
  const i = selectedTags.value.indexOf(tag)
  if (i >= 0) selectedTags.value.splice(i, 1)
  else selectedTags.value.push(tag)
}

function pick(tpl: Template) {
  emit("pick", tpl)
}

async function toggleStar(tpl: Template) {
  await store.update(tpl.id, { starred: !tpl.starred })
}

async function hide(tpl: Template) {
  await store.update(tpl.id, { hidden: true })
  store.items = store.items.filter(t => t.id !== tpl.id)
}

function startEdit(tpl: Template) {
  editingId.value = tpl.id
  editText.value = tpl.text
}

async function saveEdit(tpl: Template) {
  if (editText.value.trim() && editText.value !== tpl.text) {
    await store.update(tpl.id, { text: editText.value })
  }
  editingId.value = null
}

function cancelEdit() {
  editingId.value = null
}

function onKeydown(e: KeyboardEvent) {
  // Esc: cancel inline edit first; only close drawer when not editing.
  if (e.key === "Escape") {
    if (editingId.value !== null) {
      cancelEdit()
    } else {
      emit("close")
    }
    return
  }
  // Arrow keys / Enter only navigate list when NOT inline-editing —
  // otherwise the cursor in the edit textarea can't move and Enter
  // wouldn't be able to insert newlines.
  if (editingId.value !== null) return

  if (e.key === "ArrowDown") {
    activeIndex.value = Math.min(activeIndex.value + 1, store.items.length - 1)
    e.preventDefault()
  } else if (e.key === "ArrowUp") {
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
    e.preventDefault()
  } else if (e.key === "Enter") {
    const tpl = store.items[activeIndex.value]
    if (tpl) pick(tpl)
    e.preventDefault()
  }
}

onMounted(async () => {
  document.addEventListener("keydown", onKeydown)
  await store.loadAllTags()
  await refresh()
})
onUnmounted(() => {
  document.removeEventListener("keydown", onKeydown)
  // If a search debounce is pending, kill it so it doesn't fire
  // post-unmount and clobber another component's list call.
  if (searchTimer) window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="drawer-overlay" @click.self="emit('close')">
    <aside class="drawer" role="dialog" aria-label="模板库">
      <header class="drawer-header">
        <div class="drawer-title">
          <Icon name="stack" :size="16" />
          <span>模板库</span>
        </div>
        <button class="drawer-close" @click="emit('close')">
          <Icon name="x" :size="14" />
        </button>
      </header>

      <div class="drawer-search">
        <Icon name="search" :size="13" class="search-icon" />
        <input v-model="search" placeholder="搜索文本或标签…" />
      </div>

      <div v-if="store.allTags.length" class="drawer-tags">
        <Icon name="tag" :size="11" />
        <button
          v-for="t in store.allTags"
          :key="t"
          class="tag-chip"
          :class="{ active: selectedTags.includes(t) }"
          @click="toggleTag(t)"
        >{{ t }}</button>
      </div>

      <div v-if="store.loading" class="drawer-loading">加载中…</div>
      <div v-else-if="store.items.length === 0" class="drawer-empty">
        没找到匹配的模板
      </div>
      <ul v-else class="drawer-list">
        <li
          v-for="(tpl, i) in store.items"
          :key="tpl.id"
          class="drawer-item"
          :class="{ active: i === activeIndex }"
        >
          <div v-if="editingId === tpl.id" class="edit-mode">
            <textarea v-model="editText" rows="3" />
            <div class="edit-actions">
              <button @click="saveEdit(tpl)">保存</button>
              <button @click="cancelEdit">取消</button>
            </div>
          </div>
          <template v-else>
            <div class="item-text">{{ tpl.text }}</div>
            <div class="item-meta">
              <span v-for="t in tpl.tags" :key="t" class="meta-tag">#{{ t }}</span>
              <span v-if="tpl.source_platform">· {{ tpl.source_platform }}</span>
              <span>· 用过 {{ tpl.use_count }} 次</span>
            </div>
            <div class="item-actions">
              <button class="primary" @click="pick(tpl)">填入</button>
              <button @click="toggleStar(tpl)" :title="tpl.starred ? '取消精选' : '标精选'">
                <Icon name="skills" :size="12" />
              </button>
              <button @click="startEdit(tpl)" title="编辑">
                <Icon name="edit" :size="12" />
              </button>
              <button @click="hide(tpl)" title="隐藏">
                <Icon name="eye" :size="12" />
              </button>
            </div>
          </template>
        </li>
      </ul>
    </aside>
  </div>
</template>

<style scoped>
.drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.15);
  z-index: 90;
}
.drawer {
  position: fixed; right: 0; top: 0; bottom: 0;
  width: 420px;
  background: var(--card, #fffaef);
  border-left: 1px solid var(--line, #d4c8a8);
  display: flex;
  flex-direction: column;
  box-shadow: -8px 0 20px rgba(0,0,0,0.08);
  animation: slide-in 180ms ease-out;
}
@keyframes slide-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; border-bottom: 1px solid var(--line, #e8dcc0);
}
.drawer-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.drawer-close { background: transparent; border: none; cursor: pointer; padding: 4px; }
.drawer-search {
  position: relative; padding: 10px 16px;
}
.drawer-search input {
  width: 100%; padding: 6px 10px 6px 28px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  background: var(--card-input, #fff); font-size: 12px;
}
.search-icon { position: absolute; left: 24px; top: 50%; transform: translateY(-50%); color: var(--ink-4, #9c8a6a); }
.drawer-tags {
  display: flex; gap: 4px; flex-wrap: wrap; align-items: center;
  padding: 0 16px 8px;
}
.tag-chip {
  background: var(--card-2, #fff5dc); border: 1px solid var(--line, #e8d6a8);
  border-radius: 10px; padding: 2px 8px; font-size: 10px; cursor: pointer;
  color: var(--ink, #6a5520); font-family: inherit;
}
.tag-chip.active { background: var(--accent, #e0a020); color: #fff; border-color: var(--accent, #e0a020); }
.drawer-list { flex: 1; overflow-y: auto; margin: 0; padding: 0; list-style: none; }
.drawer-item {
  padding: 10px 16px; border-bottom: 1px solid var(--line-light, #ece0c2);
}
.drawer-item.active { background: var(--card-hover, #fff5dc); }
.item-text {
  font-size: 12px; color: var(--ink, #2a2017);
  line-height: 1.4;
  max-height: 60px; overflow: hidden;
}
.item-meta { font-size: 10px; color: var(--ink-4, #9c8a6a); margin-top: 4px; }
.meta-tag {
  background: var(--card-2, #fff5dc); padding: 1px 5px; border-radius: 6px;
  color: var(--ink, #6a5520); margin-right: 3px;
}
.item-actions { display: flex; gap: 4px; margin-top: 6px; }
.item-actions button {
  padding: 3px 8px; font-size: 10px; border-radius: 4px;
  border: 1px solid var(--line, #ece0c2); background: var(--card-2, #faf3df);
  color: var(--ink, #6b5a3a); cursor: pointer; font-family: inherit;
}
.item-actions button.primary {
  background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017);
}
.drawer-loading, .drawer-empty {
  padding: 30px; text-align: center; color: var(--ink-4, #9c8a6a); font-size: 12px;
}
.edit-mode textarea {
  width: 100%; min-height: 60px; padding: 6px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 4px;
  font-family: inherit; font-size: 12px;
}
.edit-actions { display: flex; gap: 6px; margin-top: 6px; }
.edit-actions button {
  padding: 3px 10px; font-size: 11px; border-radius: 4px;
  border: 1px solid var(--line, #d4c8a8); background: var(--card, #fff);
  cursor: pointer; font-family: inherit;
}
.edit-actions button:first-child {
  background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017);
}
</style>
