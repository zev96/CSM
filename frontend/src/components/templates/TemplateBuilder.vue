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
  blocks.value.push(blankBlock(kind));
  selectedBlockIndex.value = blocks.value.length - 1;
}
function moveBlock(i: number, dir: -1 | 1) {
  const j = i + dir;
  if (j < 0 || j >= blocks.value.length) return;
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

async function save() {
  const err = validate();
  if (err) {
    toast.warn(err);
    return;
  }
  saving.value = true;
  const body: any = {
    ...loadedRaw.value,
    id: tplId.value.trim(),
    name: tplName.value.trim(),
    product: tplProduct.value.trim(),
    template_type: tplType.value || null,
    default_skill_id: tplDefaultSkillId.value || null,
    version_groups: versionGroups.value,
    blocks: blocks.value,
  };
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
    if (Array.isArray(detail)) {
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
          <Pill>{{ blocks.length }}</Pill>
        </div>
        <div v-if="!blocks.length" class="py-4 text-[12px] text-ink-3 text-center">
          点左侧添加第一个块
        </div>
        <ul
          v-else
          class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1"
        >
          <li
            v-for="(b, i) in blocks"
            :key="i"
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
                {{ blockTitle(b) }}
              </span>
            </div>
            <div class="mt-1.5 flex justify-end gap-0.5 opacity-60">
              <button
                type="button"
                class="px-1 hover:opacity-100"
                title="上移"
                :disabled="i === 0"
                @click.stop="moveBlock(i, -1)"
              >
                <Icon name="arrowUp" :size="11" />
              </button>
              <button
                type="button"
                class="px-1 hover:opacity-100"
                title="下移"
                :disabled="i === blocks.length - 1"
                @click.stop="moveBlock(i, 1)"
              >
                <Icon name="arrowDown" :size="11" />
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
