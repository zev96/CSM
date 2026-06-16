<script setup lang="ts">
/** 文案面板（设计稿 §5「文案」）。分组 tab + 文案片段；点击插入正文光标处。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { COPY_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const grp = ref(COPY_GROUPS[0]?.key ?? "");
const tabs = COPY_GROUPS.map((g) => ({ key: g.key, name: g.name }));
const items = computed(() => COPY_GROUPS.find((g) => g.key === grp.value)?.items ?? []);
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="grp" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
      <button v-for="(it, i) in items" :key="i" type="button" class="xhs-row" @click="xhs.insertAtCursor(it)">
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
