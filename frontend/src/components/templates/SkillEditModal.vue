<script setup lang="ts">
/**
 * Skill 创建 / 编辑模态。
 *
 * 创建模式：3 步向导（对齐 csm_gui/widgets/skill_wizard.py）
 *   1/3 基础   名称 + 适用品类 + 起始模板（预设）
 *   2/3 风格   开头钩子 / 段落密度 / 语气 / 额外禁止项（留空走预设默认）
 *   3/3 预览   可手动编辑的 markdown 预览
 *
 * 编辑模式：单步表单（直接改名 / 标签 / 描述 / 正文）。
 *
 * 提交时统一调用 POST/PATCH /api/skills；name 的 .md 文件名 = id。
 */
import { computed, ref, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

const props = defineProps<{
  open: boolean;
  /** 编辑模式下传入的 skill id；null/undefined = 新建 */
  skillId?: string | null;
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "saved", id: string): void;
}>();

const sidecar = useSidecar();
const toast = useToast();

const mode = computed<"create" | "edit">(() => (props.skillId ? "edit" : "create"));

// ── 预设库（对齐 _PRESETS in skill_wizard.py）────────────────
interface Preset {
  key: string;
  label: string;
  hook: string;
  density: string;
  tone: string;
  prohibitions: string[];
}
const PRESETS: Preset[] = [
  {
    key: "xiaohongshu",
    label: "小红书种草",
    hook: "第一句必须抛出一个共鸣痛点或反常识结论",
    density: "每段 2–3 句，多用换行；emoji 不超过 2 个",
    tone: "亲切口语化，第一人称分享视角",
    prohibitions: [
      "不要使用'最'、'第一'、'100%'等绝对化用语",
      "不要出现'点击关注''免费领'等引流话术",
    ],
  },
  {
    key: "zhihu",
    label: "知乎深度长文",
    hook: "开篇先给结论，再展开论证",
    density: "段落 4–6 句，逻辑链完整",
    tone: "理性、专业、克制，避免情绪化表达",
    prohibitions: ["不要堆砌形容词", "禁止未经证实的数据"],
  },
  {
    key: "seo",
    label: "SEO 资讯文",
    hook: "首段 80 字内自然包含核心关键词",
    density: "短段为主（3 句以内）便于扫读",
    tone: "中性、信息密度优先",
    prohibitions: ["禁止关键词堆砌", "禁止与主题无关的扩写"],
  },
  {
    key: "blank",
    label: "空白模板",
    hook: "",
    density: "",
    tone: "",
    prohibitions: [],
  },
];
const presetOptions = PRESETS.map((p) => ({ label: p.label, value: p.key }));

function buildSkeleton(opts: {
  product: string;
  preset: Preset;
  hookOverride: string;
  densityOverride: string;
  toneOverride: string;
  extraProhibitions: string;
}): string {
  const hook = opts.hookOverride.trim() || opts.preset.hook;
  const density = opts.densityOverride.trim() || opts.preset.density;
  const tone = opts.toneOverride.trim() || opts.preset.tone;

  const proh = [...opts.preset.prohibitions];
  for (const line of (opts.extraProhibitions || "").split("\n")) {
    const s = line.trim().replace(/^[-•·]\s*/, "");
    if (s) proh.push(s);
  }
  const prohBlock = proh.length ? proh.map((p) => `- ${p}`).join("\n") : "- ";
  const product = opts.product.trim() || "{ product }";
  const label = opts.preset.label || "新 Skill";

  return `# ${label}

你是一位专注于 ${product} 品类的内容编辑。收到毛坯文后，按下面的规则进行**润色改写**。

## 风格约束

- 开头钩子：${hook}
- 段落密度：${density}
- 语气：${tone}
- 数字保留：必须逐字保留所有参数、价格、型号。
- 品牌/型号：必须原样保留。

## 结构约束

- 保留毛坯文的所有 H2 段落及其顺序。
- 不得新增虚构内容。

## 禁止项

${prohBlock}

## 输出

直接输出润色后的完整正文 Markdown，不要加任何前言或代码块包裹。
`;
}

// ── State ─────────────────────────────────────────────────
const step = ref<1 | 2 | 3>(1);

// 创建模式 + 编辑模式共用
const skillName = ref("");
const product = ref("");
const presetKey = ref("xiaohongshu");
const hookOverride = ref("");
const densityOverride = ref("");
const toneOverride = ref("");
const extraProhibitions = ref("");
const previewBody = ref("");

// 编辑模式额外字段
const editName = ref("");
const editDesc = ref("");
const editTone = ref("");

const loading = ref(false);
const saving = ref(false);

const selectedPreset = computed<Preset>(
  () => PRESETS.find((p) => p.key === presetKey.value) ?? PRESETS[3],
);

function reset() {
  step.value = 1;
  skillName.value = "";
  product.value = "";
  presetKey.value = "xiaohongshu";
  hookOverride.value = "";
  densityOverride.value = "";
  toneOverride.value = "";
  extraProhibitions.value = "";
  previewBody.value = "";
  editName.value = "";
  editDesc.value = "";
  editTone.value = "";
}

async function loadDetail(sid: string) {
  loading.value = true;
  try {
    const r = await sidecar.client.get(`/api/skills/${sid}`);
    skillName.value = r.data.id ?? sid;
    editName.value = r.data.name ?? "";
    editDesc.value = r.data.desc ?? "";
    editTone.value = r.data.tone ?? "";
    previewBody.value = r.data.body ?? "";
  } catch (e: any) {
    toast.error(`Skill 加载失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    emit("update:open", false);
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.open,
  (v) => {
    if (!v) return;
    reset();
    if (props.skillId) {
      loadDetail(props.skillId);
    }
  },
);

function close() {
  if (saving.value) return;
  emit("update:open", false);
}

// ── 创建模式：分步导航 ──────────────────────────────────────
function validateStep1(): string | null {
  const n = skillName.value.trim();
  if (!n) return "Skill 名称不能为空";
  // 名称作为 .md 文件名 —— 只禁文件系统真正不能用的字符（Windows 包括），
  // 中文 / 字母 / 数字 / 空格 / - _ 全部允许。
  if (/[\\/:*?"<>|\x00-\x1f]/.test(n)) {
    return "名称含有非法字符（不能包含 \\ / : * ? \" < > |）";
  }
  return null;
}
function goNext() {
  if (step.value === 1) {
    const err = validateStep1();
    if (err) {
      toast.warn(err);
      return;
    }
    step.value = 2;
    return;
  }
  if (step.value === 2) {
    // 进入预览前生成 markdown
    previewBody.value = buildSkeleton({
      product: product.value,
      preset: selectedPreset.value,
      hookOverride: hookOverride.value,
      densityOverride: densityOverride.value,
      toneOverride: toneOverride.value,
      extraProhibitions: extraProhibitions.value,
    });
    step.value = 3;
    return;
  }
}
function goBack() {
  if (step.value > 1) step.value = ((step.value - 1) as 1 | 2 | 3);
}

// ── 保存 ──────────────────────────────────────────────────
async function saveCreate() {
  const err = validateStep1();
  if (err) {
    toast.warn(err);
    step.value = 1;
    return;
  }
  saving.value = true;
  try {
    // name = 用户输入（卡片显示名）；selectedPreset.value.label 是预设的"小红书种草/知乎深度长文"
    // 这种风格标签，绝不该当成 Skill 名 —— 早期版本写错了导致所有自建 Skill 都被显示成
    // preset 标签。desc 用 preset.label 是合适的，作为卡片的副标题（"基于 X 预设"）。
    const r = await sidecar.client.post("/api/skills", {
      id: skillName.value.trim(),
      name: skillName.value.trim(),
      desc: hookOverride.value.trim() || selectedPreset.value.label || "",
      tone: toneOverride.value.trim() || selectedPreset.value.tone || presetKey.value,
      body: previewBody.value,
    });
    toast.success(`已创建 Skill：${r.data.name ?? r.data.id}`);
    emit("saved", r.data.id);
    emit("update:open", false);
  } catch (e: any) {
    toast.error(`创建失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  } finally {
    saving.value = false;
  }
}

async function saveEdit() {
  if (!editName.value.trim()) {
    toast.warn("名称不能为空");
    return;
  }
  saving.value = true;
  try {
    const sid = props.skillId!;
    const r = await sidecar.client.patch(`/api/skills/${sid}`, {
      name: editName.value.trim(),
      desc: editDesc.value.trim(),
      tone: editTone.value.trim(),
      body: previewBody.value,
    });
    toast.success(`已保存：${r.data.name ?? sid}`);
    emit("saved", sid);
    emit("update:open", false);
  } catch (e: any) {
    toast.error(`保存失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  } finally {
    saving.value = false;
  }
}

const wizardTitle = computed(() => {
  if (mode.value === "edit") return `编辑 Skill：${editName.value || skillName.value}`;
  return `新建 Skill — ${step.value} / 3 ${
    step.value === 1 ? "基础" : step.value === 2 ? "风格" : "预览"
  }`;
});
</script>

<template>
  <Dialog
    :open="open"
    size="lg"
    :title="wizardTitle"
    show-close
    :closable="!saving"
    @update:open="close"
  >
    <div
      v-if="loading"
      class="flex items-center justify-center py-8"
    >
      <Spinner :size="14" />
    </div>

    <!-- ━━━━━━━ 创建模式：3 步向导 ━━━━━━━ -->
    <template v-else-if="mode === 'create'">
      <!-- step 1：基础 -->
      <div v-if="step === 1" class="flex flex-col gap-4 px-1">
        <FormField label="Skill 名称" hint="名称将作为文件名（.md），中文 / 字母 / 数字均可，避免 \\ / : * ? &quot; &lt; &gt; |。">
          <FormInput
            v-model="skillName"
            placeholder="如：xiaohongshu-polish"
            debounce="live"
          />
        </FormField>
        <FormField label="适用品类" hint="会写进 prompt — 「你是一位专注于 X 品类的编辑」。">
          <FormInput
            v-model="product"
            placeholder="如：宠物吸尘器、轻办公笔电"
            debounce="live"
          />
        </FormField>
        <FormField label="起始模板" hint="选一个内置预设作为起点，下一步可微调。">
          <FormSelect
            :model-value="presetKey"
            :options="presetOptions"
            width="100%"
            @update:model-value="(v) => (presetKey = String(v))"
          />
        </FormField>
      </div>

      <!-- step 2：风格 -->
      <div v-else-if="step === 2" class="flex flex-col gap-4 px-1">
        <div
          class="text-[12.5px] font-medium"
          :style="{ color: 'var(--ink-2)' }"
        >
          微调风格（可留空，使用模板默认值）
        </div>
        <FormField label="开头钩子">
          <FormInput
            v-model="hookOverride"
            placeholder="覆盖：开头钩子要求"
            debounce="live"
          />
        </FormField>
        <FormField label="段落密度">
          <FormInput
            v-model="densityOverride"
            placeholder="覆盖：段落密度"
            debounce="live"
          />
        </FormField>
        <FormField label="语气">
          <FormInput
            v-model="toneOverride"
            placeholder="覆盖：语气"
            debounce="live"
          />
        </FormField>
        <FormField label="额外禁止项">
          <textarea
            v-model="extraProhibitions"
            class="bg-card-2 px-3 py-2 text-[12.5px] outline-none transition-colors focus:bg-card-white"
            :style="{
              width: '100%',
              minHeight: '110px',
              borderRadius: 'var(--radius-inner)',
              border: '1px solid var(--line)',
              resize: 'vertical',
              lineHeight: 1.6,
            }"
            placeholder="每行一条额外禁止项（可选）"
          />
        </FormField>
      </div>

      <!-- step 3：预览 -->
      <div v-else class="flex flex-col gap-2 px-1">
        <div
          class="text-[12.5px] font-medium"
          :style="{ color: 'var(--ink-2)' }"
        >
          预览（可直接编辑）
        </div>
        <textarea
          v-model="previewBody"
          class="bg-card-2 px-3 py-2 font-mono text-[12px] outline-none transition-colors focus:bg-card-white"
          :style="{
            width: '100%',
            minHeight: '320px',
            borderRadius: 'var(--radius-inner)',
            border: '1px solid var(--line)',
            resize: 'vertical',
            lineHeight: 1.7,
          }"
        />
      </div>
    </template>

    <!-- ━━━━━━━ 编辑模式：单步表单 ━━━━━━━ -->
    <template v-else>
      <div class="flex flex-col gap-4 px-1">
        <FormField label="名称" hint="出现在 Skill 列表里的显示名。">
          <FormInput
            v-model="editName"
            placeholder="如 克制 · 克制"
            debounce="live"
          />
        </FormField>
        <FormField label="ID" hint="文件名（不可修改）。">
          <FormInput :model-value="skillName" disabled />
        </FormField>
        <FormField label="一句话描述" hint="卡片副标题，不会进 prompt。">
          <FormInput
            v-model="editDesc"
            placeholder="如 极度克制 · 不超过 1 个感叹号"
            debounce="live"
          />
        </FormField>
        <FormField label="语气标签">
          <FormInput
            v-model="editTone"
            placeholder="如 克制 / 真实 / 温柔"
            debounce="live"
          />
        </FormField>
        <FormField
          label="Prompt 正文（Markdown）"
          hint="这部分会拼到生成请求的 user_skill_prompt 里。"
        >
          <textarea
            v-model="previewBody"
            class="bg-card-2 px-3 py-2 font-mono text-[12.5px] outline-none transition-colors focus:bg-card-white"
            :style="{
              width: '100%',
              minHeight: '260px',
              borderRadius: 'var(--radius-inner)',
              border: '1px solid var(--line)',
              resize: 'vertical',
              lineHeight: 1.6,
            }"
          />
        </FormField>
      </div>
    </template>

    <template #footer>
      <template v-if="!loading && mode === 'create'">
        <Btn
          v-if="step > 1"
          variant="ghost"
          small
          :disabled="saving"
          @click="goBack"
        >
          <Icon name="arrowLeft" :size="13" />
          <span>上一步</span>
        </Btn>
        <span class="flex-1" />
        <Btn variant="ghost" small :disabled="saving" @click="close">取消</Btn>
        <Btn
          v-if="step < 3"
          variant="solid"
          small
          @click="goNext"
        >
          <span>下一步</span>
          <Icon name="arrowRight" :size="13" />
        </Btn>
        <Btn v-else variant="solid" small :disabled="saving" @click="saveCreate">
          <Spinner v-if="saving" :size="11" />
          <Icon v-else name="check" :size="13" />
          <span>创建</span>
        </Btn>
      </template>
      <template v-else-if="!loading && mode === 'edit'">
        <Btn variant="ghost" small :disabled="saving" @click="close">取消</Btn>
        <Btn variant="solid" small :disabled="saving" @click="saveEdit">
          <Spinner v-if="saving" :size="11" />
          <Icon v-else name="check" :size="13" />
          <span>保存修改</span>
        </Btn>
      </template>
    </template>
  </Dialog>
</template>
