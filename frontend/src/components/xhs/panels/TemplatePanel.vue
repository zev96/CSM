<script setup lang="ts">
/**
 * 模版面板（设计稿 §5「模版」）。分类 tab + 模板卡；点击载入 title/body/topics，
 * 编辑器非空时先弹确认覆盖。
 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TEMPLATES, TEMPLATE_CATEGORIES, type XhsTemplate } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

const xhs = useXhs();
const cat = ref(TEMPLATE_CATEGORIES[0] ?? "");
const tabs = TEMPLATE_CATEGORIES.map((c) => ({ key: c, name: c }));
const list = computed(() => TEMPLATES.filter((t) => t.category === cat.value));

async function pick(t: XhsTemplate) {
  if (!xhs.isEmpty) {
    const ok = await confirmDialog("载入模板会覆盖当前的标题 / 正文 / 话题，确定吗？", {
      title: "载入模板",
      okLabel: "载入",
      kind: "danger",
    });
    if (!ok) return;
  }
  xhs.applyTemplate({ title: t.title, body: t.body, topics: t.topics });
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="cat" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '10px' }">
      <button v-for="t in list" :key="t.id" type="button" class="xhs-tpl-card" @click="pick(t)">
        <div :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)', marginBottom: '4px' }">{{ t.name }}</div>
        <div
          :style="{
            fontSize: '12px', color: 'var(--ink)', marginBottom: '4px',
            display: '-webkit-box', WebkitLineClamp: 1, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }"
        >{{ t.title }}</div>
        <div
          :style="{
            fontSize: '11px', color: 'var(--ink-2)', whiteSpace: 'pre-wrap',
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }"
        >{{ t.body }}</div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-tpl-card {
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 12px;
  padding: 10px 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.xhs-tpl-card:hover {
  border-color: var(--primary);
  box-shadow: 0 4px 14px -8px rgba(var(--shadow-rgb), 0.3);
}
</style>
