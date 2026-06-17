<script setup lang="ts">
/**
 * 中栏纯文本编辑器（设计稿 §4.1 中栏 / §4.2 内核）。
 * 标题 input + 正文 textarea + 话题 chips + 复制按钮。正文接 useCursorInsert
 * 并向 store 注册插入器，P1 素材面板即可往光标处插入。
 */
import { ref, onMounted, onUnmounted } from "vue";
import Icon from "@/components/ui/Icon.vue";
import { useXhs, TITLE_SOFT_LIMIT, BODY_SOFT_LIMIT } from "@/stores/xhs";
import { useCursorInsert } from "@/composables/useCursorInsert";

const xhs = useXhs();

const bodyRef = ref<HTMLTextAreaElement | null>(null);
const { insert } = useCursorInsert(bodyRef, (v) => xhs.setBody(v));

onMounted(() => {
  xhs.registerInserter(insert);
  xhs.registerCursorProbe(() => {
    const el = bodyRef.value;
    const pos = el ? (el.selectionStart ?? el.value.length) : 0;
    return { before: (el?.value ?? xhs.body).slice(0, pos) };
  });
});
onUnmounted(() => {
  xhs.registerInserter(null);
  xhs.registerCursorProbe(null);
});

// 话题输入
const topicInput = ref("");
function commitTopic() {
  const v = topicInput.value;
  if (!v.trim()) return;
  // 支持一次输入多个（空格 / 逗号分隔）
  for (const piece of v.split(/[\s,，]+/)) xhs.addTopic(piece);
  topicInput.value = "";
}

const labelStyle = {
  fontSize: "12px",
  color: "var(--ink-2)",
  marginBottom: "4px",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
} as const;

const inputBaseStyle = {
  width: "100%",
  border: "1px solid var(--line-2)",
  borderRadius: "10px",
  padding: "10px 12px",
  background: "#fff",
  color: "var(--ink)",
  fontSize: "14px",
  outline: "none",
  boxSizing: "border-box",
} as const;
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '14px' }">
    <!-- 工具条：排版主题快捷符号 + 表情快捷（设计稿 §4.1 中栏工具条 / §1 P1） -->
    <div class="flex flex-wrap items-center" :style="{ gap: '6px', flexShrink: 0 }">
      <template v-if="xhs.themeToolbar.length">
        <button
          v-for="b in xhs.themeToolbar"
          :key="b.key"
          type="button"
          class="xhs-tool-btn"
          :title="`插入${b.label}符号`"
          @click="b.key === 'ordered' ? xhs.insertOrdered() : xhs.insertAtCursor(b.symbol)"
        >
          <span :style="{ fontSize: '14px' }">{{ b.symbol }}</span>
          <span :style="{ fontSize: '12px', color: 'var(--ink-2)' }">{{ b.label }}</span>
        </button>
      </template>
      <button v-else type="button" class="xhs-tool-btn" @click="xhs.setActivePanel('theme')">
        <Icon name="wand" :size="14" /> 选择排版主题
      </button>
      <button type="button" class="xhs-tool-btn" :style="{ marginLeft: 'auto' }" @click="xhs.setActivePanel('emoji')">
        <Icon name="heart" :size="14" /> 表情
      </button>
    </div>

    <!-- 标题 -->
    <div>
      <div :style="labelStyle">
        <span>标题</span>
        <span :style="{ color: xhs.titleOver ? 'var(--red)' : 'var(--ink-2)' }">
          {{ xhs.titleCount }}/{{ TITLE_SOFT_LIMIT }}<template v-if="xhs.titleOver"> · 超 {{ xhs.titleCount - TITLE_SOFT_LIMIT }} 字</template>
        </span>
      </div>
      <input
        :value="xhs.title"
        type="text"
        placeholder="好标题决定打开率，建议 ≤ 20 字"
        :style="inputBaseStyle"
        @input="xhs.setTitle(($event.target as HTMLInputElement).value)"
      />
    </div>

    <!-- 正文 -->
    <div class="flex min-h-0 flex-1 flex-col">
      <div :style="labelStyle">
        <span>正文</span>
        <span :style="{ color: xhs.bodyOver ? 'var(--red)' : 'var(--ink-2)' }">
          {{ xhs.bodyCount }}/{{ BODY_SOFT_LIMIT }}<template v-if="xhs.bodyOver"> · 超 {{ xhs.bodyCount - BODY_SOFT_LIMIT }} 字</template>
        </span>
      </div>
      <textarea
        ref="bodyRef"
        :value="xhs.body"
        placeholder="写下你的图文笔记正文～ 换行、emoji、#话题 都支持"
        :style="{ ...inputBaseStyle, flex: 1, minHeight: '160px', resize: 'none', lineHeight: 1.7, fontFamily: 'inherit' }"
        @input="xhs.setBody(($event.target as HTMLTextAreaElement).value)"
      />
    </div>

    <!-- 话题 -->
    <div>
      <div :style="labelStyle"><span>话题</span></div>
      <div class="flex flex-wrap items-center" :style="{ gap: '6px' }">
        <span
          v-for="(t, i) in xhs.topics"
          :key="i"
          class="flex items-center"
          :style="{
            gap: '4px', fontSize: '13px', color: '#3a6fb0',
            background: 'rgba(58,111,176,0.08)', borderRadius: '999px', padding: '3px 10px',
          }"
        >
          #{{ t }}
          <button
            type="button"
            :style="{ cursor: 'pointer', color: '#3a6fb0', display: 'flex', alignItems: 'center' }"
            title="移除"
            @click="xhs.removeTopic(i)"
          ><Icon name="x" :size="12" /></button>
        </span>
        <input
          v-model="topicInput"
          type="text"
          placeholder="加话题，回车确认"
          :style="{ flex: 1, minWidth: '120px', border: 'none', outline: 'none', background: 'transparent', fontSize: '13px', color: 'var(--ink)' }"
          @keydown.enter.prevent="commitTopic"
          @blur="commitTopic"
        />
      </div>
    </div>

    <!-- 复制按钮 -->
    <div class="flex items-center" :style="{ gap: '8px', borderTop: '1px solid var(--line-2)', paddingTop: '12px' }">
      <button type="button" class="xhs-copy-btn" @click="xhs.copy('title')">
        <Icon name="copy" :size="13" /> 复制标题
      </button>
      <button type="button" class="xhs-copy-btn" @click="xhs.copy('body')">
        <Icon name="copy" :size="13" /> 复制正文
      </button>
      <button
        type="button"
        class="xhs-copy-btn"
        :style="{ background: 'var(--primary)', color: '#fff', borderColor: 'var(--primary)' }"
        @click="xhs.copy('full')"
      >
        <Icon name="copy" :size="13" /> 复制全文
      </button>
      <span :style="{ marginLeft: 'auto', fontSize: '12px', color: 'var(--ink-2)' }">
        {{ xhs.saving ? '保存中…' : (xhs.draftId ? '已保存' : '未保存') }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.xhs-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid var(--line-2);
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-copy-btn:hover {
  filter: brightness(0.97);
}
.xhs-tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--line-2);
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-tool-btn:hover {
  filter: brightness(0.97);
}
</style>
