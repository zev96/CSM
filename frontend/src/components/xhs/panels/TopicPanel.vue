<script setup lang="ts">
/** 话题面板（设计稿 §5「话题」）。分组 tab + #话题；点击加 chip（store 去重去 #）。已加的高亮。
 *  「我的」tab：自定义话题分组（Task 6 P4）—— 存为分组 + 全部添加 + 删除。
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

async function saveTopicGroup() {
  if (!xhs.topics.length) { toast.error("先在正文区加几个话题，再存为分组"); return; }
  const name = xhs.topics.slice(0, 3).map((t) => "#" + t).join(" ") + (xhs.topics.length > 3 ? " …" : "");
  try {
    await assets.create("topic_group", { name, tags: [...xhs.topics] });
    toast.success("已存为话题分组");
  } catch { toast.error("保存失败"); }
}

function addAll(tags: string[]) {
  for (const t of tags) xhs.addTopic(t);
}

async function removeMine(id: string) {
  try { await assets.remove(id); }
  catch { toast.error("删除失败"); }
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <!-- 顶部：tab + 存为话题分组按钮 -->
    <div class="tg-header">
      <CategoryTabs v-model="grp" :tabs="tabs" />
      <button type="button" class="xhs-save-topicgroup" @click="saveTopicGroup">＋ 存为话题分组</button>
    </div>

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

    <!-- 「我的」自定义话题分组列表 -->
    <template v-if="grp === MINE">
      <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
        <div v-if="!assets.topicGroups.length" class="xhs-empty">还没有自定义话题分组～</div>
        <div v-for="a in assets.topicGroups" :key="a.id" class="xhs-tg-card">
          <div class="xhs-tg-head">
            <span class="xhs-tg-name">{{ a.payload.name || '我的话题' }}</span>
            <button type="button" class="xhs-addall" @click="addAll(a.payload.tags ?? [])">全部添加</button>
            <button type="button" class="xhs-mine-del" title="删除分组" @click="removeMine(a.id)">✕</button>
          </div>
          <div class="flex flex-wrap" :style="{ gap: '6px' }">
            <button v-for="(t, i) in (a.payload.tags ?? [])" :key="i" type="button" class="xhs-tag-chip" @click="xhs.addTopic(t)">#{{ t }}</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.tg-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.xhs-tag {
  transition: filter 0.15s;
}
.xhs-tag:hover {
  filter: brightness(0.97);
}

/* 存为话题分组 button — matches TemplatePanel's xhs-save-template style */
.xhs-save-topicgroup {
  align-self: flex-start;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.xhs-save-topicgroup:hover {
  background: var(--primary);
  color: #fff;
}

/* 空状态提示 — EXACT copy from TemplatePanel */
.xhs-empty {
  font-size: 12px;
  color: var(--ink-2);
  text-align: center;
  padding: 24px 12px;
}

/* 删除按钮 — EXACT copy from TemplatePanel */
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

/* 自定义话题分组卡片 */
.xhs-tg-card {
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 卡片头部：分组名 + 全部添加 + ✕ */
.xhs-tg-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.xhs-tg-name {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

/* 全部添加 ghost button */
.xhs-addall {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--line-2);
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.xhs-addall:hover {
  border-color: var(--primary);
  color: var(--primary);
}

/* 分组内话题 chip */
.xhs-tag-chip {
  font-size: 13px;
  color: #3a6fb0;
  background: rgba(58, 111, 176, 0.08);
  border-radius: 999px;
  padding: 3px 10px;
  cursor: pointer;
  border: none;
  transition: background 0.15s;
}
.xhs-tag-chip:hover {
  background: rgba(58, 111, 176, 0.16);
}
</style>
