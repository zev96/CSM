<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import Spinner from "@/components/ui/Spinner.vue";
import { useMaterials, type FolderProfile, type NotePayload } from "@/stores/materials";
import { useNotifications } from "@/composables/useNotifications";
import { assembleFrontmatter, filenameError as fnError } from "@/components/materials/payload";

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

// 素材树:后端已含中间层与空文件夹(空文件夹借兄弟产品线模板),按路径深度缩进渲染。
const treeRows = computed(() =>
  m.writableFolders.map((f) => {
    const segs = f.rel_folder.split("/");
    return {
      folder: f,
      label: segs[segs.length - 1],
      pad: 10 + (segs.length - 1) * 13,
      isTable: f.body_shape === "spec_table",
      count: f.sample_count,
      tip: f.rel_folder + (f.material_types.length ? "\n" + f.material_types.join("/") : ""),
    };
  }),
);

function buildPayload(): NotePayload | null {
  const f = selected.value;
  if (!f || !filename.value.trim()) return null;
  const frontmatter = assembleFrontmatter(fm);
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

const filenameError = computed(() => fnError(filename.value));
const previewName = computed(() => m.currentPlan?.filename || (filename.value.trim() ? filename.value.trim() : "预览"));

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
  <div class="anim-up flex min-h-0 flex-1 gap-d">
    <!-- 左：素材树 -->
    <aside class="mat-panel flex flex-none flex-col overflow-hidden" style="width: 292px">
      <div class="flex flex-none items-baseline gap-2 px-4.5 pb-2 pt-4">
        <span class="text-[13px] font-bold">素材树</span>
        <span class="text-[11px]" style="color: var(--ink-4)">选择入库位置</span>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        <div v-if="m.foldersLoading" class="flex items-center gap-2 p-3 text-sm" style="color: var(--ink-3)">
          <Spinner :size="14" /> 加载文件夹…
        </div>
        <div v-else-if="!m.writableFolders.length" class="p-3 text-[12px]" style="color: var(--ink-3)">
          素材库无可写文件夹。请在「设置」确认素材库路径。
        </div>
        <button
          v-for="t in treeRows" :key="t.folder.rel_folder" :data-folder="t.folder.rel_folder" :title="t.tip"
          class="mat-row" :class="{ 'mat-row--sel': selected?.rel_folder === t.folder.rel_folder }"
          :style="{ paddingLeft: t.pad + 'px' }"
          @click="pick(t.folder)"
        >
          <svg class="flex-none" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--ink-4)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          <span class="min-w-0 flex-1 truncate text-[12.5px] font-semibold" style="color: var(--ink)">{{ t.label }}</span>
          <span v-if="t.isTable" class="mat-tag-table flex-none">参数表</span>
          <span class="flex-none text-[11px] tabular-nums" style="color: var(--ink-4)">{{ t.count }}</span>
        </button>
      </div>
    </aside>

    <!-- 中：录入表单 -->
    <section class="mat-panel flex flex-none flex-col overflow-hidden" style="width: 430px">
      <div v-if="!selected" class="grid flex-1 place-items-center text-sm" style="color: var(--ink-4)">
        选择左侧文件夹开始录入
      </div>
      <template v-else>
        <div class="flex flex-none items-center gap-2 px-[var(--density-pad)] pb-1 pt-4">
          <span class="text-[13px] font-bold">录入素材</span>
          <span class="mat-dir-pill">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="flex-none">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            <span class="truncate">{{ selected.rel_folder }}</span>
          </span>
        </div>
        <div v-if="selected.template_from" class="flex-none px-[var(--density-pad)] pt-1 text-[11px]" style="color: var(--ink-4)">
          空文件夹 · 表单模板借自「{{ selected.template_from }}」
        </div>

        <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-[var(--density-pad)] pb-1.5 pt-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-[11.5px] font-semibold" style="color: var(--ink-3)">文件名<span class="font-normal" style="color: var(--ink-4)">（建议：产品-描述-核心词）</span></label>
            <input v-model="filename" data-filename placeholder="吸尘器-描述-核心词.md" class="mat-input" />
            <p v-if="filenameError" class="text-[11px]" style="color: var(--red)">{{ filenameError }}</p>
          </div>

          <div v-for="k in selected.frontmatter_keys" :key="k" class="flex flex-col gap-1.5">
            <label class="text-[11.5px] font-semibold" style="color: var(--ink-3)">{{ k }}</label>
            <input v-model="fm[k]" :data-fm="k" class="mat-input" />
          </div>

          <!-- 变体 body -->
          <div v-if="isVariants" class="flex flex-col gap-2 pt-0.5">
            <label class="text-[11.5px] font-semibold" style="color: var(--ink-3)">正文变体（①②③）</label>
            <div v-for="(_, i) in variants" :key="i" data-variant-row class="flex gap-1.5">
              <textarea v-model="variants[i]" rows="2" class="mat-input flex-1 resize-none" />
              <button class="mat-icon-rm self-start" title="删除此变体" @click="rmVariant(i)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
            <button class="mat-btn-add" @click="addVariant">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>加变体
            </button>
          </div>

          <!-- 参数表 body -->
          <div v-else class="flex flex-col gap-2 pt-0.5">
            <div class="grid items-center gap-2" style="grid-template-columns: 96px 1fr 1fr 26px">
              <span class="text-[11.5px] font-semibold" style="color: var(--ink-3)">参数</span>
              <span class="text-[10.5px]" style="color: var(--ink-4)">参数名</span>
              <span class="text-[10.5px]" style="color: var(--ink-4)">数值</span>
              <span />
            </div>
            <div v-for="(row, i) in specRows" :key="i" data-spec-row class="grid items-center gap-2" style="grid-template-columns: 96px 1fr 1fr 26px">
              <input v-model="row.group" placeholder="分组" class="mat-input mat-input--sm" />
              <input v-model="row.key" placeholder="参数" class="mat-input mat-input--sm" />
              <input v-model="row.value" placeholder="数值" class="mat-input mat-input--sm" />
              <button class="mat-icon-rm" title="删除此行" @click="rmSpecRow(i)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
            <button class="mat-btn-add" @click="addSpecRow">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>加一行
            </button>
          </div>
        </div>

        <div class="flex flex-none items-center gap-3 px-[var(--density-pad)] pb-4 pt-3" style="border-top: 1px solid rgba(var(--ink-rgb), 0.06)">
          <button
            data-submit class="mat-btn"
            :disabled="!!filenameError || !!m.currentPlan?.conflict || submitting"
            @click="submit"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
            确认入库
          </button>
          <button v-if="m.lastReceipt" data-undo class="mat-btn-ghost" @click="undo">撤销上次写入</button>
          <span v-else class="text-[11.5px]" style="color: var(--ink-4)">写入后立即可在「品牌型号」页引用</span>
        </div>
        <p v-if="m.intakeError" class="px-[var(--density-pad)] pb-3 text-[11px]" style="color: var(--red)">{{ m.intakeError }}</p>
      </template>
    </section>

    <!-- 右：实时预览（固定暗色 code 面板） -->
    <section class="md-preview flex min-w-0 flex-1 flex-col overflow-hidden">
      <div class="flex flex-none items-center gap-2.5 px-[var(--density-pad)] pb-2.5 pt-4">
        <span class="text-[12px] font-bold" style="color: #f6f0e1">预览</span>
        <span class="text-[11px]" style="color: #a89f8d">将写入的 .md 全文</span>
        <span class="font-mono ml-auto truncate text-[11px]" style="color: #ee6a2a">{{ previewName }}</span>
      </div>
      <p v-if="m.currentPlan?.conflict" class="px-[var(--density-pad)] pb-1 text-[11px]" style="color: #e59a8c">⚠ 同名笔记已存在，不可覆盖——请改文件名</p>
      <p v-for="w in m.currentPlan?.warnings || []" :key="w" class="px-[var(--density-pad)] pb-1 text-[11px]" style="color: #e0b96a">⚠ {{ w }}</p>
      <pre class="font-mono min-h-0 flex-1 overflow-auto whitespace-pre-wrap px-[var(--density-pad)] pb-[var(--density-pad)] pt-1.5 text-[12px] leading-[1.9]" style="margin: 0; color: #d9d1bd">{{ m.currentPlan?.full_text || "填写后实时预览…" }}</pre>
      <div v-if="m.currentPlan?.index_line" class="px-[var(--density-pad)] pb-3 text-[11px]" style="color: #a89f8d">
        将登记到索引：<code class="font-mono" style="color: #d9d1bd">{{ m.currentPlan.index_line }}</code>
      </div>
    </section>
  </div>
</template>
