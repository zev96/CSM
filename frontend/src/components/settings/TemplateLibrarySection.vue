<script setup lang="ts">
/**
 * Settings → 评论模板库 section.
 * Full CRUD + bulk import + JSON export. 隐藏/恢复 功能按用户要求下线
 * （"这个功能没有用"）—— 改用直接删除。后端 hidden 字段保留兼容，
 * UI 一律按 hidden=0 拉数据，hidden=1 的老数据不显示。
 */
import { onMounted, onUnmounted, ref, watch } from "vue"

import Icon from "@/components/ui/Icon.vue"
import FormSelect from "@/components/forms/FormSelect.vue"
import { useToast } from "@/composables/useToast"
import { confirmDialog } from "@/composables/useConfirm"
import { useTemplatesStore, type Template } from "@/stores/templates"

import TemplateEditModal from "./TemplateEditModal.vue"
import TemplateBulkImportModal from "./TemplateBulkImportModal.vue"

const store = useTemplatesStore()
const toast = useToast()

const search = ref("")
const selectedTags = ref<string[]>([])
const platform = ref<string>("")
const page = ref(0)
const pageSize = 50

const showEdit = ref(false)
const editMode = ref<"create" | "edit">("create")
const editTarget = ref<Template | null>(null)
const showBulkImport = ref(false)

let searchTimer: number | undefined

// Filter changes → reset to page 0 + refresh
watch([search, selectedTags, platform], () => {
  page.value = 0
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refresh, 200)
})

// Page changes alone → just refresh (debounced)
watch(page, () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refresh, 200)
})

async function refresh() {
  // hidden 永远 "0" —— UI 不再让用户切换显示隐藏的模板。
  await store.list({
    search: search.value || undefined,
    tags: selectedTags.value.length ? selectedTags.value : undefined,
    platform: platform.value || undefined,
    hidden: "0",
    limit: pageSize,
    offset: page.value * pageSize,
  })
}

onMounted(async () => {
  await store.loadAllTags()
  await refresh()
})

onUnmounted(() => {
  if (searchTimer) window.clearTimeout(searchTimer)
})

function openCreate() {
  editMode.value = "create"
  editTarget.value = null
  showEdit.value = true
}

function openEdit(tpl: Template) {
  editMode.value = "edit"
  editTarget.value = tpl
  showEdit.value = true
}

async function onSaved(_tpl: Template) {
  showEdit.value = false
  toast.success(editMode.value === "create" ? "已新建模板" : "已保存修改")
  await refresh()
  await store.loadAllTags()
}

function onDuplicate(existingId: number) {
  toast.error(`已存在同文本模板（id=${existingId}）`)
}

async function onImported(result: { created: number; skipped_duplicates: number }) {
  showBulkImport.value = false
  if (result.created === 0) {
    toast.info(`${result.skipped_duplicates} 条全为重复，未导入新内容`)
  } else {
    toast.success(`新增 ${result.created} 条，跳过 ${result.skipped_duplicates} 条重复`)
  }
  await refresh()
  await store.loadAllTags()
}

async function toggleStar(tpl: Template) {
  await store.update(tpl.id, { starred: !tpl.starred })
}

// toggleHidden 已下线 —— 用户要求删除隐藏功能。需要清理就直接删除。

async function doDelete(tpl: Template) {
  // 不能用 window.confirm —— Tauri 2 把它转给已退役的 dialog|confirm IPC，
  // 抛 "Command not found"。统一走 in-app confirmDialog。
  const msg = tpl.use_count > 0
    ? `这条用过 ${tpl.use_count} 次，确定删除？删除后无法恢复。`
    : "确定删除？删除后无法恢复。"
  if (!(await confirmDialog(msg, { title: "删除模板", okLabel: "删除" }))) return
  await store.remove(tpl.id)
  toast.success("已删除")
  await refresh()
}

async function exportJSON() {
  const all = await store.exportAll()
  const json = JSON.stringify(all, null, 2)
  const blob = new Blob([json], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "")
  a.download = `templates-export-${today}.json`
  a.click()
  URL.revokeObjectURL(url)
  toast.success(`已导出 ${all.length} 条模板`)
}

function toggleTag(tag: string) {
  const i = selectedTags.value.indexOf(tag)
  if (i >= 0) selectedTags.value.splice(i, 1)
  else selectedTags.value.push(tag)
  page.value = 0  // reset to first page on filter change
}
</script>

<template>
  <div class="section">
    <header class="toolbar">
      <div class="search-wrap">
        <Icon name="search" :size="13" class="search-icon" />
        <input v-model="search" placeholder="搜索文本或标签…" />
      </div>
      <div class="tag-filter">
        <Icon name="tag" :size="11" />
        <button
          v-for="t in store.allTags"
          :key="t"
          class="tag-chip"
          :class="{ active: selectedTags.includes(t) }"
          @click="toggleTag(t)"
        >{{ t }}</button>
        <span v-if="!store.allTags.length" class="muted">（暂无标签）</span>
      </div>
      <!--
        平台选择按用户要求精简：
          1. 移除「手动」选项（实际没人手动入库）
          2. 默认项文案 "平台：全部" → "全部"（前缀冗余，下拉本身已说明语义）
        「显示隐藏」复选框 + 整套隐藏/恢复功能已下线。
      -->
      <FormSelect
        :model-value="platform"
        :options="[
          { label: '全部', value: '' },
          { label: '抖音', value: 'douyin' },
          { label: '快手', value: 'kuaishou' },
          { label: 'B 站', value: 'bilibili' },
        ]"
        @update:model-value="(v) => (platform = String(v))"
      />
    </header>

    <div class="actions">
      <button class="primary" @click="openCreate">
        <Icon name="plus" :size="12" /> 新建模板
      </button>
      <button @click="showBulkImport = true">
        <Icon name="upload" :size="12" /> 批量导入
      </button>
      <button @click="exportJSON">
        <Icon name="download" :size="12" /> 导出 JSON
      </button>
      <span class="count">
        共 {{ store.total }} 条
      </span>
    </div>

    <div v-if="store.items.length === 0" class="empty">
      <Icon name="bookmark" :size="48" />
      <p>评论模板库还是空的</p>
      <p class="muted">发一条评论它就会自动入库，或者点 + 新建模板 先攒几条</p>
    </div>

    <ul v-else class="list">
      <li
        v-for="tpl in store.items"
        :key="tpl.id"
        class="row"
        :class="{ starred: tpl.starred }"
      >
        <span class="star-slot">
          <button @click="toggleStar(tpl)" :title="tpl.starred ? '取消精选' : '标精选'">
            <Icon name="skills" :size="16" />
          </button>
        </span>
        <div class="body">
          <div class="text">{{ tpl.text }}</div>
          <div class="meta">
            <span v-for="t in tpl.tags" :key="t" class="meta-tag">#{{ t }}</span>
            <span v-if="!tpl.tags.length" class="muted">(无标签)</span>
            <span v-if="tpl.source_platform"> · {{ tpl.source_platform }}</span>
            <span> · 用过 {{ tpl.use_count }} 次</span>
            <span> · {{ tpl.first_seen_at.slice(0, 10) }} 入库</span>
          </div>
        </div>
        <div class="ops">
          <button @click="openEdit(tpl)" title="编辑">
            <Icon name="edit" :size="12" /> 编辑
          </button>
          <!-- 隐藏/恢复按钮已下线（用户要求） -->
          <button class="danger" @click="doDelete(tpl)" title="删除">
            <Icon name="trash" :size="12" /> 删除
          </button>
        </div>
      </li>
    </ul>

    <div v-if="store.total > pageSize" class="pager">
      <button :disabled="page === 0" @click="page--">← 上一页</button>
      <span>
        第 {{ page * pageSize + 1 }}-{{ Math.min((page + 1) * pageSize, store.total) }} / 共 {{ store.total }}
      </span>
      <button :disabled="(page + 1) * pageSize >= store.total" @click="page++">下一页 →</button>
    </div>

    <TemplateEditModal
      v-if="showEdit"
      :mode="editMode"
      :template="editTarget"
      @close="showEdit = false"
      @saved="onSaved"
      @duplicate="onDuplicate"
    />
    <TemplateBulkImportModal
      v-if="showBulkImport"
      @close="showBulkImport = false"
      @imported="onImported"
    />
  </div>
</template>

<style scoped>
.section { padding: 16px 0; }
.toolbar {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  margin-bottom: 12px;
}
.search-wrap { position: relative; }
.search-wrap input {
  padding: 5px 10px 5px 28px; min-width: 200px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  background: var(--card-input, #fff); font-size: 12px;
  color: var(--ink, #2a2017);
}
.search-icon { position: absolute; left: 8px; top: 50%; transform: translateY(-50%); color: var(--ink-4, #9c8a6a); }
.tag-filter { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.tag-chip {
  background: var(--card-2, #fff5dc); border: 1px solid var(--line, #e8d6a8);
  border-radius: 10px; padding: 2px 8px; font-size: 10px; cursor: pointer;
  color: var(--ink, #6a5520); font-family: inherit;
}
.tag-chip.active { background: var(--accent, #e0a020); color: #fff; border-color: var(--accent, #e0a020); }
/* .show-hidden 样式已下线（隐藏功能整体移除） */
.actions {
  display: flex; gap: 8px; align-items: center;
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid var(--line, #e8dcc0);
}
.actions button {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 11px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  background: var(--card, #fff); font-size: 12px; cursor: pointer;
  color: var(--ink, #4a3f2a); font-family: inherit;
}
.actions button.primary { background: var(--ink, #2a2017); color: #fff; border-color: var(--ink, #2a2017); }
.count { margin-left: auto; font-size: 11px; color: var(--ink-4, #9c8a6a); }
.empty { text-align: center; padding: 60px 20px; color: var(--ink-4, #9c8a6a); }
.empty p { margin: 6px 0; }
.list { list-style: none; padding: 0; margin: 0; }
.row {
  display: flex; gap: 12px; align-items: center;
  background: var(--card, #fff);
  border: 1px solid var(--line-light, #ece0c2); border-radius: 8px;
  padding: 11px 13px; margin-bottom: 8px;
}
.row.starred { border-color: var(--accent, #e0a020); background: var(--card-warm, #fffaee); }
/* .row.hidden 样式已下线（隐藏功能整体移除） */
.star-slot button { background: transparent; border: none; cursor: pointer; padding: 2px; color: var(--ink-4, #c8b888); }
.row.starred .star-slot button { color: var(--accent, #e0a020); }
.body { flex: 1; min-width: 0; }
.text { font-size: 12.5px; color: var(--ink, #2a2017); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { font-size: 10.5px; color: var(--ink-4, #9c8a6a); margin-top: 4px; }
.meta-tag {
  background: var(--card-2, #fff5dc); padding: 1px 6px;
  border-radius: 8px; color: var(--ink, #6a5520); margin-right: 4px;
}
.ops { display: flex; gap: 4px; }
.ops button {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 7px; border: 1px solid var(--line-light, #ece0c2); border-radius: 4px;
  background: var(--card-2, #faf3df); color: var(--ink, #6b5a3a);
  font-size: 10px; cursor: pointer; font-family: inherit;
}
.ops button.danger { color: #c44; border-color: #f0d0d0; background: #fff5f5; }
.pager {
  display: flex; gap: 16px; align-items: center; justify-content: center;
  padding: 14px; font-size: 11px; color: var(--ink-4, #9c8a6a);
  border-top: 1px dashed var(--line, #e8dcc0); margin-top: 8px;
}
.pager button {
  padding: 4px 10px; border: 1px solid var(--line, #d4c8a8); border-radius: 4px;
  background: var(--card, #fff); cursor: pointer; font-size: 11px;
  font-family: inherit; color: var(--ink, #4a3f2a);
}
.pager button:disabled { opacity: 0.4; cursor: not-allowed; }
.muted { font-size: 10px; color: var(--ink-4, #9c8a6a); }
</style>
