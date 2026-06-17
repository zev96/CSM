<script setup lang="ts">
/**
 * 小红书 AI 提示词自定义卡片，挂在「设置 → 模型」section。
 *
 * 后端契约：
 *   GET  /api/xhs/ai_prompts
 *     → { generate: {current, default}, polish: {current, default} }
 *   PATCH /api/xhs/ai_prompts
 *     Body: { generate?: string, polish?: string }
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

interface XhsAIPromptsResponse {
  generate: PromptPair;
  polish: PromptPair;
}

const sidecar = useSidecar();
const toast = useToast();

const loading = ref(true);

const generateDraft = ref("");
const generateBaseline = ref("");
const generateDefault = ref("");
const generateSaving = ref(false);

const polishDraft = ref("");
const polishBaseline = ref("");
const polishDefault = ref("");
const polishSaving = ref(false);

const generateDirty = computed(() => generateDraft.value !== generateBaseline.value);
const polishDirty = computed(() => polishDraft.value !== polishBaseline.value);

const generateIsDefault = computed(() => generateBaseline.value.trim() === "");
const polishIsDefault = computed(() => polishBaseline.value.trim() === "");

async function load() {
  loading.value = true;
  try {
    const resp = await sidecar.client.get<XhsAIPromptsResponse>("/api/xhs/ai_prompts");
    generateBaseline.value = resp.data.generate?.current ?? "";
    generateDefault.value = resp.data.generate?.default ?? "";
    generateDraft.value = generateBaseline.value;

    polishBaseline.value = resp.data.polish?.current ?? "";
    polishDefault.value = resp.data.polish?.default ?? "";
    polishDraft.value = polishBaseline.value;
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("读取小红书 AI prompt 失败" + (detail ? "：" + detail : ""));
  } finally {
    loading.value = false;
  }
}

async function patchPrompts(
  body: { generate?: string; polish?: string },
): Promise<XhsAIPromptsResponse> {
  const resp = await sidecar.client.patch<XhsAIPromptsResponse>(
    "/api/xhs/ai_prompts",
    body,
  );
  return resp.data;
}

async function saveGenerate() {
  if (!generateDirty.value || generateSaving.value) return;
  generateSaving.value = true;
  try {
    const data = await patchPrompts({ generate: generateDraft.value });
    generateBaseline.value = data.generate?.current ?? "";
    generateDraft.value = generateBaseline.value;
    toast.success("AI 生成整篇 prompt 已保存");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("保存失败" + (detail ? "：" + detail : ""));
  } finally {
    generateSaving.value = false;
  }
}

async function resetGenerate() {
  if (generateSaving.value) return;
  generateSaving.value = true;
  try {
    const data = await patchPrompts({ generate: "" });
    generateBaseline.value = data.generate?.current ?? "";
    generateDraft.value = generateBaseline.value;
    toast.success("已重置为默认");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("重置失败" + (detail ? "：" + detail : ""));
  } finally {
    generateSaving.value = false;
  }
}

async function savePolish() {
  if (!polishDirty.value || polishSaving.value) return;
  polishSaving.value = true;
  try {
    const data = await patchPrompts({ polish: polishDraft.value });
    polishBaseline.value = data.polish?.current ?? "";
    polishDraft.value = polishBaseline.value;
    toast.success("AI 润色正文 prompt 已保存");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("保存失败" + (detail ? "：" + detail : ""));
  } finally {
    polishSaving.value = false;
  }
}

async function resetPolish() {
  if (polishSaving.value) return;
  polishSaving.value = true;
  try {
    const data = await patchPrompts({ polish: "" });
    polishBaseline.value = data.polish?.current ?? "";
    polishDraft.value = polishBaseline.value;
    toast.success("已重置为默认");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("重置失败" + (detail ? "：" + detail : ""));
  } finally {
    polishSaving.value = false;
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
        <div class="font-display text-[13.5px] font-semibold">小红书 AI 提示词</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          自定义小红书编辑器里 AI 生成整篇 / AI 润色正文 用的 prompt. 留空 = 用内置默认
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="mt-4 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="12"/>
      <span>读取中…</span>
    </div>

    <template v-else>
      <!-- AI 生成整篇 -->
      <div class="mt-4">
        <div class="flex items-center gap-2">
          <div class="text-[12.5px] font-semibold">AI 生成整篇</div>
          <Pill v-if="generateIsDefault">默认</Pill>
          <Pill v-else tone="primary">自定义</Pill>
        </div>
        <textarea
          v-model="generateDraft"
          :placeholder="generateDefault || '输入自定义 AI 生成整篇 prompt…'"
          rows="4"
          class="mt-2 w-full outline-none"
          data-test="textarea-generate"
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
            :disabled="!generateDirty || generateSaving"
            data-test="save-generate"
            @click="saveGenerate"
          >
            <Spinner v-if="generateSaving" :size="11"/>
            <span>{{ generateSaving ? "保存中…" : "保存" }}</span>
          </Btn>
          <Btn
            variant="ghost"
            small
            :disabled="generateIsDefault || generateSaving"
            data-test="reset-generate"
            @click="resetGenerate"
          >
            <Icon name="refresh" :size="11"/>
            <span>重置为默认</span>
          </Btn>
        </div>
      </div>

      <!-- 分隔线 -->
      <div :style="{ height: '1px', background: 'var(--line)', margin: '18px 0' }"/>

      <!-- AI 润色正文 -->
      <div>
        <div class="flex items-center gap-2">
          <div class="text-[12.5px] font-semibold">AI 润色正文</div>
          <Pill v-if="polishIsDefault">默认</Pill>
          <Pill v-else tone="primary">自定义</Pill>
        </div>
        <textarea
          v-model="polishDraft"
          :placeholder="polishDefault || '输入自定义 AI 润色正文 prompt…'"
          rows="4"
          class="mt-2 w-full outline-none"
          data-test="textarea-polish"
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
            :disabled="!polishDirty || polishSaving"
            data-test="save-polish"
            @click="savePolish"
          >
            <Spinner v-if="polishSaving" :size="11"/>
            <span>{{ polishSaving ? "保存中…" : "保存" }}</span>
          </Btn>
          <Btn
            variant="ghost"
            small
            :disabled="polishIsDefault || polishSaving"
            data-test="reset-polish"
            @click="resetPolish"
          >
            <Icon name="refresh" :size="11"/>
            <span>重置为默认</span>
          </Btn>
        </div>
      </div>
    </template>
  </div>
</template>
