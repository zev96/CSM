<script setup lang="ts">
/**
 * skill 链组合器 —— 3 个 role 槽（人设 / 去AI味 / 平台适配），每槽一个
 * FormSelect，列出该 role 下的 skill + 一个空「不用」选项。
 *
 * 受控：props.modelValue 是有序的 skill_chain（id 列表）；任一槽变化时
 * 按 人设 → 去AI味 → 平台 的固定顺序产出新链（过滤掉空槽），emit
 * update:modelValue。skills 来源由父组件传入（复用已有 /api/skills 加载，
 * 响应里含 role 字段）。
 *
 * 设计意图：位置定职责（与后端 chain_service 一致）——
 *   人设(persona) = step0 组装/定调；去AI味(humanize) / 平台(platform)
 *   = 后续精修 pass。空链 = 退回单 skill / 模板默认（零回归）。
 */
import { computed, reactive, watch } from "vue";

import FormField from "@/components/forms/FormField.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

interface SkillRow {
  id: string;
  name: string;
  role?: string | null;
}

const props = withDefaults(
  defineProps<{
    modelValue: string[];
    skills: SkillRow[];
  }>(),
  { modelValue: () => [], skills: () => [] },
);
const emit = defineEmits<{
  (e: "update:modelValue", v: string[]): void;
}>();

// 固定的 3 个 role 槽 —— 顺序即链顺序（位置定职责）。
const ROLE_SLOTS: Array<{ role: string; label: string }> = [
  { role: "persona", label: "人设" },
  { role: "humanize", label: "去AI味" },
  { role: "platform", label: "平台适配" },
];

const KNOWN_ROLES = new Set(ROLE_SLOTS.map((s) => s.role));

/** 把某 skill 归一到一个已知 role —— 后端缺省 role 即 "persona"，未来若
 * 出现未知 role 也兜底到 persona 槽，避免 skill 在 UI 上凭空消失。 */
function normRole(role: string | null | undefined): string {
  return role && KNOWN_ROLES.has(role) ? role : "persona";
}

// 每个 role 槽的下拉选项：空「不用」 + 该 role 的 skills（保持加载顺序）。
const roleOptions = computed<Record<string, Array<{ label: string; value: string }>>>(() => {
  const out: Record<string, Array<{ label: string; value: string }>> = {};
  for (const slot of ROLE_SLOTS) {
    out[slot.role] = [{ label: "不用", value: "" }];
  }
  for (const sk of props.skills) {
    const r = normRole(sk.role);
    out[r].push({ label: sk.name, value: sk.id });
  }
  return out;
});

// 各槽当前选中的 skill id（"" = 不用）。由 modelValue 回填。
const selected = reactive<Record<string, string>>({
  persona: "",
  humanize: "",
  platform: "",
});

/** modelValue（有序 id 列表）→ 按 role 回填到对应槽。链里的 id 如果在
 * skills 里找不到（已失效）则忽略；同 role 多个 id 取第一个命中的。 */
function hydrateFromModel(ids: string[]): void {
  const byRole: Record<string, string> = { persona: "", humanize: "", platform: "" };
  for (const id of ids) {
    const sk = props.skills.find((s) => s.id === id);
    if (!sk) continue;
    const r = normRole(sk.role);
    if (!byRole[r]) byRole[r] = id;
  }
  selected.persona = byRole.persona;
  selected.humanize = byRole.humanize;
  selected.platform = byRole.platform;
}

watch(
  () => [props.modelValue, props.skills] as const,
  () => hydrateFromModel(props.modelValue ?? []),
  { immediate: true, deep: true },
);

// 有序链：人设 → 去AI味 → 平台，过滤掉空槽。
const chain = computed<string[]>(() =>
  ROLE_SLOTS.map((s) => selected[s.role]).filter(Boolean),
);

function onSlotChange(role: string, value: string | number) {
  selected[role] = String(value);
  emit("update:modelValue", chain.value);
}

defineExpose({ selected, roleOptions, chain, onSlotChange });
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
      按顺序润色：人设定调 → 去AI味 → 平台适配。每段可留空「不用」。
    </div>
    <FormField v-for="slot in ROLE_SLOTS" :key="slot.role" :label="slot.label">
      <FormSelect
        :model-value="selected[slot.role]"
        :options="roleOptions[slot.role]"
        width="100%"
        @update:model-value="(v) => onSlotChange(slot.role, v)"
      />
    </FormField>
  </div>
</template>
