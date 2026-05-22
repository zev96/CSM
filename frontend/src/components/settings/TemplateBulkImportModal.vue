<script setup lang="ts">
/**
 * Bulk import modal: paste many lines, optionally apply common tags + platform,
 * preview "新增 X / 跳过 Y 重复", confirm to import.
 */
import { computed, ref } from "vue"

import Icon from "@/components/ui/Icon.vue"
import FormSelect from "@/components/forms/FormSelect.vue"
import { useTemplatesStore } from "@/stores/templates"

const emit = defineEmits<{
  (e: "close"): void
  (e: "imported", result: { created: number; skipped_duplicates: number }): void
}>()

const store = useTemplatesStore()
const rawInput = ref("")
const tagInput = ref("")
const tags = ref<string[]>([])
const platform = ref<string>("")
const importing = ref(false)
const error = ref("")

const lines = computed(() =>
  rawInput.value.split("\n").map(l => l.trim()).filter(l => l.length > 0),
)

const previewSkipped = computed(() => {
  const seen = new Set<string>()
  let skipped = 0
  for (const line of lines.value) {
    if (seen.has(line)) skipped++
    else seen.add(line)
  }
  return skipped
})

function addTag(t: string) {
  const tag = t.trim()
  if (!tag || tags.value.includes(tag)) {
    tagInput.value = ""
    return
  }
  if (tags.value.length >= 10) {
    error.value = "最多 10 个标签"
    return
  }
  if (tag.length > 12) {
    error.value = "单标签最多 12 字"
    return
  }
  tags.value.push(tag)
  tagInput.value = ""
  error.value = ""
}

function removeTag(t: string) {
  tags.value = tags.value.filter(x => x !== t)
}

async function doImport() {
  if (lines.value.length === 0) {
    error.value = "请输入至少一行"
    return
  }
  if (lines.value.length > 500) {
    error.value = `单次最多 500 条（当前 ${lines.value.length} 条）`
    return
  }
  importing.value = true
  error.value = ""
  try {
    const result = await store.bulkImport({
      texts: lines.value,
      tags: tags.value,
      source_platform: platform.value || null,
    })
    emit("imported", result)
  } catch (err) {
    const detail = (err as any)?.response?.data?.detail
    error.value = detail || (err as Error).message || "导入失败"
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-header">
        <h3>批量导入模板</h3>
        <button @click="emit('close')"><Icon name="x" :size="14" /></button>
      </header>

      <div class="modal-body">
        <label>
          <span>每行一条评论</span>
          <textarea v-model="rawInput" rows="10" placeholder="粘贴文本，每行一条…" />
        </label>

        <label>
          <span>公共标签（应用到所有导入项）</span>
          <div class="tag-list">
            <span v-for="t in tags" :key="t" class="tag-pill">
              {{ t }} <button @click="removeTag(t)">×</button>
            </span>
            <input
              v-model="tagInput"
              placeholder="回车添加…"
              @keydown.enter.prevent="addTag(tagInput)"
              @keydown.comma.prevent="addTag(tagInput)"
              :disabled="tags.length >= 10"
            />
          </div>
        </label>

        <label>
          <span>来源平台</span>
          <FormSelect
            :model-value="platform"
            :options="[
              { label: '手动 (默认)', value: '' },
              { label: '抖音', value: 'douyin' },
              { label: '快手', value: 'kuaishou' },
              { label: 'B 站', value: 'bilibili' },
            ]"
            @update:model-value="(v) => (platform = String(v))"
          />
        </label>

        <div class="preview">
          <Icon name="info" :size="12" />
          <span>
            将尝试导入 <b>{{ lines.length }}</b> 条；
            其中 <b>{{ previewSkipped }}</b> 条在本批内重复，库内已有的会被跳过
          </span>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
      </div>

      <footer class="modal-footer">
        <button @click="emit('close')">取消</button>
        <button class="primary" :disabled="importing || lines.length === 0" @click="doImport">
          {{ importing ? "导入中…" : `导入 ${lines.length} 条` }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-card {
  background: var(--card, #fff);
  border-radius: 10px;
  width: 560px; max-width: 95vw;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.2);
  display: flex; flex-direction: column;
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--line, #e8dcc0);
}
.modal-header h3 { margin: 0; font-size: 14px; color: var(--ink, #2a2017); }
.modal-header button {
  background: transparent; border: none; cursor: pointer; padding: 4px;
}
.modal-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.modal-body label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.modal-body label > span:first-child { font-weight: 600; color: var(--ink, #4a3f2a); }
.modal-body textarea, .modal-body select {
  width: 100%; padding: 8px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  font-family: inherit; font-size: 12px;
  background: var(--card-input, #fff);
  color: var(--ink, #2a2017);
}
.modal-body textarea {
  line-height: 1.5; resize: vertical; min-height: 140px;
}
.tag-list {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px; padding: 6px;
  background: var(--card-input, #fff);
}
.tag-pill {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--card-2, #fff5dc); padding: 2px 8px;
  border-radius: 10px; font-size: 11px; color: var(--ink, #6a5520);
}
.tag-pill button {
  background: transparent; border: none; cursor: pointer;
  color: var(--ink-4, #9c8a6a); font-size: 13px; padding: 0;
}
.tag-list input {
  flex: 1; min-width: 100px; border: none; outline: none;
  font-size: 12px; background: transparent; font-family: inherit;
  color: var(--ink, #2a2017);
}
.preview {
  background: var(--card-2, #fff5dc); padding: 8px 10px;
  border-radius: 6px; font-size: 11px; color: var(--ink, #4a3f2a);
  display: flex; align-items: center; gap: 6px;
}
.error { color: #c44; font-size: 12px; }
.modal-footer {
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 12px 18px; border-top: 1px solid var(--line, #e8dcc0);
}
.modal-footer button {
  padding: 6px 14px; border-radius: 6px;
  border: 1px solid var(--line, #d4c8a8); background: var(--card, #fff);
  font-size: 12px; cursor: pointer; font-family: inherit;
  color: var(--ink, #4a3f2a);
}
.modal-footer button.primary {
  background: var(--ink, #2a2017); color: #fff;
  border-color: var(--ink, #2a2017);
}
.modal-footer button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
