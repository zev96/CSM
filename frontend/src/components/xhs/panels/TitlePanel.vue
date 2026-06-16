<script setup lang="ts">
/** 标题面板（设计稿 §5「标题」）。分类 tab + 爆款标题公式；点击填入标题（替换）。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TITLE_CATEGORIES } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const cat = ref(TITLE_CATEGORIES[0]?.key ?? "");
const tabs = TITLE_CATEGORIES.map((c) => ({ key: c.key, name: c.name }));
const items = computed(() => TITLE_CATEGORIES.find((c) => c.key === cat.value)?.items ?? []);
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="cat" :tabs="tabs" />
    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', flexShrink: 0 }">
      点击填入标题，把 <b>xx</b> 换成你的关键词
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
      <button v-for="(it, i) in items" :key="i" type="button" class="xhs-row" @click="xhs.setTitle(it)">
        {{ it }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-row {
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 8px 12px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.xhs-row:hover {
  border-color: var(--primary);
}
</style>
