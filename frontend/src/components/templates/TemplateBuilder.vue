<script setup lang="ts">
/**
 * Template builder — 3-pane layout:
 *   left: kind picker (7 BlockKinds)
 *   middle: ordered block list with reorder + delete
 *   right: BlockEditor for the selected block
 *
 * Modes:
 *   - "create" → POST /api/templates
 *   - "edit"   → PATCH /api/templates/{id}
 *
 * Save flow validates client-side that ids are unique + every depends_on
 * resolves; server validates the full pydantic schema and returns 422
 * with field-level errors on failure.
 */
import { computed, onMounted, ref, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import BlockEditor from "./BlockEditor.vue";
import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

const props = defineProps<{
  /** Template id to load and edit. ``null`` opens a fresh-create form. */
  templateId: string | null;
  /** 创建模式下，从外部模态带过来的初值。 */
  initialName?: string;
  initialProduct?: string;
}>();
const emit = defineEmits<{
  (e: "saved", id: string): void;
  (e: "cancel"): void;
}>();

const sidecar = useSidecar();
const toast = useToast();

const TEMPLATE_TYPES = [
  { label: "导购文", value: "导购文" },
  { label: "对比文", value: "对比文" },
  { label: "单品文", value: "单品文" },
  { label: "长文", value: "长文" },
];

// kind → 中文友好名 — 结构面板 fallback；左侧 KIND_PICKER 已经有 label
// 但 kind 默认 fallback 用这个 map 更直接。
const KIND_LABELS: Record<string, string> = {
  paragraph: "段落",
  heading: "标题",
  numbered_list: "编号列表",
  hero_brand: "主推",
  competitor_pool: "对比池",
  literal: "字面量内容",
  test_framework: "测试部分",
};

function blockTitle(b: any): string {
  return (
    b.label ||
    b.title ||
    (b.kind === "heading" || b.kind === "literal" ? b.text : "") ||
    KIND_LABELS[b.kind] ||
    b.kind
  );
}

const KIND_PICKER = [
  { kind: "heading", label: "标题", icon: "fileText" },
  { kind: "paragraph", label: "段落", icon: "edit" },
  { kind: "numbered_list", label: "编号列表", icon: "library" },
  { kind: "literal", label: "字面量", icon: "fileText" },
  { kind: "hero_brand", label: "主推品牌", icon: "zap" },
  { kind: "competitor_pool", label: "竞品池", icon: "trending" },
  { kind: "test_framework", label: "测试框架", icon: "radar" },
];

const tplId = ref("");
const tplName = ref("");
const tplProduct = ref("");
const tplType = ref<string | null>("导购文");
const tplDefaultSkillId = ref<string | null>(null);
const blocks = ref<any[]>([]);
// 结构版本组（PR3 会在头部加编辑 UI；PR1 先保证加载→保存不丢）。
const versionGroups = ref<any[]>([]);
// 加载时的原始模板对象 —— save() 以它为底再覆盖已知字段，防止这个编辑器
// 不认识的模板级字段在保存时被静默抹掉。
const loadedRaw = ref<Record<string, any>>({});

const selectedBlockIndex = ref<number>(-1);
const saving = ref(false);
const loading = ref(false);

const skills = ref<Array<{ id: string; name: string }>>([]);
const vaultDirs = ref<string[]>([]);
const skillOptions = computed(() => [
  { label: "无", value: "" },
  ...skills.value.map((s) => ({ label: s.name, value: s.id })),
]);

const isEdit = computed(() => Boolean(props.templateId));

// ── 结构版本 ────────────────────────────────────────────────────────
/** v1 只管理一个版本组（后端 schema 支持多组）。 */
const versionGroup = computed<any | null>(() => versionGroups.value[0] ?? null);
const versionOptions = computed<string[]>(() => versionGroup.value?.options ?? []);
/** 结构面板的版本视图；"" = 全部。5 个版本 × 每版本几块会让扁平列表膨胀。 */
const viewVersion = ref("");
const newVersionName = ref("");

const visibleIndexes = computed<number[]>(() => {
  if (!viewVersion.value) return blocks.value.map((_, i) => i);
  return blocks.value
    .map((b, i) => ({ b, i }))
    .filter(({ b }) => !b.versions?.length || b.versions.includes(viewVersion.value))
    .map(({ i }) => i);
});

function ensureVersionGroup() {
  if (!versionGroups.value.length) {
    versionGroups.value.push({
      id: "rec_ver",
      label: "推荐区版本",
      options: [],
      disabled_options: [],
    });
  }
  return versionGroups.value[0];
}

function addVersionOption() {
  const name = newVersionName.value.trim();
  if (!name) return;
  const g = ensureVersionGroup();
  if (g.options.includes(name)) {
    toast.warn("已有同名版本");
    return;
  }
  g.options.push(name);
  newVersionName.value = "";
}

function removeVersionOption(name: string) {
  const g = versionGroup.value;
  if (!g) return;
  g.options = g.options.filter((o: string) => o !== name);
  g.disabled_options = (g.disabled_options ?? []).filter((o: string) => o !== name);
  // 块上的悬空标签一并清掉，否则保存时 422
  for (const b of blocks.value) {
    if (b.versions?.length) b.versions = b.versions.filter((v: string) => v !== name);
  }
  if (viewVersion.value === name) viewVersion.value = "";
  if (!g.options.length) versionGroups.value = [];
}

function toggleVersionEnabled(name: string) {
  const g = versionGroup.value;
  if (!g) return;
  const off = new Set<string>(g.disabled_options ?? []);
  if (off.has(name)) off.delete(name);
  else if (g.options.length - off.size > 1) off.add(name);
  else toast.warn("至少要留一个可用版本");
  g.disabled_options = [...off];
}

function isVersionDisabled(name: string): boolean {
  return (versionGroup.value?.disabled_options ?? []).includes(name);
}

// ── 结构检查 ────────────────────────────────────────────────────────
const lintIssues = ref<any[]>([]);
const linting = ref(false);

async function runLint(silent = false) {
  if (!blocks.value.length) return;
  linting.value = true;
  try {
    const r = await sidecar.client.post("/api/templates/lint", buildBody());
    lintIssues.value = r.data.issues ?? [];
    if (!silent && !lintIssues.value.length) toast.success("结构检查通过");
  } catch (e: any) {
    if (!silent) toast.error(`结构检查失败：${e?.message ?? e}`);
  } finally {
    linting.value = false;
  }
}

function blankBlock(kind: string): any {
  // Minimal valid skeleton per kind. Saves invariant pydantic checks
  // when the user adds and immediately saves without filling in.
  const id = `${kind}_${Date.now().toString(36).slice(-4)}`;
  switch (kind) {
    case "heading":
      return { kind, id, level: 2, index: "", text: "标题占位" };
    case "paragraph":
      return {
        kind,
        id,
        label: "段落",
        source: { type: "notes_query", module: "", filter: {} },
        pick_notes: 1,
        pick_variants_per_note: 1,
        constraints: [],
        depends_on: [],
        children: [],
      };
    case "numbered_list":
      return {
        kind,
        id,
        label: "列表",
        source: { type: "notes_query", module: "", filter: {} },
        pick_notes: 3,
        pick_variants_per_note: 1,
        // 编号列表默认勾上"不重复素材"——历史行为是 sampler 里硬编码
        // constraints=["unique_notes"]，现在把它显式放进 block，UI 才能
        // 暴露开关同时保持兼容。
        constraints: ["unique_notes"],
        number_style: "1.",
        item_separator: "\n\n",
      };
    case "literal":
      return { kind, id, text: "字面量内容" };
    case "hero_brand":
      return {
        kind,
        id,
        title: "主推",
        reason_label: "推荐理由：",
        number_style: "1.",
      };
    case "competitor_pool":
      // 历史默认是 brand_pool，但 sampler 里 competitor_pool 只接受
      // notes_query（assert isinstance(source, NotesQuerySource)），导致用户
      // 加完块直接生成会撞 AssertionError。BlockEditor 也只暴露目录/筛选/
      // 取值三个 notes_query 字段，所以默认就改成 notes_query 才能一路走通。
      return {
        kind,
        id,
        source: { type: "notes_query", module: "", filter: {} },
        pick_notes: 2,
        pick_variants_per_note: 1,
        // 同 numbered_list — 显式暴露 schema 里新加的 constraints，保持
        // 历史默认 unique_notes（同一池子里不抽中两次同一篇竞品笔记）。
        constraints: ["unique_notes"],
        reason_label: "推荐理由：",
      };
    case "test_framework":
      return {
        kind,
        id,
        label: "测试",
        framework_module: "",
        results_module: "",
        follow_slot: "",
        pick_count: 3,
        hero_slot: "主推",
        competitor_slots: ["竞品A", "竞品B"],
        number_style: "1.",
        constraints: ["unique_notes"],
      };
  }
  return { kind, id };
}

function addBlock(kind: string) {
  const b = blankBlock(kind);
  // 在某个版本视图下新建的块自动带上该版本标签 —— 漏标是「版本统一」最
  // 容易翻车的地方（一个块漏标就会同时出现在所有版本里），这是最便宜的
  // 一道防线。
  if (viewVersion.value) b.versions = [viewVersion.value];
  blocks.value.push(b);
  selectedBlockIndex.value = blocks.value.length - 1;
}

/** 版本视图下相邻的真实下标 —— 过滤视图里「上移」应该跨过隐藏块。 */
function neighborIndex(i: number, dir: -1 | 1): number | null {
  const list = visibleIndexes.value;
  const pos = list.indexOf(i);
  if (pos < 0) return null;
  const target = list[pos + dir];
  return target === undefined ? null : target;
}

function moveBlock(i: number, dir: -1 | 1) {
  // 过滤视图里 v-for 遍历的是子集；下标必须先映射回真实数组，否则会移错块。
  const j = neighborIndex(i, dir);
  if (j === null) return;
  const tmp = blocks.value[i];
  blocks.value[i] = blocks.value[j];
  blocks.value[j] = tmp;
  if (selectedBlockIndex.value === i) selectedBlockIndex.value = j;
  else if (selectedBlockIndex.value === j) selectedBlockIndex.value = i;
}

function deleteBlock(i: number) {
  blocks.value.splice(i, 1);
  if (selectedBlockIndex.value >= blocks.value.length) {
    selectedBlockIndex.value = blocks.value.length - 1;
  }
}

function newBlockId(kind: string): string {
  let id = `${kind}_${Math.random().toString(36).slice(2, 6)}`;
  const taken = new Set(blocks.value.map((b) => b.id));
  while (taken.has(id)) id = `${kind}_${Math.random().toString(36).slice(2, 6)}`;
  return id;
}

/** 把块复制到另一个版本。必须重造 id，否则撞后端的 duplicate-id 校验。 */
function copyBlockToVersion(i: number, version: string) {
  const src = blocks.value[i];
  const copy = JSON.parse(JSON.stringify(src));
  copy.id = newBlockId(copy.kind);
  copy.versions = [version];
  blocks.value.splice(i + 1, 0, copy);
  selectedBlockIndex.value = i + 1;
  toast.success(`已复制到「${version}」`);
}

/** 追加一个接续竞品池（深浅双池：TOP2-3 详细 + TOP4-10 简略）。 */
function addContinuationPool(i: number) {
  const src = blocks.value[i];
  const pool: any = blankBlock("competitor_pool");
  pool.id = newBlockId("competitor_pool");
  pool.source = JSON.parse(JSON.stringify(src.source ?? {}));
  pool.heading_template = src.heading_template;
  pool.label_layout = src.label_layout;
  pool.card_separator = src.card_separator;
  pool.tier_key = src.tier_key;
  pool.sections = [];        // 浅结构由用户自己配
  pool.versions = [...(src.versions ?? [])];
  pool.version_group = src.version_group ?? null;
  blocks.value.splice(i + 1, 0, pool);
  selectedBlockIndex.value = i + 1;
}

/** 该竞品池的排位起点 —— 主推卡占 TOP1，前面的池各占各的数量。 */
function poolStartRank(index: number): number {
  let n = 1;
  for (let k = 0; k < index; k++) {
    const b = blocks.value[k];
    if (b.kind === "heading") n = 1;
    else if (b.kind === "hero_brand") n = (b.sections?.length ? 1 : n) + 1;
    else if (b.kind === "competitor_pool") {
      const c = typeof b.pick_notes === "number" ? b.pick_notes : (b.pick_notes?.random_between?.[1] ?? 0);
      n += c;
    }
  }
  return n;
}

async function loadSkills() {
  try {
    const r = await sidecar.client.get("/api/skills");
    skills.value = r.data.skills ?? [];
  } catch {
    skills.value = [];
  }
}

async function loadVaultDirs() {
  // 失败/空 vault 都退到空数组 —— 选择器自己有「先去设置里指定 Vault」提示。
  try {
    const r = await sidecar.client.get("/api/vault/dirs");
    vaultDirs.value = r.data.dirs ?? [];
  } catch {
    vaultDirs.value = [];
  }
}

async function loadTemplate(id: string) {
  loading.value = true;
  try {
    const r = await sidecar.client.get(`/api/templates/${id}`);
    tplId.value = r.data.id;
    tplName.value = r.data.name;
    tplProduct.value = r.data.product;
    tplType.value = r.data.template_type ?? null;
    tplDefaultSkillId.value = r.data.default_skill_id ?? null;
    // 模板级字段透传：save() 只手拼它认识的字段，不透传的话在这个编辑器里
    // 存一次就会把 version_groups 这类字段抹掉（PATCH 是整体替换）。
    loadedRaw.value = r.data ?? {};
    versionGroups.value = r.data.version_groups ?? [];
    blocks.value = r.data.blocks ?? [];
    if (blocks.value.length > 0) selectedBlockIndex.value = 0;
  } catch (e: any) {
    toast.error(`加载模板失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  } finally {
    loading.value = false;
  }
}

function slugifyId(name: string): string {
  // 名字 → 安全 slug：小写、空白/特殊字符变 -，首尾去 -。CJK 字符保留，
  // 后端 id 是字符串，不要求 ASCII。最长截到 28 字以避免文件名过长。
  const base =
    name
      .trim()
      .toLowerCase()
      .replace(/[\s/\\:*?"<>|.,;!@#$%^&()+=`~[\]{}]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 28) || "tpl";
  const suffix = Date.now().toString(36).slice(-4);
  return `${base}-${suffix}`;
}

function validate(): string | null {
  if (!tplName.value.trim()) return "模板名不能为空";
  if (!tplProduct.value.trim()) return "产品（product）字段必填";
  if (!isEdit.value && !tplId.value.trim()) {
    tplId.value = slugifyId(tplName.value);
  }
  if (!tplId.value.trim()) return "模板 ID 生成失败，请改下模板名";
  if (blocks.value.length === 0) return "至少添加 1 个 block";
  const ids = new Set<string>();
  for (const b of blocks.value) {
    if (!b.id) return `存在缺 id 的 block（kind=${b.kind}）`;
    if (ids.has(b.id)) return `block id 重复：${b.id}`;
    ids.add(b.id);
  }
  // depends_on resolves to known paragraph id
  const paragraphIds = new Set(
    blocks.value.filter((b) => b.kind === "paragraph").map((b) => b.id),
  );
  for (const b of blocks.value) {
    if (b.kind !== "paragraph") continue;
    for (const dep of b.depends_on ?? []) {
      if (!paragraphIds.has(dep)) {
        return `block ${b.id} 的 depends_on 引用了未知 paragraph id：${dep}`;
      }
    }
  }
  return null;
}

function buildBody(): any {
  return {
    // 以加载时的原始模板为底 —— PATCH 是整体替换，不透传的话这个编辑器
    // 不认识的模板级字段存一次就没了。
    ...loadedRaw.value,
    id: tplId.value.trim(),
    name: tplName.value.trim(),
    product: tplProduct.value.trim(),
    template_type: tplType.value || null,
    default_skill_id: tplDefaultSkillId.value || null,
    version_groups: versionGroups.value,
    blocks: blocks.value,
  };
}

async function save() {
  const err = validate();
  if (err) {
    toast.warn(err);
    return;
  }
  saving.value = true;
  const body: any = buildBody();
  try {
    if (isEdit.value) {
      await sidecar.client.patch(`/api/templates/${props.templateId}`, body);
      toast.success(`已保存：${body.id}`);
    } else {
      await sidecar.client.post("/api/templates", body);
      toast.success(`已创建：${body.id}`);
    }
    emit("saved", body.id);
  } catch (e: any) {
    const detail = e?.response?.data?.detail;
    if (detail?.issues) {
      // 结构 lint 拦下（跨版本引用之类）——把问题列进面板，别只弹个 toast
      lintIssues.value = detail.issues;
      const first = detail.issues.find((i: any) => i.level === "error");
      toast.error(`结构检查未通过：${first?.message ?? detail.message}`);
    } else if (Array.isArray(detail)) {
      // Pydantic validation errors come as arrays — surface the first one.
      const first = detail[0];
      toast.error(`字段错误（${first.loc?.join(".")}）：${first.msg}`);
    } else {
      toast.error(`保存失败：${detail ?? e?.message ?? e}`);
    }
  } finally {
    saving.value = false;
  }
}

watch(
  () => props.templateId,
  (id) => {
    if (id) {
      loadTemplate(id);
    } else {
      // 从「编辑 A」切到「新建」时必须清掉 A 的模板级字段，否则 version_groups
      // 会被带进新模板。
      loadedRaw.value = {};
      versionGroups.value = [];
      // Fresh-create defaults — name + product 由外部模态传入。
      tplId.value = "";
      tplName.value = props.initialName ?? "";
      tplProduct.value = props.initialProduct ?? "";
      tplType.value = "导购文";
      tplDefaultSkillId.value = null;
      blocks.value = [];
      selectedBlockIndex.value = -1;
    }
  },
  { immediate: true },
);

onMounted(() => {
  loadSkills();
  loadVaultDirs();
});
</script>

<template>
  <!--
    h-full + flex-col 让整页吃掉父容器（TemplatesView 已经是 h-full）。
    header Card 不收缩，下面 3-pane 拿剩余高度并自带 min-h-0，每个面板
    内部各自滚动 —— 中间结构面板的 ul 装在 flex-1 overflow-y-auto 里，
    块多了也只在本面板内滚，不会把整页顶出滚动条。
  -->
  <div class="flex h-full flex-col gap-d">
    <!-- ── Header ──────────────────────────────────────────────────── -->
    <Card class="flex-shrink-0">
      <div class="mb-3 flex items-center justify-between">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 text-[12px]"
          :style="{ color: 'var(--ink-3)' }"
          @click="emit('cancel')"
        >
          <Icon name="arrowLeft" :size="14" />
          返回模板库
        </button>
        <div class="flex gap-2">
          <Btn variant="ghost" small @click="emit('cancel')">取消</Btn>
          <Btn variant="solid" small :disabled="saving" @click="save">
            <Spinner v-if="saving" :size="12" />
            <span>{{ saving ? "保存中…" : "保存" }}</span>
          </Btn>
        </div>
      </div>

      <!--
        4 个字段在 lg 上等宽分布；FormSelect 默认 width:auto 会塌成
        内容宽度，外面套一层 min-w-0 + 让 select 走 width:100% 把它撑满，
        模板名 / 产品 / 类型 / 默认 Skill 才视觉上等宽对齐。
      -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <FormField label="模板名">
          <FormInput v-model="tplName" placeholder="如 导购·吸尘器" />
        </FormField>
        <FormField label="产品 (product)">
          <FormInput v-model="tplProduct" placeholder="如 无线吸尘器" />
        </FormField>
        <FormField label="类型">
          <FormSelect
            :model-value="tplType ?? ''"
            :options="[{ label: '未设置', value: '' }, ...TEMPLATE_TYPES]"
            width="100%"
            @update:model-value="(v) => (tplType = (String(v) || null) as any)"
          />
        </FormField>
        <FormField label="默认 Skill">
          <FormSelect
            :model-value="tplDefaultSkillId ?? ''"
            :options="skillOptions"
            width="100%"
            @update:model-value="(v) => (tplDefaultSkillId = String(v) || null)"
          />
        </FormField>
      </div>

      <!-- 结构版本：一个模板放多套推荐区结构，生成时随机抽一套 -->
      <div class="mt-3 border-t pt-3" style="border-color: var(--line)">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[12px] font-medium">结构版本</span>
          <span class="text-[11px] text-ink-3">
            生成时随机抽一套；主推与竞品永远同版本
          </span>
          <div class="ml-auto flex items-center gap-1.5">
            <FormInput
              v-model="newVersionName"
              placeholder="如 版本1·口碑权威型"
              style="width: 200px"
              @keyup.enter="addVersionOption"
            />
            <Btn variant="ghost" small @click="addVersionOption">添加版本</Btn>
          </div>
        </div>
        <div v-if="versionOptions.length" class="mt-2 flex flex-wrap gap-1.5">
          <span
            v-for="opt in versionOptions"
            :key="opt"
            class="inline-flex items-center gap-1 rounded px-2 py-1 text-[11.5px]"
            :style="{
              background: isVersionDisabled(opt) ? 'transparent' : 'var(--card-2)',
              border: '1px solid var(--line)',
              opacity: isVersionDisabled(opt) ? 0.5 : 1,
            }"
          >
            <span>{{ opt }}</span>
            <button
              type="button"
              class="px-0.5 text-ink-3 hover:text-ink"
              :title="isVersionDisabled(opt) ? '启用（进入抽签池）' : '禁用（素材没铺齐时先别抽中）'"
              @click="toggleVersionEnabled(opt)"
            >
              <Icon :name="isVersionDisabled(opt) ? 'eyeOff' : 'eye'" :size="11" />
            </button>
            <button
              type="button"
              class="px-0.5 text-ink-3 hover:text-red"
              title="删除该版本（块上的标签一并清掉）"
              @click="removeVersionOption(opt)"
            >
              <Icon name="x" :size="11" />
            </button>
          </span>
        </div>
        <p v-else class="mt-1.5 text-[11.5px] text-ink-3">
          没有版本 = 单一结构（与以往一致）。加两个以上版本后，给每个块标上「所属版本」即可。
        </p>
      </div>

      <!-- 结构检查结果 -->
      <div v-if="lintIssues.length" class="mt-3 space-y-1">
        <div
          v-for="(iss, k) in lintIssues"
          :key="k"
          class="rounded px-2.5 py-1.5 text-[11.5px]"
          :style="{
            background: 'var(--card-2)',
            borderLeft: `2px solid ${iss.level === 'error' ? 'var(--red)' : 'var(--amber)'}`,
          }"
        >
          <span class="font-medium">{{ iss.level === "error" ? "错误" : "提醒" }}</span>
          <span v-if="iss.version" class="text-ink-3">（{{ iss.version }}）</span>
          <span class="ml-1">{{ iss.message }}</span>
        </div>
      </div>
    </Card>

    <!-- ── Loading state ──────────────────────────────────────────── -->
    <Card v-if="loading" class="flex-shrink-0">
      <div class="flex items-center gap-2 text-ink-3">
        <Spinner :size="14" /><span>载入中…</span>
      </div>
    </Card>

    <!--
      3-pane editor — 列宽 3 : 4 : 4 (添加块 / 结构 / 区块属性) 平铺整个
      可用宽度。区块属性面板自己内部用 max-width 约束表单，避免横向过长
      导致的输入框被拉伸。
    -->
    <div
      v-else
      class="grid min-h-0 flex-1 grid-cols-1 gap-d lg:grid-cols-[3fr_4fr_4fr]"
    >
      <!-- Kind picker -->
      <Card class="flex min-h-0 flex-col">
        <div class="font-display mb-2 flex-shrink-0 text-[12.5px] font-semibold">添加块</div>
        <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          <button
            v-for="k in KIND_PICKER"
            :key="k.kind"
            type="button"
            class="flex items-center gap-2 px-3 py-2 text-[12px] text-left transition hover:bg-card-2"
            :style="{ borderRadius: 'var(--radius-inner)' }"
            @click="addBlock(k.kind)"
          >
            <Icon :name="k.icon" :size="13" />
            <span>{{ k.label }}</span>
            <Icon name="plus" :size="11" class="ml-auto opacity-60" />
          </button>
        </div>
      </Card>

      <!-- Block list — 中间面板自己滚，不让整页溢出 -->
      <Card class="flex min-h-0 flex-col">
        <div class="mb-2 flex flex-shrink-0 items-center justify-between">
          <div class="font-display text-[12.5px] font-semibold">结构</div>
          <Pill>{{ viewVersion ? visibleIndexes.length + " / " + blocks.length : blocks.length }}</Pill>
          <FormSelect
            v-if="versionOptions.length"
            :model-value="viewVersion"
            :options="[
              { label: '查看：全部版本', value: '' },
              ...versionOptions.map((o) => ({ label: '查看：' + o, value: o })),
            ]"
            :min-width="130"
            @update:model-value="(v) => (viewVersion = String(v))"
          />
          <button
            type="button"
            class="ml-auto text-[11px] text-ink-3 hover:text-ink"
            title="检查版本标签与引用是否自洽"
            :disabled="linting"
            @click="runLint()"
          >
            {{ linting ? "检查中…" : "结构检查" }}
          </button>
        </div>
        <div v-if="!blocks.length" class="py-4 text-[12px] text-ink-3 text-center">
          点左侧添加第一个块
        </div>
        <ul
          v-else
          class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1"
        >
          <li
            v-for="i in visibleIndexes"
            :key="blocks[i].id ?? i"
            class="cursor-pointer px-2.5 py-2 text-[12px] transition"
            :style="{
              borderRadius: 'var(--radius-inner)',
              background: selectedBlockIndex === i ? 'var(--card-2)' : 'transparent',
              border: selectedBlockIndex === i ? '1px solid var(--line)' : '1px solid transparent',
            }"
            @click="selectedBlockIndex = i"
          >
            <div class="flex items-center gap-1.5">
              <span class="font-mono text-[10.5px] text-ink-3 tabular-nums">{{ i + 1 }}.</span>
              <!-- 只显示友好名字，不再露出 paragraph / numbered_list 这类英文 kind ID -->
              <span class="min-w-0 flex-1 truncate font-medium">
                {{ blockTitle(blocks[i]) }}
              </span>
              <span
                v-if="blocks[i].versions?.length"
                class="shrink-0 rounded px-1 text-[10px] text-ink-3"
                :style="{ background: 'var(--card-2)' }"
                :title="'所属版本：' + blocks[i].versions.join('、')"
              >
                {{ blocks[i].versions.length === 1 ? blocks[i].versions[0] : blocks[i].versions.length + " 版本" }}
              </span>
              <span
                v-else-if="versionOptions.length"
                class="shrink-0 text-[10px] text-ink-3"
                title="未标版本 = 每个版本都会出现"
              >
                全部
              </span>
            </div>
            <div class="mt-1.5 flex justify-end gap-0.5 opacity-60">
              <button
                type="button"
                class="px-1 hover:opacity-100"
                title="上移"
                :disabled="neighborIndex(i, -1) === null"
                @click.stop="moveBlock(i, -1)"
              >
                <Icon name="arrowUp" :size="11" />
              </button>
              <button
                type="button"
                class="px-1 hover:opacity-100"
                title="下移"
                :disabled="neighborIndex(i, 1) === null"
                @click.stop="moveBlock(i, 1)"
              >
                <Icon name="arrowDown" :size="11" />
              </button>
              <button
                v-for="opt in versionOptions.filter((o) => !blocks[i].versions?.includes(o))"
                :key="opt"
                type="button"
                class="px-1 text-[10px] hover:opacity-100"
                :title="`复制一份到「${opt}」（新 id）`"
                @click.stop="copyBlockToVersion(i, opt)"
              >
                ⧉{{ opt.slice(0, 3) }}
              </button>
              <button
                v-if="blocks[i].kind === 'competitor_pool' && blocks[i].sections?.length"
                type="button"
                class="px-1 hover:opacity-100"
                title="添加接续池（深浅双池：本池排完由下一池继续编号）"
                @click.stop="addContinuationPool(i)"
              >
                <Icon name="plus" :size="11" />
              </button>
              <button
                type="button"
                class="hover:text-red px-1 hover:opacity-100"
                title="删除"
                @click.stop="deleteBlock(i)"
              >
                <Icon name="trash" :size="11" />
              </button>
            </div>
          </li>
        </ul>
      </Card>

      <!-- Block editor — 同样自滚 -->
      <Card class="flex min-h-0 flex-col">
        <div
          v-if="selectedBlockIndex < 0 || !blocks[selectedBlockIndex]"
          class="text-[12.5px] text-ink-3"
        >
          选中一个块（左侧列表）查看编辑器。
        </div>
        <!--
          右侧面板自滚 + 左右 px-3 给 input focus ring / select 弹层
          留呼吸位 —— 之前只 pr-3，左侧贴边的 input 焦点描边会被
          overflow 容器裁掉一条。
        -->
        <div v-else class="min-h-0 flex-1 overflow-y-auto px-3">
          <BlockEditor
            v-model="blocks[selectedBlockIndex]"
            :index="selectedBlockIndex"
            :total="blocks.length"
            :vault-dirs="vaultDirs"
            :version-options="versionOptions"
            :start-rank="poolStartRank(selectedBlockIndex)"
            :siblings="
              blocks
                .map((b, i) => ({
                  id: b.id,
                  label: blockTitle(b),
                  _i: i,
                }))
                .filter((s) => s._i !== selectedBlockIndex)
                .map(({ id, label }) => ({ id, label }))
            "
            @delete="deleteBlock(selectedBlockIndex)"
          />
        </div>
      </Card>
    </div>
  </div>
</template>
