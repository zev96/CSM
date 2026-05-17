<script setup lang="ts">
/**
 * Outreach AI prompt 自定义卡片，挂在「设置 → 模型」section。
 *
 * 后端契约（design §4.6）：
 *   GET  /api/mining/ai_prompts
 *     → { summary: {current, default}, suggest: {current, default},
 *         vars: { summary: [...], suggest: [...] } }
 *   PATCH /api/mining/ai_prompts
 *     Body: { summary?: string, suggest?: string }
 *     传 "" = 清回 default
 *
 * UI 状态：
 *   - 两段 textarea 各自维护 draft（用户当前输入）+ baseline（最近一次
 *     成功 PATCH 拿到的 current）；"保存"按钮只有 draft ≠ baseline 才亮
 *     起来。"重置为默认"直接 PATCH "" 然后把 baseline 同步为空。
 *   - 顶部小 Pill 标 "默认" / "自定义" —— baseline === "" 即默认。
 */
import { computed, onMounted, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

interface PromptPair {
  current: string;
  default: string;
}

interface AIPromptsResponse {
  summary: PromptPair;
  suggest: PromptPair;
  vars: {
    summary: string[];
    suggest: string[];
  };
}

const sidecar = useSidecar();
const toast = useToast();

const loading = ref(true);
const summaryDraft = ref("");
const summaryBaseline = ref("");
const summaryDefault = ref("");
const summaryVars = ref<string[]>([]);
const summarySaving = ref(false);

const suggestDraft = ref("");
const suggestBaseline = ref("");
const suggestDefault = ref("");
const suggestVars = ref<string[]>([]);
const suggestSaving = ref(false);

const summaryDirty = computed(() => summaryDraft.value !== summaryBaseline.value);
const suggestDirty = computed(() => suggestDraft.value !== suggestBaseline.value);

const summaryIsDefault = computed(() => summaryBaseline.value.trim() === "");
const suggestIsDefault = computed(() => suggestBaseline.value.trim() === "");

function fmtVars(vars: string[]): string {
  return vars.map(v => `{${v}}`).join(" · ");
}

async function load() {
  loading.value = true;
  try {
    const resp = await sidecar.client.get<AIPromptsResponse>("/api/mining/ai_prompts");
    summaryBaseline.value = resp.data.summary?.current ?? "";
    summaryDefault.value = resp.data.summary?.default ?? "";
    summaryDraft.value = summaryBaseline.value;
    summaryVars.value = resp.data.vars?.summary ?? [];

    suggestBaseline.value = resp.data.suggest?.current ?? "";
    suggestDefault.value = resp.data.suggest?.default ?? "";
    suggestDraft.value = suggestBaseline.value;
    suggestVars.value = resp.data.vars?.suggest ?? [];
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("读取 AI prompt 失败" + (detail ? "：" + detail : ""));
  } finally {
    loading.value = false;
  }
}

async function patchPrompts(
  body: { summary?: string; suggest?: string },
): Promise<AIPromptsResponse> {
  const resp = await sidecar.client.patch<AIPromptsResponse>(
    "/api/mining/ai_prompts",
    body,
  );
  return resp.data;
}

async function saveSummary() {
  if (!summaryDirty.value || summarySaving.value) return;
  summarySaving.value = true;
  try {
    const data = await patchPrompts({ summary: summaryDraft.value });
    summaryBaseline.value = data.summary?.current ?? "";
    summaryDraft.value = summaryBaseline.value;
    toast.success("AI 速览 prompt 已保存");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("保存失败" + (detail ? "：" + detail : ""));
  } finally {
    summarySaving.value = false;
  }
}

async function resetSummary() {
  if (summarySaving.value) return;
  summarySaving.value = true;
  try {
    const data = await patchPrompts({ summary: "" });
    summaryBaseline.value = data.summary?.current ?? "";
    summaryDraft.value = summaryBaseline.value;
    toast.success("已重置为默认");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("重置失败" + (detail ? "：" + detail : ""));
  } finally {
    summarySaving.value = false;
  }
}

async function saveSuggest() {
  if (!suggestDirty.value || suggestSaving.value) return;
  suggestSaving.value = true;
  try {
    const data = await patchPrompts({ suggest: suggestDraft.value });
    suggestBaseline.value = data.suggest?.current ?? "";
    suggestDraft.value = suggestBaseline.value;
    toast.success("AI 建议 prompt 已保存");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("保存失败" + (detail ? "：" + detail : ""));
  } finally {
    suggestSaving.value = false;
  }
}

async function resetSuggest() {
  if (suggestSaving.value) return;
  suggestSaving.value = true;
  try {
    const data = await patchPrompts({ suggest: "" });
    suggestBaseline.value = data.suggest?.current ?? "";
    suggestDraft.value = suggestBaseline.value;
    toast.success("已重置为默认");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("重置失败" + (detail ? "：" + detail : ""));
  } finally {
    suggestSaving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div
    :style="{
      background: 'var(--card-2)',
      border: '1px solid var(--line)',
      borderRadius: '14px',
      padding: '16px',
    }"
  >
    <!-- Header -->
    <div class="flex items-center gap-2">
      <span
        class="inline-flex items-center justify-center"
        :style="{
          width: '28px', height: '28px',
          borderRadius: '8px',
          background: 'var(--dark)',
          color: 'var(--yellow)',
        }"
      ><Icon name="spark" :size="13"/></span>
      <div>
        <div class="font-display text-[13.5px] font-semibold">Outreach AI 提示词</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          自定义抓取功能里 AI 速览 / AI 建议 用的 prompt. 留空 = 用内置默认
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="mt-4 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="12"/>
      <span>读取中…</span>
    </div>

    <template v-else>
      <!-- AI 速览 -->
      <div class="mt-4">
        <div class="flex items-center gap-2">
          <div class="text-[12.5px] font-semibold">AI 速览</div>
          <Pill v-if="summaryIsDefault">默认</Pill>
          <Pill v-else tone="primary">自定义</Pill>
        </div>
        <div
          class="mt-1 font-mono text-[10.5px]"
          :style="{ color: 'var(--ink-3)' }"
          :title="'每次生成时会用对应视频字段替换'"
        >
          可用占位符: {{ fmtVars(summaryVars) }}
        </div>
        <textarea
          v-model="summaryDraft"
          :placeholder="summaryDefault || '输入自定义 AI 速览 prompt…'"
          rows="4"
          class="mt-2 w-full outline-none"
          :style="{
            padding: '10px 12px',
            borderRadius: '10px',
            background: 'var(--card-white)',
            border: '1px solid var(--line)',
            fontSize: '12px',
            lineHeight: 1.55,
            color: 'var(--ink)',
            fontFamily: 'ui-monospace, SFMono-Regular, monospace',
            minHeight: '100px',
            resize: 'vertical',
          }"
        />
        <div class="mt-2 flex items-center gap-2">
          <Btn
            variant="solid"
            small
            :disabled="!summaryDirty || summarySaving"
            @click="saveSummary"
          >
            <Spinner v-if="summarySaving" :size="11"/>
            <span>{{ summarySaving ? "保存中…" : "保存" }}</span>
          </Btn>
          <Btn
            variant="ghost"
            small
            :disabled="summaryIsDefault || summarySaving"
            @click="resetSummary"
          >
            <Icon name="refresh" :size="11"/>
            <span>重置为默认</span>
          </Btn>
        </div>
      </div>

      <!-- 分隔线 -->
      <div :style="{ height: '1px', background: 'var(--line)', margin: '18px 0' }"/>

      <!-- AI 建议 -->
      <div>
        <div class="flex items-center gap-2">
          <div class="text-[12.5px] font-semibold">AI 建议</div>
          <Pill v-if="suggestIsDefault">默认</Pill>
          <Pill v-else tone="primary">自定义</Pill>
        </div>
        <div
          class="mt-1 font-mono text-[10.5px]"
          :style="{ color: 'var(--ink-3)' }"
          :title="'每次生成时会用对应视频字段 + 上下文替换'"
        >
          可用占位符: {{ fmtVars(suggestVars) }}
        </div>
        <textarea
          v-model="suggestDraft"
          :placeholder="suggestDefault || '输入自定义 AI 建议 prompt…'"
          rows="4"
          class="mt-2 w-full outline-none"
          :style="{
            padding: '10px 12px',
            borderRadius: '10px',
            background: 'var(--card-white)',
            border: '1px solid var(--line)',
            fontSize: '12px',
            lineHeight: 1.55,
            color: 'var(--ink)',
            fontFamily: 'ui-monospace, SFMono-Regular, monospace',
            minHeight: '100px',
            resize: 'vertical',
          }"
        />
        <div class="mt-2 flex items-center gap-2">
          <Btn
            variant="solid"
            small
            :disabled="!suggestDirty || suggestSaving"
            @click="saveSuggest"
          >
            <Spinner v-if="suggestSaving" :size="11"/>
            <span>{{ suggestSaving ? "保存中…" : "保存" }}</span>
          </Btn>
          <Btn
            variant="ghost"
            small
            :disabled="suggestIsDefault || suggestSaving"
            @click="resetSuggest"
          >
            <Icon name="refresh" :size="11"/>
            <span>重置为默认</span>
          </Btn>
        </div>
      </div>
    </template>
  </div>
</template>
