<script setup lang="ts">
/**
 * 表情面板（设计稿 §5「表情」/§6 边界）。三模式：常用分组 / 全部(Unicode) / 小红书代码。
 * 前两者再用 CategoryTabs 选子分组。点击 emoji 或代码插入正文光标处。
 * 小红书代码插入的是文字代码（如 [害羞R]），复制到小红书 App 会渲染成贴纸；
 * 本应用不打包官方贴纸图片（版权 / ToS），代码在本编辑器内按纯文本显示。
 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { EMOJI } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
type Mode = "curated" | "unicode" | "codes";
const mode = ref<Mode>("curated");
const modeTabs = [
  { key: "curated", name: "常用分组" },
  { key: "unicode", name: "全部" },
  { key: "codes", name: "小红书代码" },
];

const curatedKey = ref(EMOJI.curatedGroups[0]?.key ?? "");
const unicodeKey = ref(EMOJI.unicodeGroups[0]?.key ?? "");

const subTabs = computed(() =>
  mode.value === "curated"
    ? EMOJI.curatedGroups.map((g) => ({ key: g.key, name: g.name }))
    : mode.value === "unicode"
      ? EMOJI.unicodeGroups.map((g) => ({ key: g.key, name: g.name }))
      : [],
);
const subKey = computed<string>({
  get: () => (mode.value === "curated" ? curatedKey.value : unicodeKey.value),
  set: (v) => {
    if (mode.value === "curated") curatedKey.value = v;
    else unicodeKey.value = v;
  },
});
const emojis = computed(() => {
  if (mode.value === "curated") return EMOJI.curatedGroups.find((g) => g.key === curatedKey.value)?.emojis ?? [];
  if (mode.value === "unicode") return EMOJI.unicodeGroups.find((g) => g.key === unicodeKey.value)?.emojis ?? [];
  return [];
});
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs :model-value="mode" :tabs="modeTabs" @update:model-value="(v) => (mode = v as Mode)" />
    <CategoryTabs v-if="mode !== 'codes'" v-model="subKey" :tabs="subTabs" />

    <!-- emoji 网格 -->
    <div
      v-if="mode !== 'codes'"
      class="min-h-0 flex-1 overflow-y-auto"
      :style="{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '4px', alignContent: 'flex-start' }"
    >
      <button v-for="(e, i) in emojis" :key="i" type="button" class="xhs-emoji" @click="xhs.insertAtCursor(e)">
        {{ e }}
      </button>
    </div>

    <!-- 小红书代码 -->
    <div v-else class="min-h-0 flex-1 overflow-y-auto flex flex-wrap" :style="{ gap: '6px', alignContent: 'flex-start' }">
      <button
        v-for="c in EMOJI.xhsCodes"
        :key="c.code"
        type="button"
        class="xhs-code"
        :title="`插入代码 ${c.code}`"
        :style="{
          fontSize: '12px', padding: '5px 10px', borderRadius: '999px', cursor: 'pointer',
          border: '1px dashed var(--line-2)', background: 'rgba(var(--ink-rgb),0.04)', color: 'var(--ink)',
        }"
        @click="xhs.insertAtCursor(c.code)"
      >
        {{ c.label }} <span :style="{ color: 'var(--ink-2)' }">{{ c.code }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-code {
  transition: filter 0.15s;
}
.xhs-code:hover {
  filter: brightness(0.97);
}
.xhs-emoji {
  font-size: 20px;
  line-height: 1;
  padding: 6px 0;
  border-radius: 8px;
  cursor: pointer;
  background: transparent;
  transition: background 0.12s;
}
.xhs-emoji:hover {
  background: rgba(var(--ink-rgb), 0.06);
}
</style>
