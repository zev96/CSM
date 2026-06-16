<script setup lang="ts">
/** 装饰面板（设计稿 §5「装饰」）。分割线 / 项目符号分组；点击插入正文光标处。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { DECORATION_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const grp = ref(DECORATION_GROUPS[0]?.key ?? "");
const tabs = DECORATION_GROUPS.map((g) => ({ key: g.key, name: g.name }));
const items = computed(() => DECORATION_GROUPS.find((g) => g.key === grp.value)?.items ?? []);
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="grp" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-wrap" :style="{ gap: '8px', alignContent: 'flex-start' }">
      <button
        v-for="(it, i) in items"
        :key="i"
        type="button"
        class="xhs-deco"
        :style="{
          fontSize: '14px', padding: '8px 12px', borderRadius: '10px', cursor: 'pointer',
          border: '1px solid var(--line-2)', background: '#fff', color: 'var(--ink)', whiteSpace: 'nowrap',
        }"
        @click="xhs.insertAtCursor(it)"
      >
        {{ it }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-deco {
  transition: filter 0.15s;
}
.xhs-deco:hover {
  filter: brightness(0.97);
}
</style>
