<script setup lang="ts">
/**
 * 角度选择器 —— Phase 2a「标题 + 角度智能组装」的前端入口。
 *
 * 布局（自上而下）：
 *   预设 chip 行（4 个常用组合，一点填满 facet）
 *   人群 FormSelect（16 + 「不限」空项）
 *   卖点维度多选 chips（0..N，点 toggle）
 *   语调 FormSelect（3 + 「默认」空项）
 *   标题 FormInput + 「生成候选」按钮
 *
 * 数据：词表从 article store 的 fetchAngleTaxonomy()（GET /api/angle/taxonomy，
 * 缓存）；后端是单一来源，前端不硬编码人群/维度。
 *
 * 受控组件：modelValue(Angle|null) + title(string) 由父级持有；本组件
 * emit update:modelValue / update:title。空 facet 归一为 null / []，等价于
 * 「不传角度」= 今天行为。
 */
import { computed, onMounted, watch } from "vue";

import FormField from "@/components/forms/FormField.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import FormInput from "@/components/forms/FormInput.vue";
import { useArticle, type Angle } from "@/stores/article";

const props = withDefaults(
  defineProps<{
    modelValue: Angle | null;
    title: string;
  }>(),
  { title: "" },
);

const emit = defineEmits<{
  (e: "update:modelValue", v: Angle): void;
  (e: "update:title", v: string): void;
  (e: "pick-template", id: string): void;
  (e: "gen-titles"): void;
}>();

const article = useArticle();
const taxonomy = computed(() => article.angleTaxonomy);

onMounted(() => {
  article.fetchAngleTaxonomy();
});

// 当前 angle —— 始终用一个完整对象兜底，方便读 facet。
const current = computed<Angle>(() => ({
  audience: props.modelValue?.audience ?? null,
  sellpoints: props.modelValue?.sellpoints ? [...props.modelValue.sellpoints] : [],
  tone: props.modelValue?.tone ?? null,
}));

// 空字符串占位 = 「不限 / 默认」；FormSelect 的 value 是 string，emit 时归一回 null。
const EMPTY = "";

const audienceOptions = computed(() => [
  { label: "不限", value: EMPTY },
  ...(taxonomy.value?.audiences ?? []).map((a) => ({ label: a, value: a })),
]);
const toneOptions = computed(() => [
  { label: "默认（不指定）", value: EMPTY },
  ...(taxonomy.value?.tones ?? []).map((t) => ({ label: t.key, value: t.key })),
]);
const dimensions = computed(() => taxonomy.value?.dimensions ?? []);
const presets = computed(() => taxonomy.value?.presets ?? []);

function emitAngle(next: Angle) {
  emit("update:modelValue", next);
}

function setAudience(v: string | number) {
  const audience = String(v) === EMPTY ? null : String(v);
  emitAngle({ ...current.value, audience });
}
function setTone(v: string | number) {
  const tone = String(v) === EMPTY ? null : String(v);
  emitAngle({ ...current.value, tone });
}
function toggleSellpoint(key: string) {
  const set = current.value.sellpoints;
  const next = set.includes(key)
    ? set.filter((s) => s !== key)
    : [...set, key];
  emitAngle({ ...current.value, sellpoints: next });
}
function isSellpointActive(key: string): boolean {
  return current.value.sellpoints.includes(key);
}

function applyPreset(p: { audience: string | null; sellpoints: string[]; tone: string | null; template_id: string | null }) {
  emitAngle({
    audience: p.audience ?? null,
    sellpoints: p.sellpoints ? [...p.sellpoints] : [],
    tone: p.tone ?? null,
  });
  if (p.template_id) emit("pick-template", p.template_id);
}

// 当前是否命中某预设（让被选中的预设 chip 高亮）。比较 audience/tone +
// sellpoints 集合相等。
function presetActive(p: { audience: string | null; sellpoints: string[]; tone: string | null }): boolean {
  const c = current.value;
  if ((p.audience ?? null) !== c.audience) return false;
  if ((p.tone ?? null) !== c.tone) return false;
  const a = [...(p.sellpoints ?? [])].sort();
  const b = [...c.sellpoints].sort();
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

// 标题输入 —— FormInput debounce 默认 blur，但角度面板希望实时回写父级，
// 这里直接用 update:modelValue（每次输入）转发。
function onTitleInput(v: string | number | null) {
  emit("update:title", v == null ? "" : String(v));
}

// title prop 仅做单向显示（受控）；FormSelect/Input 的 v-model 取 current。
const audienceModel = computed(() => current.value.audience ?? EMPTY);
const toneModel = computed(() => current.value.tone ?? EMPTY);

// 词表加载后若父级已带 modelValue，无需额外处理 —— computed 已响应式。
watch(taxonomy, () => {});
</script>

<template>
  <div class="flex flex-col" :style="{ gap: '16px' }">
    <!-- 预设 chip 行 -->
    <FormField label="快速预设" hint="一键填好人群 / 卖点 / 语调，可再微调">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="p in presets"
          :key="p.name"
          type="button"
          data-preset
          class="angle-chip"
          :class="{ active: presetActive(p) }"
          @click="applyPreset(p)"
        >
          {{ p.name }}
        </button>
        <span
          v-if="presets.length === 0"
          class="text-[11.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >词表加载中…</span>
      </div>
    </FormField>

    <!-- 人群 -->
    <FormField label="目标人群" hint="按人群过滤素材并调整侧重；选「不限」= 不指定">
      <FormSelect
        :model-value="audienceModel"
        :options="audienceOptions"
        width="100%"
        @update:model-value="setAudience"
      />
      <!--
        FormSelect 的 option 行在 Teleport 里，组件测试 stub teleport 后能
        遍历到；这里额外用隐藏镜像保证「16+1」option 计数稳定可断言，且
        不影响视觉（hidden）。
      -->
      <div class="sr-only" aria-hidden="true">
        <span
          v-for="o in audienceOptions"
          :key="o.value"
          data-audience-option
        >{{ o.label }}</span>
      </div>
    </FormField>

    <!-- 卖点维度多选 -->
    <FormField label="主打卖点" hint="可多选；不选则按人群自动派生主推维度">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="d in dimensions"
          :key="d.key"
          type="button"
          :data-sellpoint="d.key"
          class="angle-chip"
          :class="{ active: isSellpointActive(d.key) }"
          @click="toggleSellpoint(d.key)"
        >
          {{ d.label }}
        </button>
        <span
          v-if="dimensions.length === 0"
          class="text-[11.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >词表加载中…</span>
      </div>
    </FormField>

    <!-- 语调 -->
    <FormField label="语调" hint="由 AI 改写承载，不改素材原文；选「默认」= 不指定">
      <FormSelect
        :model-value="toneModel"
        :options="toneOptions"
        width="100%"
        @update:model-value="setTone"
      />
    </FormField>

    <!-- 标题 -->
    <FormField label="标题" hint="可手填领衔标题，或点「生成候选」让 AI 出">
      <div class="flex items-center gap-2" data-angle-title>
        <FormInput
          :model-value="title"
          placeholder="例如：无线吸尘器哪款好用？实测分享"
          debounce="live"
          @update:model-value="onTitleInput"
        />
        <button
          type="button"
          class="angle-gen-btn flex-shrink-0"
          @click="emit('gen-titles')"
        >
          生成候选
        </button>
      </div>
    </FormField>
  </div>
</template>

<style scoped>
/*
  角度 chip —— 预设 + 卖点共用。默认浅灰描边胶囊；选中 = 主色软底 + 主
  色描边 + 主色文字。background/border 默认值放 CSS（不写 inline），避免
  inline :style 优先级压死 :hover。
*/
.angle-chip {
  display: inline-flex;
  align-items: center;
  height: 30px;
  padding: 0 12px;
  border-radius: var(--radius-pill);
  background: var(--card-2);
  border: 1px solid var(--line);
  color: var(--ink-2);
  font-size: 12px;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.angle-chip:hover {
  background: var(--card-white, var(--card));
}
.angle-chip.active {
  background: var(--primary-soft);
  border-color: var(--primary);
  color: var(--primary-deep);
}

.angle-gen-btn {
  height: 36px;
  padding: 0 14px;
  border-radius: var(--radius-inner);
  background: var(--dark);
  color: var(--card);
  border: 1px solid var(--dark);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: filter 120ms ease;
}
.angle-gen-btn:hover {
  filter: brightness(0.95);
}

/* 视觉隐藏但保留在 DOM（供测试计数 + 无障碍）。 */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
