<script setup lang="ts">
/** 生成契约设置卡 —— AppConfig.contract.mode 全局默认档（起飞可单次覆盖）。 */
import { onMounted, ref } from "vue";
import Icon from "@/components/ui/Icon.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";

const cfg = useConfig();
const toast = useToast();
const mode = ref<string>("conservative");

onMounted(async () => {
  if (!cfg.data) { try { await cfg.load(); } catch { /* store 持有 error */ } }
  mode.value = (cfg.data as any)?.contract?.mode ?? "conservative";
});

async function commit(v: string | number) {
  mode.value = String(v);
  try {
    await cfg.patch({ contract: { mode: mode.value } });
    toast.success("已保存");
  } catch (e: any) {
    toast.error(`保存失败：${cfg.error ?? e?.message ?? e}`);
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
        <div class="font-display text-[13.5px] font-semibold">生成契约</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          保守=保留全部信息点；激进=允许删减更精炼（有完整性警告兜底）。起飞时可单次覆盖。
        </div>
      </div>
    </div>
    <div class="mt-4" style="max-width: 260px">
      <FormSelect data-contract-mode :model-value="mode"
        :options="[
          { label: '保守（默认，保留全部信息点）', value: 'conservative' },
          { label: '激进（允许取舍删减）', value: 'aggressive' },
        ]"
        @update:model-value="commit" />
    </div>
  </div>
</template>
