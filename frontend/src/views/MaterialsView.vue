<script setup lang="ts">
/**
 * 素材库 V2 外壳：页头（标题 + 页签 + 汇总）+ 4 个页签内容。
 * 页签内容拆成独立组件（品牌型号 / 录入 / AI 拆条 / 使用反馈）。
 * 外层水平内缩由 App.vue 的 <main> padding（30px）提供，本视图不再叠加。
 */
import { computed, onMounted, ref } from "vue";
import { useMaterials } from "@/stores/materials";
import { useFactsChanges } from "@/stores/factsChanges";
import ModelsTab from "@/components/materials/ModelsTab.vue";
import IntakeForm from "@/components/materials/IntakeForm.vue";
import AtomizePanel from "@/components/materials/AtomizePanel.vue";
import FeedbackStatsPanel from "@/components/materials/FeedbackStatsPanel.vue";

type Tab = "models" | "intake" | "atomize" | "feedback";

const m = useMaterials();
const facts = useFactsChanges();
const tab = ref<Tab>("models");

// list() 拉型号；pull() 累积「参数已更新」变更（如刚重建过索引，进这页即显 Pill）。
onMounted(() => {
  m.list();
  facts.pull();
});

const TABS: { key: Tab; label: string }[] = [
  { key: "models", label: "品牌型号" },
  { key: "intake", label: "录入" },
  { key: "atomize", label: "AI 拆条" },
  { key: "feedback", label: "使用反馈" },
];

const summary = computed(() => {
  const total = m.models.length;
  if (!total) return "";
  const primary = m.models.filter((r) => r.role === "主推").length;
  return `共 ${total} 个型号 · 主推 ${primary} · 竞品 ${total - primary}`;
});
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 页头：标题 + 页签 + 汇总 -->
    <header class="flex flex-none items-center gap-5 pb-3.5">
      <h1 class="font-display m-0 text-[20px] font-extrabold">素材库</h1>
      <div class="flex items-center gap-1.5">
        <button
          v-for="t in TABS" :key="t.key" :data-tab="t.key"
          class="mat-tab" :class="{ 'mat-tab--on': tab === t.key }"
          @click="tab = t.key"
        >{{ t.label }}</button>
        <span class="mat-tab-soon">浏览<span class="mat-badge-soon">建设中</span></span>
      </div>
      <span v-if="summary" class="ml-auto text-[12px]" style="color: var(--ink-4)">{{ summary }}</span>
    </header>

    <ModelsTab v-if="tab === 'models'" />
    <IntakeForm v-else-if="tab === 'intake'" />
    <AtomizePanel v-else-if="tab === 'atomize'" />
    <FeedbackStatsPanel v-else-if="tab === 'feedback'" />
  </div>
</template>
