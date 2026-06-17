<script setup lang="ts">
/**
 * 模版面板（设计稿 §5「模版」）。分类 tab + 模板卡；点击载入 title/body/topics，
 * 编辑器非空时先弹确认覆盖。「我的」tab 显示用户自定义模版（Task 4 P4）。
 */
import { ref, computed, onMounted } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TEMPLATES, TEMPLATE_CATEGORIES, type XhsTemplate } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";
import { useXhsAssets } from "@/stores/xhsAssets";
import { confirmDialog } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";

const xhs = useXhs();
const assets = useXhsAssets();
const toast = useToast();

const MINE = "__mine__";

const cat = ref(TEMPLATE_CATEGORIES[0] ?? "");
const builtinTabs = TEMPLATE_CATEGORIES.map((c) => ({ key: c, name: c }));
const tabs = [...builtinTabs, { key: MINE, name: "我的" }];

const list = computed(() => TEMPLATES.filter((t) => t.category === cat.value));

onMounted(() => {
  void assets.ensureLoaded();
});

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

async function applyMine(payload: Record<string, any>) {
  if (!xhs.isEmpty) {
    const ok = await confirmDialog("载入模板会覆盖当前的标题 / 正文 / 话题，确定吗？", {
      title: "载入模板",
      okLabel: "载入",
      kind: "danger",
    });
    if (!ok) return;
  }
  xhs.applyTemplate({
    title: payload.title ?? "",
    body: payload.body ?? "",
    topics: Array.isArray(payload.topics) ? payload.topics : [],
  });
}

function saveAsTemplate() {
  const title = xhs.title.trim();
  const body = xhs.body.trim();
  if (!title && !body) {
    toast.error("先写点标题或正文再存为模版");
    return;
  }
  void assets
    .create("template", {
      name: title || "我的模版",
      title: xhs.title,
      body: xhs.body,
      topics: [...xhs.topics],
    })
    .then(() => toast.success("已存为我的模版"))
    .catch(() => toast.error("保存失败"));
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <!-- 顶部：tab + 存为我的模版按钮 -->
    <div class="tpl-header">
      <CategoryTabs v-model="cat" :tabs="tabs" />
      <button type="button" class="xhs-save-template" @click="saveAsTemplate">＋ 存为我的模版</button>
    </div>

    <!-- 内置模版列表 -->
    <div v-if="cat !== MINE" class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '10px' }">
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

    <!-- 「我的」自定义模版列表 -->
    <div v-else class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
      <div v-if="assets.templates.length === 0" class="xhs-empty">
        还没有自定义模版，写好一篇点「存为我的模版」
      </div>
      <div v-for="a in assets.templates" :key="a.id" class="xhs-mine-row">
        <button type="button" class="xhs-mine-main" @click="applyMine(a.payload)">
          <div class="xhs-mine-name">{{ a.payload.name || "我的模版" }}</div>
          <div class="xhs-mine-preview">{{ a.payload.title }}</div>
        </button>
        <button type="button" class="xhs-mine-del" title="删除" @click="assets.remove(a.id)">✕</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tpl-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.xhs-save-template {
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
.xhs-save-template:hover {
  background: var(--primary);
  color: #fff;
}

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

.xhs-empty {
  font-size: 12px;
  color: var(--ink-2);
  text-align: center;
  padding: 24px 12px;
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
  cursor: pointer;
  transition: border-color 0.15s;
}
.xhs-mine-main:hover {
  border-color: var(--primary);
}

.xhs-mine-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.xhs-mine-preview {
  font-size: 11px;
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
