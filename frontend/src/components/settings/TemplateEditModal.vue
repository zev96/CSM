<script setup lang="ts">
/**
 * Modal for create/edit one template.
 * Used by TemplateLibrarySection in settings.
 *
 * Props:
 *   - mode: "create" | "edit"
 *   - template: Template | null   (required when mode === "edit")
 * Emits:
 *   - close()
 *   - saved(tpl: Template)
 *   - duplicate(existingId: number)
 */
import { onMounted, ref } from "vue"

import Icon from "@/components/ui/Icon.vue"
import { useTemplatesStore, TemplateDuplicateError, type Template } from "@/stores/templates"

const props = defineProps<{
  mode: "create" | "edit"
  template: Template | null
}>()
const emit = defineEmits<{
  (e: "close"): void
  (e: "saved", tpl: Template): void
  (e: "duplicate", existingId: number): void
}>()

const store = useTemplatesStore()
const text = ref("")
const tags = ref<string[]>([])
const tagInput = ref("")
const saving = ref(false)
const error = ref("")
const allTags = ref<string[]>([])

onMounted(async () => {
  if (props.mode === "edit" && props.template) {
    text.value = props.template.text
    tags.value = [...props.template.tags]
  }
  await store.loadAllTags()
  allTags.value = store.allTags
})

function addTag(tag: string) {
  const t = tag.trim()
  if (!t || tags.value.includes(t)) {
    tagInput.value = ""
    return
  }
  if (tags.value.length >= 10) {
    error.value = "最多 10 个标签"
    return
  }
  if (t.length > 12) {
    error.value = "单标签最多 12 字"
    return
  }
  tags.value.push(t)
  tagInput.value = ""
  error.value = ""
}

function removeTag(t: string) {
  tags.value = tags.value.filter(x => x !== t)
}

async function save() {
  error.value = ""
  if (text.value.trim().length === 0) {
    error.value = "文本不能为空"
    return
  }
  if (text.value.length > 2000) {
    error.value = "文本最多 2000 字"
    return
  }
  saving.value = true
  try {
    if (props.mode === "create") {
      const tpl = await store.create({ text: text.value, tags: tags.value })
      emit("saved", tpl)
    } else if (props.template) {
      const tpl = await store.update(props.template.id, {
        text: text.value, tags: tags.value,
      })
      emit("saved", tpl)
    }
  } catch (err) {
    if (err instanceof TemplateDuplicateError) {
      emit("duplicate", err.existingId)
    } else {
      error.value = (err as Error).message || "保存失败"
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-header">
        <h3>{{ mode === "create" ? "新建模板" : "编辑模板" }}</h3>
        <button @click="emit('close')"><Icon name="x" :size="14" /></button>
      </header>

      <div class="modal-body">
        <label>
          <span>文本</span>
          <textarea v-model="text" rows="6" placeholder="评论文本…" />
          <span class="char-count">{{ text.length }} / 2000</span>
        </label>

        <label>
          <span>标签</span>
          <div class="tag-list">
            <span v-for="t in tags" :key="t" class="tag-pill">
              {{ t }}
              <button @click="removeTag(t)">×</button>
            </span>
            <input
              v-model="tagInput"
              placeholder="输入或选择…"
              @keydown.enter.prevent="addTag(tagInput)"
              @keydown.comma.prevent="addTag(tagInput)"
              :disabled="tags.length >= 10"
            />
          </div>
          <div v-if="allTags.length" class="tag-suggestions">
            <span class="muted">已有：</span>
            <button
              v-for="t in allTags.filter((tg: string) => !tags.includes(tg))"
              :key="t"
              class="suggest-chip"
              @click="addTag(t)"
            >{{ t }}</button>
          </div>
        </label>

        <div v-if="error" class="error">{{ error }}</div>
      </div>

      <footer class="modal-footer">
        <button @click="emit('close')">取消</button>
        <button class="primary" :disabled="saving" @click="save">
          {{ saving ? "保存中…" : "保存" }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-card {
  background: var(--card, #fff);
  border-radius: 10px;
  width: 480px; max-width: 95vw;
  box-shadow: 0 12px 32px rgba(0,0,0,0.2);
  display: flex; flex-direction: column;
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--line, #e8dcc0);
}
.modal-header h3 { margin: 0; font-size: 14px; color: var(--ink, #2a2017); }
.modal-header button { background: transparent; border: none; cursor: pointer; padding: 4px; }
.modal-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.modal-body label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.modal-body label > span:first-child { font-weight: 600; color: var(--ink, #4a3f2a); }
.modal-body textarea {
  width: 100%; padding: 8px;
  border: 1px solid var(--line, #d4c8a8); border-radius: 6px;
  font-family: inherit; font-size: 12px; line-height: 1.5;
  resize: vertical; min-height: 100px;
  background: var(--card-input, #fff);
}
.char-count { font-size: 10px; color: var(--ink-4, #9c8a6a); align-self: flex-end; }
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
.tag-suggestions {
  display: flex; flex-wrap: wrap; gap: 4px;
  align-items: center; margin-top: 4px;
}
.suggest-chip {
  background: transparent; border: 1px dashed var(--line, #d4c8a8);
  padding: 1px 7px; border-radius: 8px; font-size: 10px;
  color: var(--ink-3, #8a7848); cursor: pointer; font-family: inherit;
}
.suggest-chip:hover { background: var(--card-2, #fff5dc); }
.muted { font-size: 10px; color: var(--ink-4, #9c8a6a); }
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
