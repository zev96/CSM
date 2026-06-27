<script setup lang="ts">
import { reactive, ref, watch, computed } from "vue";
import { useMaterials, type AtomDraft, type FolderProfile, type NotePayload, type WriteReceipt } from "@/stores/materials";
import { useNotifications } from "@/composables/useNotifications";
import { assembleFrontmatter, filenameError } from "@/components/materials/payload";

const props = defineProps<{ atom: AtomDraft; folders: FolderProfile[] }>();
const m = useMaterials();
const notify = useNotifications();

const selectedRel = ref<string | null>(props.atom.rel_folder);
const fm = reactive<Record<string, string>>({});
const filename = ref(props.atom.filename);
const text = ref(props.atom.text);
const receipt = ref<WriteReceipt | null>(null);
const committing = ref(false);

function folderOf(rel: string | null): FolderProfile | null {
  return props.folders.find((f) => f.rel_folder === rel) ?? null;
}

function rebuildFm(rel: string | null): void {
  for (const k of Object.keys(fm)) delete fm[k];
  const f = folderOf(rel);
  if (!f) return;
  for (const k of f.frontmatter_keys) fm[k] = f.defaults[k] ?? "";
  if ("产品" in fm && props.atom.product) fm["产品"] = props.atom.product;
  if ("素材类型" in fm && props.atom.material_type) fm["素材类型"] = props.atom.material_type;
  if ("核心关键词" in fm && props.atom.keyword) fm["核心关键词"] = props.atom.keyword;
}
watch(selectedRel, (rel) => rebuildFm(rel), { immediate: true });

const fnErr = computed(() => filenameError(filename.value));
const confLabel = computed(() => ({ high: "高", med: "中", low: "低" }[props.atom.confidence]));

function buildPayload(): NotePayload | null {
  if (!selectedRel.value || fnErr.value) return null;
  const variants = [text.value].filter((t) => t.trim());
  if (!variants.length) return null;
  return { rel_folder: selectedRel.value, filename: filename.value.trim(),
    frontmatter: assembleFrontmatter(fm), body_shape: "variants", variants };
}

const canCommit = computed(() => !!buildPayload() && !receipt.value && !committing.value);

async function commit(): Promise<void> {
  const p = buildPayload();
  if (!p || receipt.value || committing.value) return;
  committing.value = true;
  try {
    const rc = await m.commitAtom(p);
    if (rc) { receipt.value = rc; notify.push(`已入库：${p.filename}`, { tone: "success" }); }
  } finally {
    committing.value = false;
  }
}

async function undo(): Promise<void> {
  if (!receipt.value) return;
  await m.undoAtom(receipt.value);
  receipt.value = null;
  notify.push("已撤销该条", { tone: "info" });
}

// 面板「全部入库」用：仅 high/med 且未入库才提交，返回真实结果供统计。
async function commitAuto(): Promise<"committed" | "skipped" | "failed"> {
  if (!["high", "med"].includes(props.atom.confidence) || receipt.value) return "skipped";
  await commit();
  return receipt.value ? "committed" : "failed";
}
defineExpose({ commitAuto });
</script>

<template>
  <div data-atom-card :data-confidence="atom.confidence"
    class="flex flex-col gap-2 rounded-xl border p-3"
    :style="{ borderColor: atom.confidence === 'low' ? 'var(--amber, #d97706)' : 'rgba(0,0,0,0.1)',
              background: receipt ? 'rgba(16,185,129,0.06)' : 'transparent' }">
    <div class="flex items-center gap-2 text-xs">
      <span class="rounded-full px-2 py-0.5"
        :style="{ background: atom.confidence === 'low' ? 'rgba(217,119,6,0.15)' : 'rgba(0,0,0,0.06)' }">
        置信度 {{ confLabel }}
      </span>
      <span v-if="receipt" class="text-emerald-600">✓ 已入库</span>
    </div>

    <p v-for="w in atom.warnings" :key="w" class="text-xs text-amber-600">⚠ {{ w }}</p>

    <textarea v-model="text" rows="3" data-atom-text
      class="w-full rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />

    <div class="flex flex-wrap gap-2">
      <select v-model="selectedRel" data-atom-folder
        class="rounded-lg border border-ink/15 px-2 py-1 text-xs">
        <option :value="null">— 选择文件夹 —</option>
        <option v-for="f in folders" :key="f.rel_folder" :value="f.rel_folder">{{ f.rel_folder }}</option>
      </select>
      <input v-model="filename" data-atom-filename placeholder="文件名.md"
        class="w-40 rounded-lg border border-ink/15 px-2 py-1 text-xs" />
    </div>
    <p v-if="fnErr" class="text-xs" :style="{ color: 'var(--red)' }">{{ fnErr }}</p>

    <div v-for="k in folderOf(selectedRel)?.frontmatter_keys || []" :key="k" class="flex items-center gap-2">
      <label class="w-16 shrink-0 text-xs text-ink/50">{{ k }}</label>
      <input v-model="fm[k]" :data-atom-fm="k"
        class="flex-1 rounded-lg border border-ink/15 px-2 py-1 text-xs" />
    </div>

    <div class="flex items-center gap-2 pt-1">
      <button data-atom-commit
        class="rounded-lg px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
        :style="{ background: 'var(--primary)' }" :disabled="!canCommit" @click="commit">确认入库</button>
      <button v-if="receipt" data-atom-undo class="rounded-lg px-3 py-1 text-xs text-ink/70" @click="undo">撤销</button>
    </div>
  </div>
</template>
