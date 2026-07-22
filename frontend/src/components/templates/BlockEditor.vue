<script setup lang="ts">
/**
 * 单块区块编辑器 — 严格对齐 csm_gui/widgets/block_inspector.py 的字段布局：
 *
 *   eyebrow   "区块 N / M · 段落 / 标题 / ..."
 *   title     友好标题（label / title / text 的派生值）
 *   字段：
 *     paragraph        — 区块名 + 目录 + 段落高级（筛选 / 取值 + 子素材 / 链接）
 *     heading          — 序号 + 标题文本（+关键词）
 *     numbered_list    — 区块名 + 目录 + 编号样式 + 列表高级（筛选 / 取值）
 *     hero_brand       — 标题 + 编号样式 + 推荐理由前缀
 *     competitor_pool  — 目录 + 推荐理由前缀 + 对比池高级（筛选 / 取值）
 *     literal          — 固定文本
 *     test_framework   — 区块名 + 编号样式 + 框架/结果目录 + 主推/竞品标签 +
 *                        测试部分高级（测试项数量 + 跟随区块）
 *     最底部：删除此区块（红色描边）
 *
 *  pick_notes 既可以是 int，也可以是 {random_between: [min, max]}（schema 里
 *  PickCountSpec 的轻量子集），UI 用「素材数量 + 启用随机区间」交互。
 *
 *  paragraph 的 constraints 数组里如果含 "unique_notes" 视作勾选「不重复素材」。
 */
import { computed, ref, watch } from "vue";

import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import Icon from "@/components/ui/Icon.vue";
import CascadePicker from "./CascadePicker.vue";
// MultiValuePicker 已下线 —— 段落筛选改为单选（用 FormSelect 替代）。
import { useSidecar } from "@/stores/sidecar";

const props = defineProps<{
  modelValue: any;
  /** 当前块在父列表中的 index（0-based）；用于「区块 N / M」的 eyebrow。 */
  index?: number;
  /** 父列表总块数。 */
  total?: number;
  /** 父列表里其它所有块（不含自身） — 用于「链接 / 跟随区块」下拉。 */
  siblings?: Array<{ id: string; label: string }>;
  /** Vault 叶子目录列表 — 喂给 CascadePicker 渲染折叠树。 */
  vaultDirs?: string[];
  /** 模板声明的结构版本；空 = 模板没有版本概念。 */
  versionOptions?: string[];
  /** 本块（竞品池）在榜单里的排位起点，用于「本池从 TOP{k} 开始」提示。 */
  startRank?: number;
}>();
const emit = defineEmits<{
  (e: "update:modelValue", v: any): void;
  (e: "delete"): void;
}>();

const block = computed(() => props.modelValue);

// ── 所属版本 ────────────────────────────────────────────────────────
const blockVersions = computed<string[]>(() => block.value.versions ?? []);

function toggleVersion(v: string, on: boolean) {
  const set = new Set(blockVersions.value);
  if (on) set.add(v);
  else set.delete(v);
  patch({ versions: [...set] });
}

// ── 卡片小节 ────────────────────────────────────────────────────────
const isCardMode = computed(() => (block.value.sections?.length ?? 0) > 0);
const isPool = computed(() => block.value.kind === "competitor_pool");

/** 打开卡片模式：给块补上卡片专属字段的默认值。 */
function enableCardMode() {
  if (isPool.value) {
    patch({
      sections: [{ label: "市场口碑数据", h2: "", required: true, pick_variants: 1 }],
      heading_template: block.value.heading_template ?? "### {tier} TOP{n}. {title}",
      tier_key: block.value.tier_key ?? "层级标签",
      label_layout: block.value.label_layout ?? "inline",
      card_separator: block.value.card_separator ?? "\n\n",
    });
  } else {
    patch({
      sections: [{ label: "市场口碑数据", module: null, filter: {}, pick_notes: 1, pick_variants_per_note: 1 }],
      source: block.value.source ?? { type: "notes_query", module: "", filter: {} },
      heading_template: block.value.heading_template ?? "### {tier} TOP{n}. {title}",
      tier: block.value.tier ?? "",
      label_layout: block.value.label_layout ?? "inline",
    });
  }
}

function disableCardMode() {
  patch({ sections: [] });
}

function addSection() {
  const sections = [...(block.value.sections ?? [])];
  sections.push(
    isPool.value
      ? { label: "", h2: "", required: true, pick_variants: 1 }
      : { label: "", module: null, filter: {}, pick_notes: 1, pick_variants_per_note: 1 },
  );
  patch({ sections });
}

function updateSection(i: number, p: Record<string, any>) {
  const sections = [...(block.value.sections ?? [])];
  sections[i] = { ...sections[i], ...p };
  patch({ sections });
}

function removeSection(i: number) {
  const sections = [...(block.value.sections ?? [])];
  sections.splice(i, 1);
  patch({ sections });
}

function moveSection(i: number, dir: -1 | 1) {
  const sections = [...(block.value.sections ?? [])];
  const j = i + dir;
  if (j < 0 || j >= sections.length) return;
  [sections[i], sections[j]] = [sections[j], sections[i]];
  patch({ sections });
}

/** 小节的筛选值 —— 卡片主推小节沿用块级 filter 的单键形态。 */
function sectionFilterValue(sec: any): string {
  const v = Object.values(sec.filter ?? {})[0];
  return v === undefined ? "" : String(v);
}
function sectionFilterKey(sec: any): string {
  return Object.keys(sec.filter ?? {})[0] ?? "素材类型";
}
function setSectionFilter(i: number, key: string, value: string) {
  updateSection(i, { filter: value ? { [key]: value } : {} });
}

// ── 覆盖度检查 ──────────────────────────────────────────────────────
const coverage = ref<any | null>(null);
const coverageLoading = ref(false);

async function runCoverage() {
  coverageLoading.value = true;
  coverage.value = null;
  try {
    const r = await sidecar.client.post("/api/vault/card_coverage", {
      module: block.value.source?.module ?? "",
      filter: block.value.source?.filter ?? {},
      sections: (block.value.sections ?? []).map((x: any) => ({
        label: x.label,
        h2: x.h2 ?? "",
        required: x.required !== false,
      })),
      tier_key: block.value.tier_key ?? "层级标签",
    });
    coverage.value = r.data;
  } catch (e: any) {
    coverage.value = { error: e?.response?.data?.detail ?? e?.message ?? String(e) };
  } finally {
    coverageLoading.value = false;
  }
}

const HEADING_VARS = ["{tier}", "{n}", "{title}", "{brand}", "{model}", "{title_kw}"];

function insertHeadingVar(v: string) {
  patch({ heading_template: (block.value.heading_template ?? "") + v });
}

function patch(p: Record<string, any>) {
  emit("update:modelValue", { ...props.modelValue, ...p });
}
function patchSource(p: Record<string, any>) {
  emit("update:modelValue", {
    ...props.modelValue,
    source: { ...(props.modelValue.source ?? {}), ...p },
  });
}

const KIND_LABELS: Record<string, string> = {
  paragraph: "段落",
  heading: "标题",
  numbered_list: "编号列表",
  hero_brand: "主推",
  competitor_pool: "对比池",
  literal: "文本",
  test_framework: "测试部分",
};

const NUMBER_STYLES = [
  { label: "1.", value: "1." },
  { label: "一、", value: "一、" },
  { label: "无", value: "none" },
];

// friendlyTitle 已下线 —— 区块编辑器顶部大字标题按用户要求移除
// （跟下面 "区块名"/"标题" 输入框内容重复）。eyebrow「区块 N / 类型」
// 单独保留作为定位锚点。

const hasModule = computed(() =>
  ["paragraph", "numbered_list", "competitor_pool"].includes(block.value.kind),
);
const hasName = computed(() =>
  ["paragraph", "numbered_list", "test_framework"].includes(block.value.kind),
);

// ── 高级 · 筛选 (filter) ────────────────────────────────────────────────
// 之前直接把 rows computed 自 source.filter 反向派生，结果「+ 添加」
// 推一行 {key: "", value: ""} 进去，commit 时 trim() 把空 key 行扔掉，
// 反向派生又拿不回新行 → 视觉上点击没反应。
//
// 现在改成本地 ref 维护一份编辑态：
//   - 块切换 / source.filter 由外部变化时 watch 同步过来
//   - 用户操作只改本地 rows，再 debounced 写回 source.filter
// 这样空 key 行可以保留，用户填了 key 才落到真实 dict 里。
interface FilterRow {
  key: string;
  value: string;
}
const filterRows = ref<FilterRow[]>([]);

function rowsFromBlock(b: any): FilterRow[] {
  const f = b?.source?.filter ?? {};
  return Object.entries(f).map(([k, v]) => ({
    key: k,
    value: Array.isArray(v) ? v.join(", ") : String(v ?? ""),
  }));
}

// 只 watch 区块切换，不 watch source.filter —— 本地编辑时 filter 是
// commitFilters 的**输出**，不该再倒灌回 filterRows。否则：用户先选 key
// → commitFilters 因为 value 为空跳过这行 → source.filter = {} → watch
// 把这行从 UI 抹掉，用户感觉"点了 key 就消失"。
//
// 历史上这里有个 same 检查试图避免抹除，但它依赖 incoming.length ===
// filterRows.length，而"用户刚选 key 但 value 还空"恰好就是 length
// 不等的场景，所以 same 永远 false，本地状态被吃掉。
// 按用户要求改为单选 —— 不再支持多行 filter 也不再支持多值。filterRows
// 永远 length === 1。老数据如果有多行/多值，watch 时只保留 first row +
// first value（不破坏 source.filter 已存在的其它条目，但 UI 只暴露一个）。
watch(
  () => block.value?.id,
  () => {
    const rows = rowsFromBlock(block.value);
    if (rows.length === 0) {
      filterRows.value = [{ key: "", value: "" }];
    } else {
      const first = rows[0];
      // 若 value 是多值（逗号分隔），只取第一个
      const v = first.value.split(",")[0]?.trim() ?? "";
      filterRows.value = [{ key: first.key, value: v }];
    }
  },
  { immediate: true },
);

function commitFilters() {
  const out: Record<string, any> = {};
  // 单选模式下只看 filterRows[0]
  const r = filterRows.value[0];
  if (r) {
    const key = r.key.trim();
    const value = r.value.trim();
    if (key && value) {
      out[key] = value;
    }
  }
  patchSource({ filter: out });
}

function updateFilterRow(i: number, p: Partial<FilterRow>) {
  const old = filterRows.value[i];
  const next = { ...old, ...p };
  // 切 key 时清掉 value（不同属性取值集不同，残留旧值会变成无效筛选）
  if (p.key !== undefined && p.key !== old.key) {
    next.value = "";
  }
  filterRows.value[i] = next;
  commitFilters();
}

// ── Vault 属性自动补全 ─────────────────────────────────────────
// 旧的 key 字段是 free-text，用户得自己记得 vault 笔记 frontmatter
// 里写的 attribute 名字（"素材类型" / "核心关键词" 等），打错一个字
// 整个 filter 就失效。改成下拉：调 /api/vault/attributes 拿当前 module
// 范围内出现过的 key 列表，FormSelect 直接展示。
//
// 不挂在 sidecar store 里 cache —— 不同 block 可能 scope 到不同
// module，每个 BlockEditor 实例按自己的 source.module 单独拉一次。
// API 已经返回了 sample_values，这里把它存下来给 value 输入框做
// placeholder 提示（首条 sample 拿来用）。
const sidecar = useSidecar();
interface VaultAttribute {
  key: string;
  note_count: number;
  value_count: number;
  sample_values: string[];
}
const vaultAttrs = ref<VaultAttribute[]>([]);
const attrsLoading = ref(false);
const attrsError = ref<string | null>(null);

const attrKeyOptions = computed(() => {
  // 当前 filterRows 已经选过的 key 也得在选项里（不然切回 BlockEditor
  // 时已选的 key 会显示空白）。合并 vault scan 出来的 + 当前已用的。
  const usedKeys = filterRows.value.map((r) => r.key).filter(Boolean);
  const set = new Set<string>(usedKeys);
  for (const a of vaultAttrs.value) set.add(a.key);
  const opts = Array.from(set).map((k) => {
    const meta = vaultAttrs.value.find((a) => a.key === k);
    const label = meta
      ? `${k}  ·  ${meta.note_count} 篇`
      : `${k}  ·  自定义`;
    return { label, value: k };
  });
  // 首位插「不筛选」—— 单选模式下用户没有"删除筛选行"按钮，得在
  // 下拉里能选回空（覆盖之前选过的 key）
  return [{ label: "不筛选", value: "" }, ...opts];
});

function valueHintFor(key: string): string {
  const meta = vaultAttrs.value.find((a) => a.key === key);
  if (!meta || !meta.sample_values.length) return "如：引言乱象";
  // 取 sample 的前 2 个拼成示例，截断避免 placeholder 过长。
  const head = meta.sample_values.slice(0, 2).join(" / ");
  return `如：${head}`;
}

const VALUE_OPTIONS_THRESHOLD = 20;

function valueOptionsFor(key: string): string[] {
  const meta = vaultAttrs.value.find((a) => a.key === key);
  if (!meta) return [];
  // 后端已经把 sample_values 截到 20；这里只是双保险确认。
  if (meta.value_count > VALUE_OPTIONS_THRESHOLD) return [];
  return meta.sample_values ?? [];
}

async function fetchAttrsRaw(): Promise<VaultAttribute[]> {
  const moduleScope: string | undefined = block.value?.source?.module;
  const r = await sidecar.client.get("/api/vault/attributes", {
    params: moduleScope ? { module: moduleScope } : {},
  });
  return r.data?.attributes ?? [];
}

async function loadVaultAttrs() {
  attrsLoading.value = true;
  attrsError.value = null;
  try {
    vaultAttrs.value = await fetchAttrsRaw();
  } catch (e: any) {
    if (e?.response?.status === 409) {
      // 409 = sidecar 还没有 vault 索引（lifespan 自动扫挂了 / 还没起来 /
      // 用户首次配置 vault 后还没重启）。主动触发一次 scan + retry。
      try {
        await sidecar.client.post("/api/vault/scan", {});
        vaultAttrs.value = await fetchAttrsRaw();
      } catch (inner: any) {
        const status = inner?.response?.status;
        if (status === 400) {
          attrsError.value = "尚未配置素材库 — 请在设置中指定 Vault";
        } else if (status === 404) {
          attrsError.value = "素材库目录不存在 — 请检查设置中的 Vault 路径";
        } else {
          attrsError.value = inner?.message ?? String(inner);
        }
        vaultAttrs.value = [];
      }
    } else {
      attrsError.value = e?.message ?? String(e);
      vaultAttrs.value = [];
    }
  } finally {
    attrsLoading.value = false;
  }
}

// 切换 block 或者 module 变化时重新拉一次。第一次 mount 也会触发
// （immediate: true）。
watch(
  () => [block.value?.id, block.value?.source?.module] as const,
  () => {
    if (
      block.value &&
      ["paragraph", "numbered_list", "competitor_pool"].includes(block.value.kind)
    ) {
      loadVaultAttrs();
    }
  },
  { immediate: true },
);

// ── 高级 · 取值（pick_notes / pick_count） ─────────────────────────────
const pickField = computed(() =>
  block.value.kind === "test_framework" ? "pick_count" : "pick_notes",
);
const rawPick = computed(() => block.value[pickField.value]);
const isRange = computed(
  () => typeof rawPick.value === "object" && rawPick.value?.random_between,
);
const pickMin = computed(() => {
  if (isRange.value) return Number(rawPick.value.random_between?.[0] ?? 1);
  return typeof rawPick.value === "number" ? rawPick.value : 1;
});
const pickMax = computed(() => {
  if (isRange.value)
    return Number(rawPick.value.random_between?.[1] ?? pickMin.value + 1);
  return Math.max(pickMin.value + 1, 2);
});
function setPick(opts: { min?: number; max?: number; range?: boolean }) {
  const min = Math.max(1, opts.min ?? pickMin.value);
  const max = Math.max(min + 1, opts.max ?? pickMax.value);
  const range = opts.range ?? isRange.value;
  patch({
    [pickField.value]: range ? { random_between: [min, max] } : min,
  });
}
function toggleRange(on: boolean) {
  setPick({ range: on, min: pickMin.value, max: Math.max(pickMin.value + 1, pickMax.value) });
}

// ── 高级 · 子素材 / 不重复（paragraph + numbered_list + competitor_pool） ────
// 三种块都从 notes_query 抽笔记，共用同一套"每篇抽几个变体 + 同池不重复"
// 语义。schema 上 numbered_list / competitor_pool 默认 constraints=
// ["unique_notes"] + pick_variants_per_note=1，与历史 sampler 里的硬编码
// 行为一致；UI 上把这两个开关暴露出来允许调整。
const supportsSubMaterial = computed(() =>
  ["paragraph", "numbered_list", "competitor_pool"].includes(block.value.kind),
);
const uniqueNotes = computed(() =>
  (block.value.constraints ?? []).includes("unique_notes"),
);
function toggleUniqueNotes(on: boolean) {
  const set = new Set<string>(block.value.constraints ?? []);
  if (on) set.add("unique_notes");
  else set.delete("unique_notes");
  patch({ constraints: Array.from(set) });
}

// ── 高级 · 链接 / 跟随（depends_on / follow_slot） ─────────────────────
// paragraph：depends_on 是 string[]
// test_framework：follow_slot 是 "id1+id2" 这种字符串
const linkedIds = computed<string[]>(() => {
  const b = block.value;
  if (b.kind === "paragraph") return b.depends_on ?? [];
  if (b.kind === "test_framework") {
    return (b.follow_slot ?? "")
      .split("+")
      .map((s: string) => s.trim())
      .filter(Boolean);
  }
  return [];
});
function setLinked(ids: string[]) {
  if (block.value.kind === "paragraph") {
    patch({ depends_on: ids });
  } else if (block.value.kind === "test_framework") {
    patch({ follow_slot: ids.join("+") });
  }
}
function toggleLink(id: string, on: boolean) {
  const set = new Set(linkedIds.value);
  if (on) set.add(id);
  else set.delete(id);
  setLinked(Array.from(set));
}
const linkButtonText = computed(() => {
  const ids = linkedIds.value;
  if (!ids.length) return "未链接";
  const map = new Map((props.siblings ?? []).map((s) => [s.id, s.label]));
  const labels = ids.map((id) => map.get(id) ?? id);
  const joined = labels.join("、");
  return joined.length > 30 ? joined.slice(0, 28) + "…" : joined;
});

// 链接下拉的开/关 — 简单 v-if，外层 click outside 由父容器的滚动天然吞掉。
const linkOpen = ref(false);

// ── + 关键词 ─────────────────────────────────────────────────────────
function insertKeyword(field: "text") {
  const cur = block.value[field] ?? "";
  patch({ [field]: cur + "{keyword}" });
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!--
      eyebrow only —— 大字 friendlyTitle 标题按用户要求移除（跟下面的
      「区块名」/「标题」输入框内容重复，看着是一个 block 名字写两次）。
      eyebrow「区块 N / 类型」保留作为定位锚点。
    -->
    <div>
      <div
        class="text-[11.5px]"
        :style="{ color: 'var(--ink-3)', letterSpacing: '0.6px' }"
      >
        <template v-if="typeof index === 'number' && total">
          区块 {{ index + 1 }} / {{ total }}
        </template>
        <template v-else>—</template>
        · {{ KIND_LABELS[block.kind] ?? block.kind }}
      </div>
    </div>

    <!-- ── 区块名（paragraph / numbered_list / test_framework） ────── -->
    <FormField v-if="hasName" label="区块名">
      <FormInput
        :model-value="block.label ?? ''"
        debounce="live"
        @update:model-value="(v) => patch({ label: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 标题（hero_brand） ────────────────────────────────────────── -->
    <FormField v-if="block.kind === 'hero_brand'" label="标题">
      <FormInput
        :model-value="block.title ?? ''"
        debounce="live"
        placeholder="如：CEWEY DS18"
        @update:model-value="(v) => patch({ title: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 序号（heading） ──────────────────────────────────────────── -->
    <FormField v-if="block.kind === 'heading'" label="序号">
      <FormInput
        :model-value="block.index ?? ''"
        :width="120"
        debounce="live"
        placeholder="如：一"
        @update:model-value="(v) => patch({ index: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 标题文本（heading）— 带 + 关键词 ───────────────────────────── -->
    <div v-if="block.kind === 'heading'" class="flex flex-col gap-1.5">
      <div class="flex items-center gap-2">
        <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">标题文本</div>
        <span class="flex-1" />
        <button
          type="button"
          class="inline-flex h-[22px] items-center px-2.5 text-[11px]"
          :style="{
            color: 'var(--primary-deep)',
            border: '1px solid rgba(238,106,42,0.3)',
            borderRadius: '11px',
            background: 'transparent',
          }"
          title="光标位置插入 {keyword}"
          @click="insertKeyword('text')"
        >
          + 关键词
        </button>
      </div>
      <FormInput
        :model-value="block.text ?? ''"
        debounce="live"
        placeholder="如：{keyword} 推荐"
        @update:model-value="(v) => patch({ text: String(v ?? '') })"
      />
    </div>

    <!-- ── 编号样式（numbered_list / hero_brand / test_framework） ──── -->
    <FormField
      v-if="['numbered_list', 'hero_brand', 'test_framework'].includes(block.kind)"
      label="编号样式"
    >
      <FormSelect
        :model-value="block.number_style ?? '1.'"
        :options="NUMBER_STYLES"
        :width="120"
        @update:model-value="(v) => patch({ number_style: String(v) })"
      />
    </FormField>

    <!--
      推荐理由前缀 —— 只在 hero_brand 显示。competitor_pool 按用户要求
      不再单独设置，直接继承前面 hero_brand 的 reason_label（assembler
      render.py:195 已经做了 "competitor_pool inherits the preceding
      hero's reason_label" 的回退，UI 隐藏即可，无需后端改动）。
    -->
    <FormField
      v-if="block.kind === 'hero_brand'"
      label="推荐理由前缀"
    >
      <FormInput
        :model-value="block.reason_label ?? '推荐理由：'"
        debounce="live"
        placeholder="如：推荐理由："
        @update:model-value="(v) => patch({ reason_label: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 所属版本（模板声明了版本组才显示）─────────────────────── -->
    <FormField v-if="(versionOptions?.length ?? 0) > 0" label="所属版本">
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="opt in versionOptions"
          :key="opt"
          type="button"
          class="rounded px-2 py-1 text-[11.5px] transition"
          :style="{
            background: blockVersions.includes(opt) ? 'var(--primary-soft)' : 'var(--card-2)',
            border: '1px solid var(--line)',
          }"
          @click="toggleVersion(opt, !blockVersions.includes(opt))"
        >
          {{ opt }}
        </button>
      </div>
      <p class="mt-1 text-[11px] text-ink-3">
        {{
          blockVersions.length
            ? "只在选中的版本里出现"
            : "未选 = 每个版本都出现（公共块）。推荐区的块务必选上版本，漏标会让两个版本的内容混在一起。"
        }}
      </p>
    </FormField>

    <!-- ── 榜单卡片模式（hero_brand / competitor_pool）────────────── -->
    <div
      v-if="block.kind === 'hero_brand' || isPool"
      class="mt-1"
      style="border-top: 1px solid var(--line); padding-top: 10px"
    >
      <div class="flex items-center gap-2">
        <span class="text-[12px] font-medium">榜单卡片</span>
        <span class="text-[11px] text-ink-3">标题行 + 加粗小节，每个点独立随机</span>
        <button
          type="button"
          class="ml-auto text-[11px] text-ink-3 hover:text-ink"
          @click="isCardMode ? disableCardMode() : enableCardMode()"
        >
          {{ isCardMode ? "关闭卡片模式" : "启用卡片模式" }}
        </button>
      </div>

      <template v-if="isCardMode">
        <div
          v-if="isPool && (startRank ?? 0) > 1"
          class="mt-2 rounded px-2 py-1 text-[11px] text-ink-3"
          :style="{ background: 'var(--card-2)' }"
        >
          本池排位从 TOP{{ startRank }} 开始（接续前面的卡）
        </div>

        <FormField label="标题行模板" class="mt-2">
          <FormInput
            :model-value="block.heading_template ?? '### {tier} TOP{n}. {title}'"
            debounce="live"
            @update:model-value="(v) => patch({ heading_template: String(v ?? '') })"
          />
          <div class="mt-1 flex flex-wrap gap-1">
            <button
              v-for="hv in HEADING_VARS"
              :key="hv"
              type="button"
              class="rounded px-1.5 py-0.5 text-[10.5px] text-ink-3 hover:text-ink"
              :style="{ background: 'var(--card-2)' }"
              @click="insertHeadingVar(hv)"
            >
              {{ hv }}
            </button>
          </div>
        </FormField>

        <FormField v-if="block.kind === 'hero_brand'" label="层级标签" class="mt-2">
          <FormInput
            :model-value="block.tier ?? ''"
            debounce="live"
            placeholder="如：国内外知名品牌-综合性能首选"
            @update:model-value="(v) => patch({ tier: String(v ?? '') })"
          />
        </FormField>
        <FormField v-else label="层级标签字段" class="mt-2">
          <FormInput
            :model-value="block.tier_key ?? '层级标签'"
            debounce="live"
            placeholder="竞品卡 frontmatter 里的字段名"
            @update:model-value="(v) => patch({ tier_key: String(v ?? '') })"
          />
        </FormField>

        <FormField label="小节标签排版" class="mt-2">
          <FormSelect
            :model-value="block.label_layout ?? 'inline'"
            :options="[
              { label: '同行：**小节名** ：正文', value: 'inline' },
              { label: '独占一行', value: 'line' },
            ]"
            width="100%"
            @update:model-value="(v) => patch({ label_layout: String(v) })"
          />
        </FormField>

        <div v-if="isPool" class="mt-2">
          <button
            type="button"
            class="text-[11px] text-ink-3 hover:text-ink"
            :disabled="coverageLoading"
            title="看看哪些竞品能上榜、谁缺哪节、型号写歪没有"
            @click="runCoverage"
          >
            {{ coverageLoading ? "检查中…" : "覆盖度检查" }}
          </button>
          <div
            v-if="coverage"
            class="mt-1.5 rounded p-2 text-[11px]"
            :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }"
          >
            <template v-if="coverage.error">
              <span class="text-red">{{ coverage.error }}</span>
            </template>
            <template v-else>
              <div class="mb-1">
                合格竞品 {{ coverage.eligible_count }} / {{ coverage.competitors.length }}
                （目录里 {{ coverage.note_count }} 张卡）
              </div>
              <div
                v-for="c in coverage.competitors"
                :key="c.identity_key"
                class="flex items-center gap-1.5 py-0.5"
              >
                <span :style="{ color: c.eligible ? 'var(--ink-2)' : 'var(--red)' }">
                  {{ c.eligible ? "✓" : "✕" }}
                </span>
                <span>{{ c.title }}</span>
                <span v-if="c.card_count > 1" class="text-ink-3">{{ c.card_count }} 张卡</span>
                <span v-if="c.tiers.length > 1" class="text-ink-3">
                  层级标签不一致：{{ c.tiers.join("/") }}
                </span>
              </div>
              <div
                v-for="r in coverage.rows.filter((x: any) => x.missing_required.length)"
                :key="r.path"
                class="mt-1 text-ink-3"
              >
                {{ r.model }} 缺「{{ r.missing_required.join("、") }}」——
                该卡实有小节：{{ r.h2_present.join("、") || "（无）" }}
              </div>
              <div
                v-for="(x, xi) in coverage.notes_missing_identity"
                :key="'ni' + xi"
                class="mt-1 text-ink-3"
              >
                缺品牌/型号 frontmatter：{{ x }}
              </div>
              <div
                v-for="(x, xi) in coverage.stem_conflicts"
                :key="'sc' + xi"
                class="mt-1"
                :style="{ color: 'var(--red)' }"
              >
                文件名重复「{{ x.stem }}」——重随会串到别的竞品，请改成带型号的文件名
              </div>
              <div
                v-for="(x, xi) in coverage.near_duplicates"
                :key="'nd' + xi"
                class="mt-1 text-ink-3"
              >
                疑似同款各占一个排位：{{ x.join(" / ") }}
              </div>
            </template>
          </div>
        </div>

        <div class="mt-3">
          <div class="mb-1.5 flex items-center gap-2">
            <span class="text-[12px] font-medium">小节</span>
            <span class="text-[11px] text-ink-3">
              {{ isPool ? "对应竞品卡里的 ## 小节" : "每节独立配目录与筛选" }}
            </span>
            <button
              type="button"
              class="ml-auto text-[11px] text-ink-3 hover:text-ink"
              @click="addSection"
            >
              + 添加小节
            </button>
          </div>

          <div
            v-for="(sec, si) in block.sections"
            :key="si"
            class="mb-2 rounded p-2"
            :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }"
          >
            <div class="flex items-center gap-1.5">
              <FormInput
                :model-value="sec.label ?? ''"
                debounce="live"
                :placeholder="isPool ? '小节名' : '小节名（留空 = 上一节的续段）'"
                style="flex: 1"
                @update:model-value="(v) => updateSection(si, { label: String(v ?? '') })"
              />
              <button type="button" class="px-1 text-ink-3 hover:text-ink" title="上移" @click="moveSection(si, -1)">
                <Icon name="arrowUp" :size="11" />
              </button>
              <button type="button" class="px-1 text-ink-3 hover:text-ink" title="下移" @click="moveSection(si, 1)">
                <Icon name="arrowDown" :size="11" />
              </button>
              <button type="button" class="hover:text-red px-1 text-ink-3" title="删除" @click="removeSection(si)">
                <Icon name="trash" :size="11" />
              </button>
            </div>

            <div v-if="isPool" class="mt-1.5 flex flex-wrap items-center gap-2">
              <FormInput
                :model-value="sec.h2 ?? ''"
                debounce="live"
                placeholder="卡片里的 ## 名（留空 = 用小节名匹配）"
                style="width: 210px"
                @update:model-value="(v) => updateSection(si, { h2: String(v ?? '') })"
              />
              <label class="flex items-center gap-1 text-[11.5px]">
                <input
                  type="checkbox"
                  :checked="sec.required !== false"
                  @change="updateSection(si, { required: ($event.target as HTMLInputElement).checked })"
                />
                必需
              </label>
              <label class="flex items-center gap-1 text-[11.5px]">
                候选数
                <FormInput
                  :model-value="String(sec.pick_variants ?? 1)"
                  type="number"
                  style="width: 56px"
                  @update:model-value="(v) => updateSection(si, { pick_variants: Math.max(1, Number(v) || 1) })"
                />
              </label>
            </div>

            <div v-else class="mt-1.5 space-y-1.5">
              <CascadePicker
                :model-value="sec.module ?? ''"
                :dirs="vaultDirs ?? []"
                placeholder="目录（留空 = 用块上的默认目录）"
                @update:model-value="(v) => updateSection(si, { module: String(v ?? '') || null })"
              />
              <div class="flex flex-wrap items-center gap-2">
                <FormInput
                  :model-value="sectionFilterKey(sec)"
                  debounce="live"
                  placeholder="筛选字段"
                  style="width: 110px"
                  @update:model-value="(v) => setSectionFilter(si, String(v ?? '素材类型'), sectionFilterValue(sec))"
                />
                <FormInput
                  :model-value="sectionFilterValue(sec)"
                  debounce="live"
                  placeholder="筛选值，如 市场口碑数据"
                  style="width: 170px"
                  @update:model-value="(v) => setSectionFilter(si, sectionFilterKey(sec), String(v ?? ''))"
                />
                <label class="flex items-center gap-1 text-[11.5px]">
                  抽几篇
                  <FormInput
                    :model-value="String(typeof sec.pick_notes === 'number' ? sec.pick_notes : 1)"
                    type="number"
                    style="width: 56px"
                    @update:model-value="(v) => updateSection(si, { pick_notes: Math.max(1, Number(v) || 1) })"
                  />
                </label>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ── 目录（paragraph / numbered_list / competitor_pool） ──────── -->
    <FormField v-if="hasModule" label="目录">
      <CascadePicker
        :model-value="block.source?.module ?? ''"
        :dirs="vaultDirs ?? []"
        placeholder="选择数据库文件夹"
        @update:model-value="(v) => patchSource({ module: v })"
      />
    </FormField>

    <!-- ── 测试框架/结果目录 + 主推/竞品标签（test_framework） ───────── -->
    <template v-if="block.kind === 'test_framework'">
      <FormField label="测试框架目录">
        <CascadePicker
          :model-value="block.framework_module ?? ''"
          :dirs="vaultDirs ?? []"
          placeholder="选择测试框架笔记目录"
          @update:model-value="(v) => patch({ framework_module: v })"
        />
      </FormField>
      <FormField label="测试结果目录">
        <CascadePicker
          :model-value="block.results_module ?? ''"
          :dirs="vaultDirs ?? []"
          placeholder="选择品牌结果笔记目录"
          @update:model-value="(v) => patch({ results_module: v })"
        />
      </FormField>
      <FormField label="主推槽位标签">
        <FormInput
          :model-value="block.hero_slot ?? '主推'"
          debounce="live"
          placeholder="如：主推"
          @update:model-value="(v) => patch({ hero_slot: String(v ?? '主推') })"
        />
      </FormField>
      <FormField label="竞品槽位标签（逗号分隔）">
        <FormInput
          :model-value="(block.competitor_slots ?? ['竞品A', '竞品B']).join(', ')"
          debounce="blur"
          placeholder="如：竞品A, 竞品B"
          @update:model-value="(v) =>
            patch({
              competitor_slots: String(v ?? '')
                .split(/[,，、]/)
                .map((s) => s.trim())
                .filter(Boolean),
            })
          "
        />
      </FormField>
    </template>

    <!-- ── literal 文本 ─────────────────────────────────────────────── -->
    <div v-if="block.kind === 'literal'" class="flex flex-col gap-1.5">
      <div class="flex items-center gap-2">
        <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">固定文本</div>
        <span class="flex-1" />
        <button
          type="button"
          class="inline-flex h-[22px] items-center px-2.5 text-[11px]"
          :style="{
            color: 'var(--primary-deep)',
            border: '1px solid rgba(238,106,42,0.3)',
            borderRadius: '11px',
          }"
          @click="insertKeyword('text')"
        >
          + 关键词
        </button>
      </div>
      <textarea
        :value="block.text ?? ''"
        rows="6"
        class="font-serif-cn w-full bg-card-2 px-3 py-2 text-[12.5px] outline-none focus:bg-card-white"
        :style="{
          minHeight: '120px',
          borderRadius: 'var(--radius-inner)',
          border: '1px solid var(--line)',
        }"
        @blur="(e) => patch({ text: (e.target as HTMLTextAreaElement).value })"
      />
    </div>

    <!-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ -->
    <!-- ── 高级设置（paragraph / numbered_list / competitor_pool / test_framework） ── -->
    <!-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ -->
    <template
      v-if="['paragraph', 'numbered_list', 'competitor_pool', 'test_framework'].includes(block.kind)"
    >
      <div :style="{ height: '1px', background: 'var(--line)', margin: '4px 0' }" />

      <div class="font-display text-[13px] font-semibold">
        {{
          ({
            paragraph: '段落高级设置',
            numbered_list: '列表高级设置',
            competitor_pool: '对比池高级设置',
            test_framework: '测试部分高级设置',
          } as Record<string, string>)[block.kind] ?? '高级设置'
        }}
      </div>

      <!-- ── 筛选（paragraph / numbered_list / competitor_pool） ───── -->
      <template v-if="block.kind !== 'test_framework'">
        <div class="flex items-center justify-between">
          <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">筛选</div>
          <!--
            状态条 —— 拉取属性中 / 失败 / 无属性。成功且非空就不显示。
            把 vault 没扫描的语义讲清楚，比一个空下拉强。
          -->
          <div
            v-if="attrsLoading"
            class="text-[10.5px]"
            :style="{ color: 'var(--ink-4)' }"
          >读取属性…</div>
          <div
            v-else-if="attrsError"
            class="text-[10.5px]"
            :style="{ color: 'var(--red)' }"
            :title="attrsError"
          >{{ attrsError }}</div>
          <div
            v-else-if="!vaultAttrs.length"
            class="text-[10.5px]"
            :style="{ color: 'var(--ink-4)' }"
          >当前范围未发现属性</div>
        </div>
        <!--
          单选筛选 —— 按用户要求改为只有一行 key + value 下拉。原来支持
          多行 filter + 每行 value 多选（checkbox-style MultiValuePicker），
          被用户判定为"容易出错"+"UI 跟应用其它下拉不一致"。
          - key 走 FormSelect（含「不筛选」首选项，用户能清掉）
          - value 当有候选值时走 FormSelect（跟 key 同款下拉），
            没候选值（vault 高基数 / 未扫）时回退 FormInput 兜底
          - 不再有 添加 / 删除 按钮
        -->
        <div class="flex items-center gap-2">
          <div class="flex-[2]" :style="{ minWidth: '0' }">
            <FormSelect
              :model-value="filterRows[0]?.key ?? ''"
              :options="attrKeyOptions"
              placeholder="选择属性…"
              width="100%"
              @update:model-value="(v) => updateFilterRow(0, { key: String(v) })"
            />
          </div>
          <div class="flex-[3]" :style="{ minWidth: '0' }">
            <FormSelect
              v-if="filterRows[0]?.key && valueOptionsFor(filterRows[0].key).length > 0"
              :model-value="filterRows[0]?.value ?? ''"
              :options="valueOptionsFor(filterRows[0].key).map((v) => ({ label: v, value: v }))"
              placeholder="选择值…"
              width="100%"
              @update:model-value="(v) => updateFilterRow(0, { value: String(v) })"
            />
            <FormInput
              v-else
              :model-value="filterRows[0]?.value ?? ''"
              :placeholder="valueHintFor(filterRows[0]?.key ?? '')"
              :disabled="!filterRows[0]?.key"
              @update:model-value="(v) => updateFilterRow(0, { value: String(v) })"
            />
          </div>
        </div>
      </template>

      <!-- ── 取值 / 测试项数量 ──────────────────────────────────────── -->
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
        {{ block.kind === 'test_framework' ? '测试项数量' : '取值' }}
      </div>
      <div class="flex flex-wrap items-center gap-3 text-[12.5px]">
        <span :style="{ color: 'var(--ink-2)' }">素材数量：</span>
        <FormInput
          type="number"
          :model-value="pickMin"
          :width="100"
          @update:model-value="(v) => setPick({ min: Math.max(1, Number(v) || 1) })"
        />
        <label class="inline-flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            :checked="isRange"
            @change="(e) => toggleRange((e.target as HTMLInputElement).checked)"
          />
          <span>启用随机区间</span>
        </label>
        <template v-if="isRange">
          <span :style="{ color: 'var(--ink-2)' }">最多：</span>
          <FormInput
            type="number"
            :model-value="pickMax"
            :width="100"
            @update:model-value="(v) => setPick({ max: Math.max(pickMin + 1, Number(v) || pickMin + 1) })"
          />
        </template>
      </div>

      <!-- ── 子素材 + 不重复（paragraph + numbered_list） ─────────── -->
      <template v-if="supportsSubMaterial">
        <div class="flex flex-wrap items-center gap-3 text-[12.5px]">
          <span :style="{ color: 'var(--ink-2)' }">子素材随机数量：</span>
          <FormInput
            type="number"
            :model-value="block.pick_variants_per_note ?? 1"
            :width="100"
            @update:model-value="(v) => patch({ pick_variants_per_note: Math.max(1, Number(v) || 1) })"
          />
        </div>
        <label class="inline-flex cursor-pointer items-center gap-1.5 text-[12.5px]">
          <input
            type="checkbox"
            :checked="uniqueNotes"
            @change="(e) => toggleUniqueNotes((e.target as HTMLInputElement).checked)"
          />
          <span>不重复素材</span>
          <span class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
            {{
              block.kind === 'numbered_list' ? '（同列表内不抽中重复笔记）'
              : block.kind === 'competitor_pool' ? '（同对比池内不抽中重复竞品）'
              : '（父子段落不复用同一素材）'
            }}
          </span>
        </label>
      </template>

      <!-- ── 链接（paragraph） / 跟随区块（test_framework） ─────────── -->
      <template
        v-if="['paragraph', 'test_framework'].includes(block.kind)"
      >
        <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
          {{ block.kind === 'paragraph' ? '链接' : '跟随区块' }}
        </div>
        <div class="relative">
          <button
            type="button"
            class="flex w-full items-center justify-between gap-2 px-3 py-2 text-[12.5px]"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-inner)',
              color: linkedIds.length ? 'var(--ink)' : 'var(--ink-3)',
            }"
            @click="linkOpen = !linkOpen"
          >
            <span class="truncate text-left">{{ linkButtonText }}</span>
            <Icon name="arrowDown" :size="12" />
          </button>
          <!--
            下拉皮肤对齐 native <select>：cream 底 + dark hover row。
            选中行用 primary-soft 提示，已勾选项右边补一个 ✓。
          -->
          <div
            v-if="linkOpen"
            class="absolute z-10 mt-1 max-h-[240px] w-full overflow-y-auto p-1.5"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-inner)',
              boxShadow: '0 6px 18px rgba(var(--shadow-rgb),0.10)',
            }"
            @click.stop
          >
            <div
              v-if="!siblings || siblings.length === 0"
              class="px-2 py-1 text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              （无可用区块）
            </div>
            <button
              v-for="s in siblings"
              :key="s.id"
              type="button"
              class="link-row flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left text-[12.5px]"
              :style="{
                borderRadius: '6px',
                background: linkedIds.includes(s.id) ? 'var(--primary-soft)' : 'transparent',
                color: linkedIds.includes(s.id) ? 'var(--primary-deep)' : 'var(--ink)',
              }"
              @click="toggleLink(s.id, !linkedIds.includes(s.id))"
            >
              <span class="flex-1 truncate">{{ s.label }}</span>
              <Icon
                v-if="linkedIds.includes(s.id)"
                name="check"
                :size="11"
                :style="{ color: 'var(--primary-deep)' }"
              />
            </button>
            <div class="flex justify-end pt-1">
              <button
                type="button"
                class="px-2 py-1 text-[11px]"
                :style="{ color: 'var(--ink-3)' }"
                @click="linkOpen = false"
              >
                完成
              </button>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- ── 删除此区块 ─────────────────────────────────────────────── -->
    <div :style="{ height: '1px', background: 'var(--line)', margin: '4px 0' }" />
    <button
      type="button"
      class="w-full px-4 py-2 text-[13px]"
      :style="{
        color: 'var(--red)',
        background: 'transparent',
        border: '1px solid rgba(194,92,77,0.32)',
        borderRadius: '8px',
      }"
      @click="emit('delete')"
    >
      删除此区块
    </button>
  </div>
</template>

<style scoped>
/*
 * 链接 / 跟随区块下拉的 hover 行 —— 对齐原生 <select> 的深色 hover：
 * 任意行 hover 时翻成 --dark 底 + cream 字，覆盖选中态的 primary-soft。
 * 用 !important 是因为行的内联 :style 优先级比类高，否则压不住。
 */
.link-row:hover {
  background: var(--dark) !important;
  color: var(--card) !important;
}
.link-row:hover :deep(svg) {
  color: var(--card) !important;
}
</style>
