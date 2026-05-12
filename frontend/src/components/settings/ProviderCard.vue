<script setup lang="ts">
/**
 * One LLM-provider tile inside ModelsSection.
 * Pulls keyring status, lets the user paste a key, run a connection test
 * (mock provider via /api/polish/block), and pin the provider as default.
 */
import { onMounted, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormInput from "@/components/forms/FormInput.vue";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";
import { keyringDelete, keyringSet, keyringStatus } from "@/api/client";
import { useSidecar } from "@/stores/sidecar";
import { confirmDialog } from "@/composables/useConfirm";

const props = defineProps<{
  provider: string;
  label: string;
  defaultModel: string;
}>();

const cfg = useConfig();
const toast = useToast();
const sidecar = useSidecar();

const hasKey = ref(false);
const newKey = ref("");
const testing = ref(false);
const lastTestOk = ref<boolean | null>(null);

async function refresh() {
  if (props.provider === "mock") {
    hasKey.value = true; // mock needs no key
    return;
  }
  try {
    const status = await keyringStatus(props.provider);
    hasKey.value = status.has_key;
  } catch (e: any) {
    toast.error(`读取密钥状态失败：${e?.message ?? e}`);
  }
}

async function saveKey() {
  if (!newKey.value.trim()) return;
  try {
    await keyringSet(props.provider, newKey.value.trim());
    newKey.value = "";
    hasKey.value = true;
    toast.success(`${props.label} 密钥已保存`);
  } catch (e: any) {
    toast.error(`保存失败：${e?.message ?? e}`);
  }
}

async function clearKey() {
  if (!(await confirmDialog(`确定从系统钥匙串删除 ${props.label} 的 API Key？`, { title: "删除 API Key" }))) return;
  try {
    await keyringDelete(props.provider);
    hasKey.value = false;
    toast.info(`${props.label} 密钥已清除`);
  } catch (e: any) {
    toast.error(`清除失败：${e?.message ?? e}`);
  }
}

async function setAsDefault() {
  await cfg.patch({ default_provider: props.provider });
  toast.success(`已切换默认提供商为 ${props.label}`);
}

async function testConnection() {
  testing.value = true;
  lastTestOk.value = null;
  try {
    // Lightweight ping via the polish endpoint with a tiny prompt.
    const resp = await sidecar.client.post("/api/polish/block", {
      text: "ping",
      provider: props.provider,
    });
    lastTestOk.value = Boolean(resp.data?.text);
    if (lastTestOk.value) {
      toast.success(`${props.label} 测试通过`);
    } else {
      toast.warn(`${props.label} 返回空响应`);
    }
  } catch (e: any) {
    lastTestOk.value = false;
    const detail = e?.response?.data?.detail || e?.message || String(e);
    toast.error(`${props.label} 测试失败：${detail}`);
  } finally {
    testing.value = false;
  }
}

const isDefault = () => cfg.data?.default_provider === props.provider;

onMounted(refresh);
</script>

<template>
  <div
    class="bg-card-2 border border-line"
    :style="{
      borderRadius: 'var(--radius-inner)',
      padding: '14px 16px',
    }"
  >
    <div class="mb-2 flex items-center justify-between gap-2">
      <div class="font-display text-[14px] font-semibold">{{ label }}</div>
      <Pill v-if="isDefault()" tone="primary">默认</Pill>
    </div>

    <div class="font-mono mb-3 text-[11px] text-ink-3">{{ defaultModel }}</div>

    <div class="mb-3 flex items-center gap-2 text-[12px]">
      <Pill v-if="provider === 'mock'">无需密钥</Pill>
      <template v-else>
        <Pill v-if="hasKey" tone="ok">已配置</Pill>
        <Pill v-else tone="warn">未配置</Pill>
      </template>
      <Pill v-if="lastTestOk === true" tone="ok">连接 ok</Pill>
      <Pill v-else-if="lastTestOk === false" tone="alert">连接失败</Pill>
    </div>

    <div v-if="provider !== 'mock'" class="mb-3 flex gap-2">
      <FormInput
        v-model="newKey"
        type="password"
        placeholder="粘贴 API Key…"
        debounce="live"
      />
      <Btn variant="solid" small :disabled="!newKey.trim()" @click="saveKey">保存</Btn>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <Btn variant="ghost" small :disabled="testing" @click="testConnection">
        <Spinner v-if="testing" :size="12" />
        <span>{{ testing ? "测试中…" : "测试连接" }}</span>
      </Btn>
      <Btn v-if="!isDefault()" variant="soft" small @click="setAsDefault">设为默认</Btn>
      <Btn v-if="provider !== 'mock' && hasKey" variant="ghost" small @click="clearKey">清除密钥</Btn>
    </div>
  </div>
</template>
