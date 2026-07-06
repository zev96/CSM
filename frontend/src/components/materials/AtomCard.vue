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
const hidden = ref(false); // 「忽略」= 本地隐藏 + commitAll 跳过

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

// 置信度徽章配色（走 token → 暗色自动适配）
const CONF = {
  high: { bg: "rgba(var(--green-rgb), 0.16)", color: "var(--green-deep)", label: "高置信度" },
  med: { bg: "var(--yellow-soft)", color: "var(--yellow-deep)", label: "中置信度" },
  low: { bg: "rgba(var(--red-rgb), 0.14)", color: "var(--red)", label: "低置信度" },
} as const;
const conf = computed(() => CONF[props.atom.confidence]);
const cardBorder = computed(() =>
  receipt.value
    ? "rgba(var(--green-rgb), 0.45)"
    : props.atom.confidence === "low"
      ? "rgba(var(--red-rgb), 0.35)"
      : "rgba(var(--ink-rgb), 0.08)",
);

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

// 面板「全部入库」用：仅 high/med 且未入库/未忽略才提交，返回真实结果供统计。
async function commitAuto(): Promise<"committed" | "skipped" | "failed"> {
  if (hidden.value) return "skipped";
  if (!["high", "med"].includes(props.atom.confidence) || receipt.value) return "skipped";
  await commit();
  return receipt.value ? "committed" : "failed";
}
defineExpose({ commitAuto });
</script>

<template>
  <div
    v-if="!hidden" data-atom-card :data-confidence="atom.confidence"
    class="flex flex-col gap-2 rounded-[14px] border p-4"
    :style="{ borderColor: cardBorder, background: receipt ? 'rgba(var(--green-rgb), 0.06)' : 'var(--card-white)' }"
  >
    <!-- 头：归类目录 + 置信度 -->
    <div class="flex items-center gap-2">
      <select
        v-model="selectedRel" data-atom-folder :title="selectedRel || undefined"
        class="font-mono min-w-0 max-w-[62%] truncate rounded-md px-1.5 py-0.5 text-[11px]"
        :style="{ color: 'var(--ink-3)', background: 'rgba(var(--ink-rgb), 0.04)', border: '1px solid transparent' }"
      >
        <option :value="null">— 选择文件夹 —</option>
        <option v-for="f in folders" :key="f.rel_folder" :value="f.rel_folder">{{ f.rel_folder }}</option>
      </select>
      <span v-if="receipt" class="text-[11px]" style="color: var(--green-deep)">✓ 已入库</span>
      <span class="ml-auto flex-none rounded-full px-2.5 py-[2.5px] text-[10.5px] font-semibold"
        :style="{ background: conf.bg, color: conf.color }">{{ conf.label }}</span>
    </div>

    <!-- 正文（可编辑） -->
    <textarea v-model="text" rows="3" data-atom-text class="mat-input mat-input--sm resize-none leading-[1.8]" />

    <!-- why / 警告 -->
    <div v-for="w in atom.warnings" :key="w" class="flex items-start gap-1.5 rounded-lg px-2.5 py-[7px] text-[11.5px] leading-[1.7]"
      style="background: rgba(var(--red-rgb), 0.07); color: var(--red-deep)">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mt-[3px] flex-none">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
      <span>{{ w }}</span>
    </div>

    <!-- 文件名 + frontmatter -->
    <input v-model="filename" data-atom-filename placeholder="文件名.md" class="mat-input mat-input--sm" />
    <p v-if="fnErr" class="text-[11px]" style="color: var(--red)">{{ fnErr }}</p>
    <div v-for="k in folderOf(selectedRel)?.frontmatter_keys || []" :key="k" class="flex items-center gap-2">
      <label class="w-16 flex-none text-[11px]" style="color: var(--ink-3)">{{ k }}</label>
      <input v-model="fm[k]" :data-atom-fm="k" class="mat-input mat-input--sm" />
    </div>

    <!-- 入库 / 忽略 -->
    <div class="flex items-center gap-2 pt-0.5">
      <button data-atom-commit class="atom-ingest" :disabled="!canCommit" @click="commit">
        {{ receipt ? "已入库" : "入库" }}
      </button>
      <button v-if="receipt" data-atom-undo class="mat-btn-ghost !py-1.5 !text-[12px]" @click="undo">撤销</button>
      <button v-else class="mat-btn-ghost !py-1.5 !text-[12px]" @click="hidden = true">忽略</button>
    </div>
  </div>
</template>

<style scoped>
/* 入库按钮：软橙（未入库）→ 软绿（已入库），呼应设计稿 */
.atom-ingest {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5.5px 14px;
  border-radius: 999px;
  border: none;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  background: var(--primary-soft);
  color: var(--primary-deep);
  transition: background 0.12s, opacity 0.12s;
}
.atom-ingest:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
