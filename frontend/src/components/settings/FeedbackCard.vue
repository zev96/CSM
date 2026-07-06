<script setup lang="ts">
/**
 * 反馈学习设置卡 —— AppConfig.feedback.*（record 默认开静默采集、rank 默认关）。
 * 读写走 useConfig；PATCH /api/config 对嵌套 dict 深合并，故每个控件只发自己那一个字段。
 */
import { onMounted, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormToggle from "@/components/forms/FormToggle.vue";
import FormInput from "@/components/forms/FormInput.vue";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";

const cfg = useConfig();
const toast = useToast();
const loading = ref(false);

const record = ref(true);
const rank = ref(false);
const minSamples = ref<number>(5);

function syncFromConfig() {
  const fb = (cfg.data?.feedback ?? {}) as Record<string, any>;
  record.value = fb.record !== false; // 默认 true
  rank.value = !!fb.rank;
  minSamples.value = Number(fb.min_samples ?? 5);
}

onMounted(async () => {
  if (!cfg.data) {
    loading.value = true;
    try { await cfg.load(); } catch { /* error 由 store 持有 */ } finally { loading.value = false; }
  }
  syncFromConfig();
});

async function save(patch: Record<string, unknown>) {
  try {
    await cfg.patch({ feedback: patch });
    toast.success("已保存");
  } catch (e: any) {
    toast.error(`保存失败：${cfg.error ?? e?.message ?? e}`);
    syncFromConfig(); // 回滚 UI 到真实值
  }
}

function onRecord(v: boolean) { record.value = v; save({ record: v }); }
function onRank(v: boolean) { rank.value = v; save({ rank: v }); }
function commitMinSamples(v: number | string | null) {
  const n = Math.max(1, Math.min(50, Number(v) || 5));
  minSamples.value = n;
  save({ min_samples: n });
}
</script>

<template>
  <div class="rounded-card" :style="{ background: 'var(--card-2)', padding: '16px' }">
    <div class="flex items-center gap-2">
      <span class="inline-flex h-7 w-7 items-center justify-center rounded-lg" :style="{ background: 'var(--card)' }">
        <Icon name="stack" :size="15" />
      </span>
      <div>
        <div class="font-display text-[13.5px] font-semibold">反馈学习</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          导出后静默记录成稿表现 · 可选反哺素材采样（同种子仍可复现）
        </div>
      </div>
    </div>

    <div v-if="loading" class="mt-3 flex items-center gap-2 text-sm" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="14" /> 读取中…
    </div>

    <div v-else class="mt-4 flex flex-col gap-4">
      <FormField label="记录导出用于学习"
        hint="导出后静默落一条成稿记录（编辑量/素材用量/评分）。默认开，绝不影响导出。">
        <span data-test="toggle-feedback-record">
          <FormToggle :model-value="record" @update:model-value="onRecord" />
        </span>
      </FormField>

      <FormField label="用反馈微调采样"
        hint="按素材历史「改得少=好用」加权采样。默认关；同种子仍确定可复现（零回归）。">
        <span data-test="toggle-feedback-rank">
          <FormToggle :model-value="rank" @update:model-value="onRank" />
        </span>
      </FormField>

      <FormField label="最小样本数" hint="某素材累计导出达此数才纳入加权（不足则不影响采样）">
        <FormInput :model-value="minSamples" type="number" width="90" debounce="blur"
          @commit="commitMinSamples" />
      </FormField>
    </div>
  </div>
</template>
