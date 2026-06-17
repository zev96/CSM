<script setup lang="ts">
/** 话题面板（设计稿 §5「话题」）。分组 tab + #话题；点击追加到正文（store 去重去 #）。
 *  「我的」tab：单条自定义话题（输入添加 + 点击追加正文 + 删除）。
 */
import { ref, computed, onMounted } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TOPIC_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";
import { useXhsAssets } from "@/stores/xhsAssets";
import { useToast } from "@/composables/useToast";

const xhs = useXhs();
const assets = useXhsAssets();
const toast = useToast();

const MINE = "__mine__";

const builtinTabs = TOPIC_GROUPS.map((g) => ({ key: g.key, name: g.name }));
const tabs = [...builtinTabs, { key: MINE, name: "我的" }];

const grp = ref(TOPIC_GROUPS[0]?.key ?? "");
const tags = computed(() => TOPIC_GROUPS.find((g) => g.key === grp.value)?.tags ?? []);

function added(tag: string): boolean {
  return xhs.topics.includes(tag);
}

onMounted(() => { void assets.ensureLoaded(); });

const addInput = ref("");
async function addCustom() {
  const t = addInput.value.trim().replace(/^#+/, "");
  if (!t) return;
  try {
    await assets.create("topic", { text: t });
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
    <!-- 顶部：tab -->
    <CategoryTabs v-model="grp" :tabs="tabs" />

    <!-- 内置话题列表（非「我的」tab） -->
    <div v-if="grp !== MINE" class="min-h-0 flex-1 overflow-y-auto flex flex-wrap" :style="{ gap: '8px', alignContent: 'flex-start' }">
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

    <!-- 「我的」自定义话题 -->
    <div v-else class="min-h-0 flex-1 flex flex-col" :style="{ gap: '8px' }">
      <div class="flex items-center" :style="{ gap: '6px' }">
        <input
          v-model="addInput"
          type="text"
          class="xhs-topic-add-input"
          placeholder="输入话题，回车或点添加"
          @keydown.enter.prevent="addCustom"
        />
        <button type="button" class="xhs-topic-add-btn" @click="addCustom">添加</button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
        <div v-if="!assets.topics.length" class="xhs-empty">还没有自定义话题～</div>
        <div v-for="a in assets.topics" :key="a.id" class="xhs-mine-row">
          <button type="button" class="xhs-mine-main" @click="xhs.addTopic(a.payload.text)">#{{ a.payload.text }}</button>
          <button type="button" class="xhs-mine-del" title="删除" @click="removeMine(a.id)">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.xhs-tag {
  transition: filter 0.15s;
}
.xhs-tag:hover {
  filter: brightness(0.97);
}

.xhs-topic-add-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line-2);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  outline: none;
  color: var(--ink);
  background: #fff;
}

.xhs-topic-add-btn {
  flex-shrink: 0;
  font-size: 13px;
  padding: 7px 14px;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  cursor: pointer;
}

.xhs-empty {
  color: var(--ink-2);
  font-size: 12.5px;
  text-align: center;
  padding: 16px 8px;
}

.xhs-mine-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.xhs-mine-main {
  flex: 1;
  min-width: 0;
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 8px 12px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: border-color 0.15s;
}
.xhs-mine-main:hover {
  border-color: var(--primary);
}

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
