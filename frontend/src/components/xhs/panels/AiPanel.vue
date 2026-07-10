<script setup lang="ts">
/**
 * AI 助手面板（设计稿 §5「AI 助手」/ §1 P3 / §4.6）。
 * 两个能力：① 生成整篇（输入主题 → title/body/topics 填入，编辑器非空先确认覆盖）；
 * ② 润色当前正文（小红书风改写后填回）。未配置 LLM → toast「去设置」跳 /settings。
 */
import { ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "@/components/ui/Icon.vue";
import { useXhs, LLMNotConfiguredError } from "@/stores/xhs";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const xhs = useXhs();
const toast = useToast();
const router = useRouter();

const intent = ref("");
const generating = ref(false);
const polishing = ref(false);

function handleAiError(err: unknown) {
  if (err instanceof LLMNotConfiguredError) {
    toast.error("请先在设置中配置 AI 服务", {
      actionLabel: "去设置",
      onAction: () => { router.push("/settings"); },
    });
  } else {
    toast.error("AI 服务调用失败，请稍后重试");
  }
}

async function generate() {
  const text = intent.value.trim();
  if (!text) { toast.warn("请先填写主题或关键词"); return; }
  if (generating.value) return;
  // 先确认覆盖再花 LLM 调用（取消则不请求）。
  if (!xhs.isEmpty) {
    const ok = await confirmDialog("AI 生成会覆盖当前的标题 / 正文 / 话题，确定吗？", {
      title: "AI 生成", okLabel: "覆盖", kind: "danger",
    });
    if (!ok) return;
  }
  generating.value = true;
  try {
    const result = await xhs.generateNote(text);
    xhs.applyTemplate({ title: result.title, body: result.body, topics: result.topics });
    toast.success("已填入 AI 生成内容");
  } catch (err) {
    handleAiError(err);
  } finally {
    generating.value = false;
  }
}

async function polish() {
  if (!xhs.body.trim()) { toast.warn("正文为空，先写点内容再润色"); return; }
  if (polishing.value) return;
  polishing.value = true;
  try {
    const text = await xhs.polishBody();
    xhs.setBody(text);
    toast.success("已润色正文");
  } catch (err) {
    handleAiError(err);
  } finally {
    polishing.value = false;
  }
}
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto" :style="{ gap: '16px' }">
    <!-- 生成整篇 -->
    <section :style="{ display: 'flex', flexDirection: 'column', gap: '8px' }">
      <div :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }">AI 生成整篇</div>
      <div :style="{ fontSize: '11px', color: 'var(--ink-2)' }">
        输入主题 / 关键词，生成标题 + 正文 + 话题（会覆盖当前内容，先确认）
      </div>
      <textarea
        v-model="intent"
        class="xhs-ai-input"
        placeholder="例：学生党平价护肤好物分享"
        rows="3"
      />
      <button
        type="button"
        class="xhs-ai-btn xhs-ai-btn-primary"
        :disabled="generating"
        @click="generate"
      >
        <Icon name="spark" :size="14" />
        {{ generating ? '生成中…' : '生成整篇' }}
      </button>
    </section>

    <div :style="{ height: '1px', background: 'var(--line-2)', flexShrink: 0 }" />

    <!-- 润色正文 -->
    <section :style="{ display: 'flex', flexDirection: 'column', gap: '8px' }">
      <div :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }">AI 润色正文</div>
      <div :style="{ fontSize: '11px', color: 'var(--ink-2)' }">
        把当前正文改写成更地道的小红书风（口语化 + emoji 排版）
      </div>
      <button
        type="button"
        class="xhs-ai-btn xhs-ai-btn-polish"
        :disabled="polishing"
        @click="polish"
      >
        <Icon name="wand" :size="14" />
        {{ polishing ? '润色中…' : '润色当前正文' }}
      </button>
    </section>

    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', marginTop: 'auto', flexShrink: 0 }">
      使用与「文章润色」相同的 AI 设置；未配置时会提示去设置。
    </div>
  </div>
</template>

<style scoped>
.xhs-ai-input {
  width: 100%;
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--card-white);
  color: var(--ink);
  font-size: 13px;
  line-height: 1.6;
  outline: none;
  resize: none;
  box-sizing: border-box;
  font-family: inherit;
}
.xhs-ai-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  padding: 9px 14px;
  border-radius: 10px;
  border: 1px solid var(--line-2);
  background: var(--card-white);
  color: var(--ink);
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-ai-btn:hover {
  filter: brightness(0.97);
}
.xhs-ai-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.xhs-ai-btn-primary {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
</style>
