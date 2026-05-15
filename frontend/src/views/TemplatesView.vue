<script setup lang="ts">
/**
 * 模板库 — V1 设计稿同款：
 *   - header：模板库 caption + 大标题 + 副标题 + 右侧胶囊 tab + 新建按钮
 *   - body：左侧 2 列卡片网格（首张深色 + 橙 blob，其余浅色），右侧预览
 *   - skills tab：右侧改为 md 文件预览（仿 .md 编辑器外观）
 *
 * 数据来自 /api/templates 与 /api/skills；空仓库时退到 V1 设计稿同款示例，
 * UI 不会塌掉。Builder 模式接管整页。
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import TemplateBuilder from "@/components/templates/TemplateBuilder.vue";
import CreateTemplateModal from "@/components/templates/CreateTemplateModal.vue";
import SkillEditModal from "@/components/templates/SkillEditModal.vue";

import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const sidecar = useSidecar();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const { whenReady } = useSidecarReady();

const initialTab = route.query.tab === "skills" ? "skills" : "templates";
const tab = ref<"templates" | "skills">(initialTab);

watch(
  () => route.query.tab,
  (q) => {
    if (q === "skills") tab.value = "skills";
    else if (q === "templates") tab.value = "templates";
  },
);

// Builder mode — null = creating new; <id> = editing; undefined = browsing.
const builderTemplateId = ref<string | null | undefined>(undefined);
const inBuilder = computed(() => builderTemplateId.value !== undefined);
// 创建模式下从模态带入的初值，传给 TemplateBuilder
const builderInitialName = ref("");
const builderInitialProduct = ref("");
const createModalOpen = ref(false);

function openCreateModal() {
  createModalOpen.value = true;
}
function startNewWith(payload: { name: string; product: string }) {
  builderInitialName.value = payload.name;
  builderInitialProduct.value = payload.product;
  builderTemplateId.value = null;
}
function startEdit(id: string) {
  builderInitialName.value = "";
  builderInitialProduct.value = "";
  builderTemplateId.value = id;
}
function exitBuilder() {
  builderTemplateId.value = undefined;
  builderInitialName.value = "";
  builderInitialProduct.value = "";
}
async function onSaved(id: string) {
  exitBuilder();
  await loadTemplates();
  selectedTemplate.value = id;
}

interface Template {
  id: string;
  name: string;
  path?: string;
  /** 槽位数 — 由 blocks.length 推导，列表接口里通常没有 */
  slots?: number;
  /** 标签 — 列表接口若返回 template_type 等可填，否则为空 */
  tags?: string[];
  /** 用过次数 — 后端目前无统计，保持 undefined */
  used?: number;
}
interface Skill {
  id: string;
  name: string;
  desc: string;
  tone?: string;
  uses?: number;
}

// ── V1 设计稿同款示例 — 后端空仓库时兜底 ───────────────────
const FALLBACK_TEMPLATES: Template[] = [
  { id: "_t1", name: "导购 · 场景人群", slots: 6, tags: ["导购", "场景"], used: 142 },
  { id: "_t2", name: "导购 · 科普物品", slots: 8, tags: ["导购", "科普"], used: 96 },
  { id: "_t3", name: "测评 · 长期使用", slots: 5, tags: ["测评", "主观"], used: 71 },
  { id: "_t4", name: "测评 · 横评", slots: 7, tags: ["测评", "数据"], used: 58 },
  { id: "_t5", name: "测评 · 安全合规", slots: 4, tags: ["测评", "母婴"], used: 33 },
  { id: "_t6", name: "投放文 · 软广", slots: 6, tags: ["投放"], used: 24 },
];
const FALLBACK_SKILLS: Skill[] = [
  { id: "_s1", name: "克制 · 克制", desc: "极度克制 · 不超过 1 个感叹号", tone: "克制", uses: 38 },
  { id: "_s2", name: "测评 · 真心话", desc: "第一人称 · 长期使用者", tone: "真实", uses: 27 },
  { id: "_s3", name: "母婴 · 温柔", desc: "安全优先 · 温柔但专业", tone: "温柔", uses: 19 },
  { id: "_s4", name: "极简 · 短句", desc: "句长 ≤ 18 字 · 动词起句", tone: "极简", uses: 12 },
];

// V1 SKILL_DETAILS 同款示例 md
const FALLBACK_SKILL_MD: Record<string, string> = {
  _s1: `# 克制·克制 Skill

你是一位专注于家电品类的资深编辑，风格极度克制。

## 风格约束
- **开头钩子**：用一个具体场景切入，不超过两句
- **段落密度**：每段 80-150 字，信息密度高
- **口语化**：禁止，保持书面语
- **感叹号**：全文不超过 1 个

## 结构约束
- 保留毛坯文的所有 H2 标题
- 不添加新段落，只重写现有段落
- 产品名称保持原样

## 禁止项
- 禁止出现"强烈推荐"、"必买"、"yyds"
- 禁止使用超过 3 个连续形容词
- 禁止反问句开头

## 输出
直接输出润色后的完整正文 Markdown，不加额外说明。`,
  _s2: `# 测评 · 真心话 Skill

你是一个用了三年的真实用户，第一人称视角。

## 风格约束
- **视角**：第一人称，长期使用者
- **诚实度**：必须给出缺点，不能全好评
- **场景感**：每个优缺点配一个真实使用场景

## 结构约束
- 保留原有 H2 结构
- 每款产品必须有"优点"和"不足"两段

## 禁止项
- 禁止"性价比之王"等营销用语
- 禁止省略具体数据

## 输出
直接输出润色后的完整正文 Markdown。`,
  _s3: `# 母婴 · 温柔 Skill

你是一位关注母婴安全的编辑。

## 风格约束
- **安全优先**：所有产品先讲安全合规
- **语气**：温柔但专业，像和闺蜜聊天
- **案例化**：用"我家宝宝"等真实案例

## 禁止项
- 禁止"宝妈必看"等标题党
- 禁止忽略安全警告

## 输出
直接输出润色后的完整正文 Markdown。`,
  _s4: `# 极简 · 短句 Skill

句子控制在 18 字以内。

## 风格约束
- **句长**：不超过 18 字
- **动词开头**：优先用动词起句
- **删形容词**：每句最多 1 个形容词

## 输出
直接输出润色后的完整正文 Markdown。`,
};

// V1 设计稿里 6 槽位的常见名（按顺序，用于真实模板没拉到 detail 时凑数）
const FALLBACK_SLOT_NAMES = [
  "开篇 · 痛点引入",
  "选购维度 · 三件事",
  "横评 · 真实场景",
  "推荐组合 · 按预算 / 按场景",
  "避坑 · 反例",
  "收口 · 一句话总结",
];

const templates = ref<Template[]>([]);
const skills = ref<Skill[]>([]);
const selectedTemplate = ref<string | null>(null);
const selectedSkill = ref<string | null>(null);
const templateDetail = ref<any | null>(null);
const skillDetail = ref<{ body: string; name: string } | null>(null);
const loaded = ref(false);
const loading = ref(false);

// V1 设计稿示例数据，发布前默认不展示 —— 用户主动「加载示例」时才翻到 true，
// 自动 fallback 关掉后，没有真实模板就走真实数据的空态（让用户去新建），
// 而不是塞一屏假数据让人误以为已经预置了模板。FALLBACK_* 数组保留下来给
// 「加载示例」按钮使用。
const demoTemplates = ref(false);
const demoSkills = ref(false);

const displayTemplates = computed<Template[]>(() =>
  demoTemplates.value ? FALLBACK_TEMPLATES : templates.value,
);
const displaySkills = computed<Skill[]>(() =>
  demoSkills.value ? FALLBACK_SKILLS : skills.value,
);

const activeTemplate = computed<Template | null>(() => {
  const list = displayTemplates.value;
  if (!list.length) return null;
  return list.find((t) => t.id === selectedTemplate.value) ?? list[0];
});
const activeSkill = computed<Skill | null>(() => {
  const list = displaySkills.value;
  if (!list.length) return null;
  return list.find((s) => s.id === selectedSkill.value) ?? list[0];
});

async function loadTemplates() {
  loading.value = true;
  try {
    const r = await sidecar.client.get("/api/templates");
    templates.value = r.data.templates ?? [];
    if (templates.value.length && !selectedTemplate.value) {
      selectedTemplate.value = templates.value[0].id;
    }
  } catch (e: any) {
    toast.error(`模板加载失败：${e?.message ?? e}`);
  } finally {
    loading.value = false;
    loaded.value = true;
  }
}

async function loadTemplateDetail(id: string) {
  if (id.startsWith("_")) {
    templateDetail.value = null;
    return;
  }
  try {
    const r = await sidecar.client.get(`/api/templates/${id}`);
    templateDetail.value = r.data;
  } catch {
    templateDetail.value = null;
  }
}

async function loadSkills() {
  loading.value = true;
  try {
    const r = await sidecar.client.get("/api/skills");
    skills.value = r.data.skills ?? [];
    if (skills.value.length && !selectedSkill.value) {
      selectedSkill.value = skills.value[0].id;
    }
  } catch (e: any) {
    toast.error(`Skill 加载失败：${e?.message ?? e}`);
  } finally {
    loading.value = false;
  }
}

async function loadSkillDetail(id: string) {
  if (id.startsWith("_")) {
    skillDetail.value = {
      name: FALLBACK_SKILLS.find((s) => s.id === id)?.name ?? id,
      body: FALLBACK_SKILL_MD[id] ?? "",
    };
    return;
  }
  try {
    const r = await sidecar.client.get(`/api/skills/${id}`);
    skillDetail.value = r.data;
  } catch {
    skillDetail.value = null;
  }
}

async function deleteTemplate(id: string) {
  if (id.startsWith("_")) {
    toast.info("示例模板不可删除");
    return;
  }
  if (!(await confirmDialog(`确定删除模板 ${id}？`, { title: "删除模板" }))) return;
  try {
    await sidecar.client.delete(`/api/templates/${id}`);
    toast.success(`已删除：${id}`);
    selectedTemplate.value = null;
    await loadTemplates();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

function useTemplate(t: Template) {
  if (t.id.startsWith("_")) {
    toast.info("示例模板，先去新建一个真实模板再来用");
    return;
  }
  router.push({ name: "article", query: { template: t.id } });
}

function onEditTemplateClick(t: Template) {
  if (t.id.startsWith("_")) {
    toast.info("示例模板不可编辑，先「新建模板」做一份真实的再来改");
    return;
  }
  startEdit(t.id);
}

function onDeleteTemplateClick(t: Template) {
  if (t.id.startsWith("_")) {
    toast.info("示例模板不可删除");
    return;
  }
  deleteTemplate(t.id);
}

// ── Skill 编辑 / 新建 / 删除 ──────────────────────────────
const skillModalOpen = ref(false);
const skillEditingId = ref<string | null>(null);

function openCreateSkill() {
  skillEditingId.value = null;
  skillModalOpen.value = true;
}

function onEditSkillClick(s: Skill) {
  if (s.id.startsWith("_")) {
    toast.info("示例 Skill 不可编辑，先「新建 Skill」做一份真实的再来改");
    return;
  }
  skillEditingId.value = s.id;
  skillModalOpen.value = true;
}

async function onDeleteSkillClick(s: Skill) {
  if (s.id.startsWith("_")) {
    toast.info("示例 Skill 不可删除");
    return;
  }
  if (!(await confirmDialog(`确定删除 Skill「${s.name}」？`, { title: "删除 Skill" }))) return;
  try {
    await sidecar.client.delete(`/api/skills/${s.id}`);
    toast.success(`已删除：${s.name}`);
    if (selectedSkill.value === s.id) selectedSkill.value = null;
    skillDetail.value = null;
    await loadSkills();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

async function onSkillSaved(id: string) {
  await loadSkills();
  selectedSkill.value = id;
  await loadSkillDetail(id);
}

const slotList = computed<{ label: string; chars: number }[]>(() => {
  // 真实模板：从 blocks 派生
  if (templateDetail.value?.blocks?.length) {
    return templateDetail.value.blocks.map((b: any, i: number) => ({
      label: b.label || b.id || FALLBACK_SLOT_NAMES[i] || `槽位 ${i + 1}`,
      chars: 200 + i * 60,
    }));
  }
  // 示例 / 列表里的模板：用 V1 同款文案凑数
  const n = activeTemplate.value?.slots ?? 6;
  return FALLBACK_SLOT_NAMES.slice(0, Math.min(n, FALLBACK_SLOT_NAMES.length)).map(
    (label, i) => ({ label, chars: 200 + i * 60 }),
  );
});

const slotCount = computed(
  () => templateDetail.value?.blocks?.length ?? activeTemplate.value?.slots ?? 0,
);

watch(selectedTemplate, (id) => {
  if (id) loadTemplateDetail(id);
});
watch(selectedSkill, (id) => {
  if (id) loadSkillDetail(id);
});
watch(tab, async (t) => {
  if (t === "templates" && !templates.value.length && !loaded.value) await loadTemplates();
  if (t === "skills" && !skills.value.length) await loadSkills();
});
watch(activeTemplate, (t) => {
  if (t && selectedTemplate.value !== t.id) selectedTemplate.value = t.id;
});
watch(activeSkill, (s) => {
  if (s && selectedSkill.value !== s.id) selectedSkill.value = s.id;
});

onMounted(async () => {
  try {
    await whenReady();
    await loadTemplates();
    await loadSkills();
  } catch {
    /* already toasted */
  }
});

// 解析 md 为带样式的渲染行 — 严格按 V1 SkillDetail 的简易渲染。
interface MdLine {
  kind: "h1" | "h2" | "li" | "p" | "blank";
  text: string;
}
const skillMdLines = computed<MdLine[]>(() => {
  const md = skillDetail.value?.body ?? "";
  return md.split("\n").map<MdLine>((line) => {
    if (line.startsWith("# ")) return { kind: "h1", text: line.slice(2) };
    if (line.startsWith("## ")) return { kind: "h2", text: line.slice(3) };
    if (line.startsWith("- ")) return { kind: "li", text: line };
    if (line.trim() === "") return { kind: "blank", text: "" };
    return { kind: "p", text: line };
  });
});

const skillFileName = computed(() => {
  const n = activeSkill.value?.name ?? "skill";
  return `${n.replace(/\s/g, "-").toLowerCase()}.md`;
});
</script>

<template>
  <div class="flex h-full flex-col" style="gap: var(--density-gap)">
    <!-- 新建模板模态：只问名字 + 产品，提交后跳进 builder -->
    <CreateTemplateModal
      v-model:open="createModalOpen"
      @submit="startNewWith"
    />

    <!-- 新建 / 编辑 Skill 模态 -->
    <SkillEditModal
      v-model:open="skillModalOpen"
      :skill-id="skillEditingId"
      @saved="onSkillSaved"
    />

    <!-- Builder mode — 整页接管 -->
    <TemplateBuilder
      v-if="inBuilder"
      :template-id="builderTemplateId ?? null"
      :initial-name="builderInitialName"
      :initial-product="builderInitialProduct"
      @saved="onSaved"
      @cancel="exitBuilder"
    />

    <template v-else>
      <!-- header — V1 设计稿同款 -->
      <div class="flex flex-shrink-0 items-start justify-between gap-4">
        <div class="min-w-0">
          <div
            class="text-[11px] font-medium uppercase"
            :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
          >
            模板库
          </div>
          <div
            class="font-display mt-2 font-bold"
            :style="{ fontSize: '30px', letterSpacing: '-0.5px' }"
          >
            {{ tab === "templates" ? "文章模板" : "风格语气" }}
          </div>
          <div class="mt-1 text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
            {{
              tab === "templates"
                ? "模板决定文章的骨架与槽位 —— 写哪些段落、什么顺序、用什么节奏"
                : "Skill 决定写作的语气与收口 —— 同一份骨架可以套不同的 Skill"
            }}
          </div>
        </div>
        <div class="flex flex-shrink-0 items-center gap-2">
          <!-- 胶囊 tab 切换 — V1 hero chip 同款 -->
          <div
            class="flex items-center"
            :style="{
              background: 'var(--card)',
              borderRadius: '999px',
              padding: '4px',
              border: '1px solid var(--line)',
            }"
          >
            <button
              v-for="x in [
                { id: 'templates', label: '结构模板', icon: 'library' },
                { id: 'skills', label: '风格 Skill', icon: 'skills' },
              ]"
              :key="x.id"
              type="button"
              class="inline-flex items-center gap-1.5 transition"
              :style="{
                height: '32px',
                padding: '0 16px',
                borderRadius: '999px',
                fontSize: '12.5px',
                fontWeight: 500,
                background: tab === x.id ? 'var(--dark)' : 'transparent',
                color: tab === x.id ? '#fbf7ec' : 'var(--ink-3)',
              }"
              @click="tab = x.id as any"
            >
              <Icon :name="x.icon" :size="13" />
              {{ x.label }}
            </button>
          </div>
          <Btn
            v-if="tab === 'templates'"
            variant="solid"
            @click="openCreateModal"
          >
            <Icon name="plus" :size="13" />
            <span>新建模板</span>
          </Btn>
          <Btn v-else variant="solid" @click="openCreateSkill">
            <Icon name="plus" :size="13" />
            <span>新建 Skill</span>
          </Btn>
        </div>
      </div>

      <!-- body — 1.4fr 卡片栅格 + 1fr 预览 -->
      <div
        class="grid min-h-0 flex-1"
        :style="{ gridTemplateColumns: '1.4fr 1fr', gap: 'var(--density-gap)' }"
      >
        <!-- ━━━━ 左：卡片网格 ━━━━ -->
        <div
          v-if="tab === 'templates'"
          class="grid auto-rows-min overflow-y-auto pr-1"
          :style="{ gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--density-gap)' }"
        >
          <div
            v-if="loading && !displayTemplates.length"
            class="col-span-2 flex justify-center p-6"
          >
            <Spinner :size="14" />
          </div>
          <button
            v-for="(t, i) in displayTemplates"
            :key="t.id"
            type="button"
            class="text-left transition"
            :style="{ borderRadius: 'var(--radius-card)' }"
            @click="selectedTemplate = t.id"
          >
            <div
              class="relative overflow-hidden p-5"
              :style="{
                minHeight: '168px',
                borderRadius: 'var(--radius-card)',
                background:
                  selectedTemplate === t.id || (!selectedTemplate && i === 0)
                    ? 'var(--dark)'
                    : 'var(--card)',
                border:
                  selectedTemplate === t.id || (!selectedTemplate && i === 0)
                    ? '1px solid transparent'
                    : '1px solid var(--line)',
                color:
                  selectedTemplate === t.id || (!selectedTemplate && i === 0)
                    ? '#fbf7ec'
                    : 'var(--ink)',
                cursor: 'pointer',
              }"
            >
              <!-- 暖色 blob — 当前激活卡用橙、其它每隔 3 张用黄 -->
              <div
                v-if="selectedTemplate === t.id || (!selectedTemplate && i === 0)"
                aria-hidden="true"
                :style="{
                  position: 'absolute',
                  width: '160px',
                  height: '160px',
                  top: '20px',
                  left: '140px',
                  borderRadius: '50%',
                  background: 'var(--primary)',
                  opacity: 0.45,
                  filter: 'blur(40px)',
                  pointerEvents: 'none',
                }"
              />
              <div
                v-else-if="i % 3 === 0"
                aria-hidden="true"
                :style="{
                  position: 'absolute',
                  width: '130px',
                  height: '130px',
                  top: '-30px',
                  left: '150px',
                  borderRadius: '50%',
                  background: 'var(--yellow)',
                  opacity: 0.4,
                  filter: 'blur(36px)',
                  pointerEvents: 'none',
                }"
              />

              <div class="relative flex h-full flex-col">
                <div
                  class="font-display font-bold"
                  :style="{ fontSize: '16px' }"
                >
                  {{ t.name }}
                </div>
                <div
                  class="mt-1 text-[11.5px]"
                  :style="{
                    color:
                      selectedTemplate === t.id || (!selectedTemplate && i === 0)
                        ? 'rgba(255,255,255,0.6)'
                        : 'var(--ink-3)',
                  }"
                >
                  {{
                    [
                      t.slots ? `${t.slots} 槽位` : null,
                      ...(t.tags ?? []),
                    ]
                      .filter(Boolean)
                      .join(" · ") || "—"
                  }}
                </div>
                <div class="flex-1" />
                <div
                  v-if="t.used !== undefined"
                  class="mt-3 text-[11px]"
                  :style="{
                    color:
                      selectedTemplate === t.id || (!selectedTemplate && i === 0)
                        ? 'rgba(255,255,255,0.5)'
                        : 'var(--ink-4)',
                  }"
                >
                  用过
                  <b
                    :style="{
                      color:
                        selectedTemplate === t.id || (!selectedTemplate && i === 0)
                          ? '#fbf7ec'
                          : 'var(--ink)',
                    }"
                    >{{ t.used }}</b
                  >
                  次
                </div>
              </div>
            </div>
          </button>
        </div>

        <!-- skills 卡片网格 -->
        <div
          v-else
          class="grid auto-rows-min overflow-y-auto pr-1"
          :style="{ gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--density-gap)' }"
        >
          <div
            v-if="loading && !displaySkills.length"
            class="col-span-2 flex justify-center p-6"
          >
            <Spinner :size="14" />
          </div>
          <button
            v-for="(s, i) in displaySkills"
            :key="s.id"
            type="button"
            class="text-left transition"
            :style="{ borderRadius: 'var(--radius-card)' }"
            @click="selectedSkill = s.id"
          >
            <div
              class="relative overflow-hidden p-5"
              :style="{
                minHeight: '168px',
                borderRadius: 'var(--radius-card)',
                background:
                  selectedSkill === s.id || (!selectedSkill && i === 0)
                    ? 'var(--dark)'
                    : 'var(--card)',
                border:
                  selectedSkill === s.id || (!selectedSkill && i === 0)
                    ? '1px solid transparent'
                    : '1px solid var(--line)',
                color:
                  selectedSkill === s.id || (!selectedSkill && i === 0)
                    ? '#fbf7ec'
                    : 'var(--ink)',
                cursor: 'pointer',
              }"
            >
              <div
                v-if="selectedSkill === s.id || (!selectedSkill && i === 0)"
                aria-hidden="true"
                :style="{
                  position: 'absolute',
                  width: '160px',
                  height: '160px',
                  top: '20px',
                  left: '140px',
                  borderRadius: '50%',
                  background: 'var(--primary)',
                  opacity: 0.45,
                  filter: 'blur(40px)',
                  pointerEvents: 'none',
                }"
              />
              <div
                v-else-if="i % 3 === 0"
                aria-hidden="true"
                :style="{
                  position: 'absolute',
                  width: '130px',
                  height: '130px',
                  top: '-30px',
                  left: '150px',
                  borderRadius: '50%',
                  background: 'var(--yellow)',
                  opacity: 0.4,
                  filter: 'blur(36px)',
                  pointerEvents: 'none',
                }"
              />

              <div class="relative flex h-full flex-col">
                <div
                  class="font-display font-bold"
                  :style="{ fontSize: '16px' }"
                >
                  {{ s.name }}
                </div>
                <div
                  class="mt-1 text-[11.5px]"
                  :style="{
                    color:
                      selectedSkill === s.id || (!selectedSkill && i === 0)
                        ? 'rgba(255,255,255,0.6)'
                        : 'var(--ink-3)',
                  }"
                >
                  {{ s.desc }}
                </div>
                <div class="flex-1" />
                <div
                  v-if="s.uses !== undefined"
                  class="mt-3 text-[11px]"
                  :style="{
                    color:
                      selectedSkill === s.id || (!selectedSkill && i === 0)
                        ? 'rgba(255,255,255,0.5)'
                        : 'var(--ink-4)',
                  }"
                >
                  用过
                  <b
                    :style="{
                      color:
                        selectedSkill === s.id || (!selectedSkill && i === 0)
                          ? '#fbf7ec'
                          : 'var(--ink)',
                    }"
                    >{{ s.uses }}</b
                  >
                  次
                </div>
              </div>
            </div>
          </button>
        </div>

        <!-- ━━━━ 右：预览 ━━━━ -->
        <Card v-if="tab === 'templates'" class="min-h-0 overflow-y-auto">
          <template v-if="!activeTemplate">
            <div class="text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
              选一个模板查看结构。
            </div>
          </template>
          <template v-else>
            <div class="flex items-center justify-between">
              <div>
                <div
                  class="text-[11px] uppercase"
                  :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
                >
                  预览
                </div>
                <div
                  class="font-display mt-1 font-bold"
                  :style="{ fontSize: '20px' }"
                >
                  {{ activeTemplate.name }}
                </div>
              </div>
              <div class="flex items-center gap-2">
                <Btn
                  variant="ghost"
                  small
                  @click="onDeleteTemplateClick(activeTemplate)"
                >
                  <Icon name="trash" :size="13" />
                  <span :style="{ color: 'var(--red)' }">删除模板</span>
                </Btn>
                <Btn
                  variant="ghost"
                  small
                  @click="onEditTemplateClick(activeTemplate)"
                >
                  <Icon name="edit" :size="13" />
                  <span>编辑模板</span>
                </Btn>
                <Btn variant="solid" small @click="useTemplate(activeTemplate)">
                  <Icon name="play" :size="13" />
                  <span>用此模板</span>
                </Btn>
              </div>
            </div>
            <div class="mt-5">
              <div class="mb-2 text-[12px]" :style="{ color: 'var(--ink-3)' }">
                结构 · {{ slotCount }} 个槽位
              </div>
              <div class="flex flex-col gap-2">
                <div
                  v-for="(s, i) in slotList"
                  :key="i"
                  class="flex items-center gap-3 px-3 py-2.5"
                  :style="{
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                    borderRadius: '10px',
                  }"
                >
                  <span
                    class="inline-flex items-center justify-center"
                    :style="{
                      width: '22px',
                      height: '22px',
                      borderRadius: '7px',
                      background: 'var(--dark)',
                      color: 'var(--primary)',
                      fontSize: '11px',
                      fontWeight: 700,
                    }"
                    >{{ i + 1 }}</span
                  >
                  <span class="flex-1 text-[12.5px]">{{ s.label }}</span>
                  <span
                    class="text-[10.5px]"
                    :style="{ color: 'var(--ink-4)' }"
                    >~{{ s.chars }} 字</span
                  >
                </div>
              </div>
            </div>

          </template>
        </Card>

        <!-- skills 预览：name + md 文件预览（仿 V1 SkillDetail） -->
        <Card v-else class="flex min-h-0 flex-col overflow-hidden">
          <template v-if="!activeSkill">
            <div class="text-[12.5px]" :style="{ color: 'var(--ink-3)' }">
              选一个 Skill 查看 prompt 内容。
            </div>
          </template>
          <template v-else>
            <div class="flex flex-shrink-0 items-center justify-between">
              <div>
                <div
                  class="text-[11px] uppercase"
                  :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
                >
                  Skill 详情
                </div>
                <div
                  class="font-display mt-1 font-bold"
                  :style="{ fontSize: '20px' }"
                >
                  {{ activeSkill.name }}
                </div>
              </div>
              <div class="flex items-center gap-2">
                <Btn
                  variant="ghost"
                  small
                  @click="onDeleteSkillClick(activeSkill)"
                >
                  <Icon name="trash" :size="13" />
                  <span :style="{ color: 'var(--red)' }">删除</span>
                </Btn>
                <Btn
                  variant="ghost"
                  small
                  @click="onEditSkillClick(activeSkill)"
                >
                  <Icon name="edit" :size="13" />
                  <span>编辑</span>
                </Btn>
                <Btn variant="solid" small disabled>
                  <Icon name="play" :size="13" />
                  <span>用此 Skill</span>
                </Btn>
              </div>
            </div>

            <div class="mt-3 flex flex-shrink-0 items-center gap-2">
              <Pill v-if="activeSkill.tone" tone="primary">{{ activeSkill.tone }}</Pill>
              <span
                v-if="activeSkill.uses !== undefined"
                class="text-[11px]"
                :style="{ color: 'var(--ink-3)' }"
                >用过 {{ activeSkill.uses }} 次</span
              >
            </div>

            <!-- md 文件预览 — 撑满预览卡剩余高度 -->
            <div
              class="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden"
              :style="{ borderRadius: '14px', border: '1px solid var(--line)' }"
            >
              <div
                class="flex flex-shrink-0 items-center gap-2 px-4 py-2.5"
                :style="{
                  background: 'var(--card-2)',
                  borderBottom: '1px solid var(--line)',
                }"
              >
                <Icon name="doc" :size="13" :style="{ color: 'var(--ink-3)' }" />
                <span
                  class="font-mono text-[12px] font-medium"
                  :style="{ color: 'var(--ink-2)' }"
                >
                  {{ skillFileName }}
                </span>
                <span class="flex-1" />
                <span class="text-[10px]" :style="{ color: 'var(--ink-4)' }">
                  {{ skillMdLines.length }} 行
                </span>
              </div>
              <div
                class="font-mono flex-1 overflow-auto px-4 py-3 text-[12px]"
                :style="{
                  background: 'var(--card-white, var(--card))',
                  lineHeight: 1.8,
                }"
              >
                <template v-for="(line, i) in skillMdLines" :key="i">
                  <div v-if="line.kind === 'blank'" :style="{ height: '8px' }" />
                  <div
                    v-else
                    :style="{
                      ...(line.kind === 'h1'
                        ? { fontSize: '15px', fontWeight: 700, color: 'var(--ink)', marginTop: '4px', marginBottom: '2px' }
                        : line.kind === 'h2'
                        ? { fontSize: '13.5px', fontWeight: 700, color: 'var(--primary-deep)', marginTop: '8px', marginBottom: '2px' }
                        : line.kind === 'li'
                        ? { color: 'var(--ink-2)', paddingLeft: '12px' }
                        : { color: 'var(--ink)' }),
                    }"
                  >
                    <span
                      class="mr-3 inline-block w-7 select-none text-right"
                      :style="{ color: 'var(--ink-4)', fontSize: '10px' }"
                      >{{ i + 1 }}</span
                    >
                    {{ line.text }}
                  </div>
                </template>
              </div>
            </div>
          </template>
        </Card>
      </div>
    </template>
  </div>
</template>
