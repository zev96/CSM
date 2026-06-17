<script setup lang="ts">
/** 标题面板（设计稿 §5「标题」）。分类 tab + 爆款标题公式；点击填入标题（替换）。P4 增「我的」自定义标题。 */
import { ref, computed, onMounted } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TITLE_CATEGORIES } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";
import { useXhsAssets } from "@/stores/xhsAssets";
import { useToast } from "@/composables/useToast";

const xhs = useXhs();
const assets = useXhsAssets();
const toast = useToast();
onMounted(() => { void assets.ensureLoaded(); });

const MINE = "__mine__";
const cat = ref(TITLE_CATEGORIES[0]?.key ?? "");
const tabs = [...TITLE_CATEGORIES.map((c) => ({ key: c.key, name: c.name })), { key: MINE, name: "我的" }];
const items = computed(() => TITLE_CATEGORIES.find((c) => c.key === cat.value)?.items ?? []);

const addInput = ref("");
async function addCustom() {
  const text = addInput.value.trim();
  if (!text) return;
  try {
    await assets.create("title", { text });
    addInput.value = "";
  } catch {
    toast.error("添加失败");
  }
}
async function removeMine(id: string) {
  try { await assets.remove(id); }
  catch { toast.error("删除失败"); }
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="cat" :tabs="tabs" />

    <!-- 起步标题 -->
    <template v-if="cat !== MINE">
      <div :style="{ fontSize: '11px', color: 'var(--ink-2)', flexShrink: 0 }">
        点击填入标题，把 <b>xx</b> 换成你的关键词
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
        <button v-for="(it, i) in items" :key="i" type="button" class="xhs-row" @click="xhs.setTitle(it)">
          {{ it }}
        </button>
      </div>
    </template>

    <!-- 我的标题 -->
    <div v-else class="min-h-0 flex-1 flex flex-col" :style="{ gap: '8px' }">
      <div class="flex items-center" :style="{ gap: '6px' }">
        <input
          v-model="addInput"
          type="text"
          class="xhs-title-add-input"
          placeholder="添加自定义标题，回车或点添加"
          @keydown.enter.prevent="addCustom"
        />
        <button type="button" class="xhs-title-add-btn" @click="addCustom">添加</button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
        <div v-if="!assets.titles.length" class="xhs-empty">还没有自定义标题～</div>
        <div v-for="a in assets.titles" :key="a.id" class="xhs-mine-row">
          <button type="button" class="xhs-mine-main" @click="xhs.setTitle(a.payload.text)">{{ a.payload.text }}</button>
          <button type="button" class="xhs-mine-del" title="删除" @click="removeMine(a.id)">✕</button>
        </div>
      </div>
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
.xhs-title-add-input { flex: 1; min-width: 0; border: 1px solid var(--line-2); border-radius: 8px; padding: 7px 10px; font-size: 13px; outline: none; color: var(--ink); background: #fff; }
.xhs-title-add-btn { flex-shrink: 0; font-size: 13px; padding: 7px 14px; border-radius: 8px; background: var(--primary); color: #fff; cursor: pointer; }
.xhs-empty { color: var(--ink-2); font-size: 12.5px; text-align: center; padding: 16px 8px; }
.xhs-mine-row { display: flex; align-items: center; gap: 6px; }
.xhs-mine-main { flex: 1; min-width: 0; text-align: left; border: 1px solid var(--line-2); border-radius: 10px; padding: 8px 12px; background: #fff; color: var(--ink); font-size: 13px; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; transition: border-color 0.15s; }
.xhs-mine-main:hover { border-color: var(--primary); }
.xhs-mine-del {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--ink-2);
  border: 1px solid var(--line-2);
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.xhs-mine-del:hover {
  color: #e53e3e;
  border-color: #e53e3e;
}
</style>
