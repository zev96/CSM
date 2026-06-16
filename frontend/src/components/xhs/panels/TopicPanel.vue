<script setup lang="ts">
/** 话题面板（设计稿 §5「话题」）。分组 tab + #话题；点击加 chip（store 去重去 #）。已加的高亮。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TOPIC_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const grp = ref(TOPIC_GROUPS[0]?.key ?? "");
const tabs = TOPIC_GROUPS.map((g) => ({ key: g.key, name: g.name }));
const tags = computed(() => TOPIC_GROUPS.find((g) => g.key === grp.value)?.tags ?? []);
function added(tag: string): boolean {
  return xhs.topics.includes(tag);
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="grp" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-wrap" :style="{ gap: '8px', alignContent: 'flex-start' }">
      <button
        v-for="(t, i) in tags"
        :key="i"
        type="button"
        class="xhs-tag"
        :style="{
          fontSize: '13px', padding: '5px 12px', borderRadius: '999px', cursor: 'pointer',
          border: '1px solid ' + (added(t) ? '#3a6fb0' : 'var(--line-2)'),
          background: added(t) ? 'rgba(58,111,176,0.10)' : '#fff',
          color: added(t) ? '#3a6fb0' : 'var(--ink)',
        }"
        @click="xhs.addTopic(t)"
      >
        #{{ t }}
      </button>
    </div>
  </div>
</template>
