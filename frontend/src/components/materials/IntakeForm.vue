<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import Spinner from "@/components/ui/Spinner.vue";
import Pill from "@/components/ui/Pill.vue";
import { useMaterials, type FolderProfile, type NotePayload } from "@/stores/materials";
import { useNotifications } from "@/composables/useNotifications";

const m = useMaterials();
const notify = useNotifications();

const selected = ref<FolderProfile | null>(null);
const filename = ref("");
const fm = reactive<Record<string, string>>({});
const variants = ref<string[]>([""]);
const specRows = ref<{ group: string; key: string; value: string }[]>([{ group: "", key: "", value: "" }]);
const submitting = ref(false);

onMounted(() => m.loadFolders());

function pick(f: FolderProfile): void {
  selected.value = f;
  for (const k of Object.keys(fm)) delete fm[k];
  for (const k of f.frontmatter_keys) fm[k] = f.defaults[k] ?? "";
  filename.value = "";
  variants.value = [""];
  specRows.value = [{ group: "", key: "", value: "" }];
  m.currentPlan = null;
}

const isVariants = computed(() => selected.value?.body_shape !== "spec_table");

function buildPayload(): NotePayload | null {
  const f = selected.value;
  if (!f || !filename.value.trim()) return null;
  const frontmatter: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fm)) {
    if (k === "核心关键词") frontmatter[k] = String(v).split(/[，,\s]+/).filter(Boolean);
    else if (v) frontmatter[k] = v;
  }
  const payload: NotePayload = {
    rel_folder: f.rel_folder, filename: filename.value.trim(),
    frontmatter, body_shape: isVariants.value ? "variants" : "spec_table",
  };
  if (isVariants.value) payload.variants = variants.value.filter((t) => t.trim());
  else payload.spec_rows = specRows.value.filter((r) => r.key.trim());
  return payload;
}

// 防抖 diff 预览
let _t: ReturnType<typeof setTimeout> | undefined;
watch([selected, filename, fm, variants, specRows], () => {
  if (_t) clearTimeout(_t);
  _t = setTimeout(() => {
    const p = buildPayload();
    if (p) m.planNote(p);
  }, 350);
}, { deep: true });

onUnmounted(() => { if (_t) clearTimeout(_t); });

const filenameError = computed(() => {
  const v = filename.value.trim();
  if (!v) return "";
  if (/\s/.test(v) || v.includes("/") || v.includes("\\")) return "不能含空格/路径分隔符";
  if (!v.endsWith(".md")) return "须以 .md 结尾";
  return "";
});

async function submit(): Promise<void> {
  const p = buildPayload();
  if (!p || filenameError.value || m.currentPlan?.conflict || submitting.value) return;
  submitting.value = true;
  try {
    if (await m.commitNote(p)) {
      notify.push(`已入库：${p.filename}`, { tone: "success" });
      if (selected.value) pick(selected.value);   // reset fields, keep folder + 撤销 可达
    }
  } finally {
    submitting.value = false;
  }
}

async function undo(): Promise<void> {
  await m.undoLast();
  notify.push("已撤销上次写入", { tone: "info" });
}

function addVariant(): void { variants.value.push(""); }
function rmVariant(i: number): void { variants.value.splice(i, 1); }
function addSpecRow(): void { specRows.value.push({ group: "", key: "", value: "" }); }
function rmSpecRow(i: number): void { specRows.value.splice(i, 1); }
</script>

<template>
  <div class="flex h-full min-h-0 gap-4">
    <!-- 左：文件夹选择 -->
    <div class="flex w-72 min-w-0 flex-col overflow-y-auto border-r border-ink/10 pr-3">
      <div v-if="m.foldersLoading" class="flex items-center gap-2 p-3 text-sm text-ink/50">
        <Spinner :size="14" /> 加载文件夹…
      </div>
      <div v-else-if="!m.writableFolders.length" class="p-3 text-sm text-ink/50">
        素材库无可写文件夹。请在「设置」确认素材库路径。
      </div>
      <button
        v-for="f in m.writableFolders" :key="f.rel_folder" :data-folder="f.rel_folder"
        class="flex flex-col gap-1 rounded-lg px-2 py-2 text-left transition-colors"
        :style="{ background: selected?.rel_folder === f.rel_folder ? 'var(--card-2, rgba(0,0,0,0.05))' : 'transparent' }"
        @click="pick(f)"
      >
        <span class="text-sm font-medium">{{ f.rel_folder }}</span>
        <div class="flex flex-wrap items-center gap-1 text-[10px] text-ink/50">
          <Pill>{{ f.body_shape === "spec_table" ? "参数表" : "变体" }}</Pill>
          <span>{{ f.sample_count }} 篇</span>
          <span v-if="f.material_types.length">· {{ f.material_types.join("/") }}</span>
        </div>
      </button>
    </div>

    <!-- 中：表单 -->
    <div class="flex w-96 min-w-0 flex-col gap-3 overflow-y-auto">
      <div v-if="!selected" class="grid h-full place-items-center text-sm text-ink/40">
        选择左侧文件夹开始录入
      </div>
      <template v-else>
        <div>
          <label class="mb-1 block text-xs text-ink/50">文件名</label>
          <input v-model="filename" data-filename placeholder="吸尘器-描述-核心词.md"
            class="w-full rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
          <p v-if="filenameError" class="mt-1 text-xs" :style="{ color: 'var(--red)' }">{{ filenameError }}</p>
        </div>
        <div v-for="k in selected.frontmatter_keys" :key="k">
          <label class="mb-1 block text-xs text-ink/50">{{ k }}</label>
          <input v-model="fm[k]" :data-fm="k"
            class="w-full rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
        </div>

        <!-- 变体 body -->
        <div v-if="isVariants" class="flex flex-col gap-2">
          <label class="text-xs text-ink/50">正文变体（①②③）</label>
          <div v-for="(_, i) in variants" :key="i" data-variant-row class="flex gap-1">
            <textarea v-model="variants[i]" rows="2"
              class="flex-1 rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
            <button class="text-xs text-ink/40" @click="rmVariant(i)">✕</button>
          </div>
          <button class="self-start text-xs text-ink/60" @click="addVariant">+ 加变体</button>
        </div>

        <!-- 参数表 body -->
        <div v-else class="flex flex-col gap-2">
          <label class="text-xs text-ink/50">参数（分组/参数/数值）</label>
          <div v-for="(row, i) in specRows" :key="i" data-spec-row class="flex gap-1">
            <input v-model="row.group" placeholder="分组" class="w-20 rounded border border-ink/15 px-1.5 py-1 text-xs" />
            <input v-model="row.key" placeholder="参数" class="w-24 rounded border border-ink/15 px-1.5 py-1 text-xs" />
            <input v-model="row.value" placeholder="数值" class="flex-1 rounded border border-ink/15 px-1.5 py-1 text-xs" />
            <button class="text-xs text-ink/40" @click="rmSpecRow(i)">✕</button>
          </div>
          <button class="self-start text-xs text-ink/60" @click="addSpecRow">+ 加行</button>
        </div>

        <div class="flex items-center gap-2 pt-2">
          <button
            data-submit
            class="rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
            :style="{ background: 'var(--primary)' }"
            :disabled="!!filenameError || !!m.currentPlan?.conflict || submitting"
            @click="submit"
          >确认入库</button>
          <button v-if="m.lastReceipt" data-undo class="rounded-lg px-3 py-1.5 text-sm text-ink/70" @click="undo">
            撤销上次写入
          </button>
        </div>
        <p v-if="m.intakeError" class="text-xs" :style="{ color: 'var(--red)' }">{{ m.intakeError }}</p>
      </template>
    </div>

    <!-- 右：diff 预览 -->
    <div class="flex min-w-0 flex-1 flex-col overflow-y-auto">
      <label class="mb-1 text-xs text-ink/50">预览（将写入的 .md 全文）</label>
      <p v-if="m.currentPlan?.conflict" class="mb-2 text-xs" :style="{ color: 'var(--red)' }">
        ⚠ 同名笔记已存在，不可覆盖——请改文件名
      </p>
      <p v-for="w in m.currentPlan?.warnings || []" :key="w" class="mb-1 text-xs text-amber-600">⚠ {{ w }}</p>
      <pre class="flex-1 whitespace-pre-wrap rounded-lg bg-ink/5 p-3 text-xs leading-relaxed text-ink/80">{{ m.currentPlan?.full_text || "填写后实时预览…" }}</pre>
      <div v-if="m.currentPlan?.index_line" class="mt-2 text-[11px] text-ink/50">
        将登记到索引：<code>{{ m.currentPlan.index_line }}</code>
      </div>
    </div>
  </div>
</template>
