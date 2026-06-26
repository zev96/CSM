<script setup lang="ts">
/**
 * 模型单价设置卡 —— 让 AppConfig.pricing.* 能从 UI 改。
 * 读写走 useConfig；PATCH /api/config 对嵌套 dict 深合并，每个 model 只发自己那条。
 * 单价用于成稿区「≈¥」成本估算（token 为本地 CJK 估算，非真实分词）。
 */
import { onMounted, reactive, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormInput from "@/components/forms/FormInput.vue";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";

// 与后端 csm_core/llm/pricing.DEFAULT_PRICES 对齐（仅作占位/清单；真实算价在后端）。
const KNOWN: Record<string, { input: number; output: number }> = {
  "deepseek-chat": { input: 1.0, output: 2.0 },
  "deepseek-reasoner": { input: 1.0, output: 4.0 },
  "qwen-plus": { input: 0.8, output: 2.0 },
  "qwen-max": { input: 2.4, output: 9.6 },
  "qwen-turbo": { input: 0.3, output: 0.6 },
};

const cfg = useConfig();
const toast = useToast();
const loading = ref(false);
// 每 model 的当前覆盖值（空串=未覆盖，用默认占位）。
const prices = reactive<Record<string, { input: string; output: string }>>({});

function modelList(): string[] {
  const dm = (cfg.data?.default_model ?? {}) as Record<string, string>;
  const fromCfg = Object.values(dm).filter(Boolean);
  return Array.from(new Set([...Object.keys(KNOWN), ...fromCfg]));
}

function syncFromConfig() {
  const pr = (cfg.data?.pricing ?? {}) as Record<string, { input?: number; output?: number }>;
  for (const m of modelList()) {
    prices[m] = {
      input: pr[m]?.input != null ? String(pr[m].input) : "",
      output: pr[m]?.output != null ? String(pr[m].output) : "",
    };
  }
}

onMounted(async () => {
  if (!cfg.data) {
    loading.value = true;
    try { await cfg.load(); } catch { /* store 持有 error */ } finally { loading.value = false; }
  }
  syncFromConfig();
});

async function commit(model: string) {
  const row = prices[model];
  // 两格都空 = 不覆盖（删除该 model 的覆盖：发空对象会被深合并保留旧值，故只在有值时发）。
  const input = Number(row.input);
  const output = Number(row.output);
  if (!row.input.trim() || !row.output.trim() || Number.isNaN(input) || Number.isNaN(output)) {
    toast.info("单价两格都填正数才生效");
    return;
  }
  try {
    await cfg.patch({ pricing: { [model]: { input, output } } });
    toast.success("已保存");
  } catch (e: any) {
    toast.error(`保存失败：${cfg.error ?? e?.message ?? e}`);
    syncFromConfig();
  }
}
</script>

<template>
  <div class="rounded-card" :style="{ background: 'var(--card-2)', padding: '16px' }">
    <div class="flex items-center gap-2">
      <span class="inline-flex h-7 w-7 items-center justify-center rounded-lg" :style="{ background: 'var(--card)' }">
        <Icon name="stack" :size="15" />
      </span>
      <div>
        <div class="font-display text-[13.5px] font-semibold">模型单价</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          ¥/1M tokens · 用于成稿区成本估算（token 为本地估算，非真实分词）
        </div>
      </div>
    </div>

    <div v-if="loading" class="mt-3 flex items-center gap-2 text-sm" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="14" /> 读取中…
    </div>

    <div v-else class="mt-4 flex flex-col gap-3">
      <div v-for="m in modelList()" :key="m" class="flex items-center gap-3">
        <span class="text-[12px] font-mono flex-1 truncate" :title="m">{{ m }}</span>
        <FormInput :data-price-input="m" :model-value="prices[m]?.input" type="number" width="80" debounce="blur"
          :placeholder="String(KNOWN[m]?.input ?? '')"
          @update:model-value="(v: any) => (prices[m].input = String(v ?? ''))"
          @commit="() => commit(m)" />
        <span class="text-[10px]" :style="{ color: 'var(--ink-4)' }">入</span>
        <FormInput :data-price-output="m" :model-value="prices[m]?.output" type="number" width="80" debounce="blur"
          :placeholder="String(KNOWN[m]?.output ?? '')"
          @update:model-value="(v: any) => (prices[m].output = String(v ?? ''))"
          @commit="() => commit(m)" />
        <span class="text-[10px]" :style="{ color: 'var(--ink-4)' }">出</span>
      </div>
    </div>
  </div>
</template>
