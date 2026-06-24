<script setup lang="ts">
/**
 * 品牌记忆设置卡（Phase 1 Plan 6 补遗）——让 brand_memory.* 能从 UI 开。
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

const inject = ref(false);
const factcheck = ref(false);
const ownBrands = ref("");
const variantCap = ref<number>(3);
const endorsementCap = ref<number>(5);

function syncFromConfig() {
  const bm = (cfg.data?.brand_memory ?? {}) as Record<string, any>;
  inject.value = !!bm.inject;
  factcheck.value = !!bm.factcheck;
  ownBrands.value = (bm.own_brands ?? []).join("、");
  variantCap.value = Number(bm.inject_variant_cap ?? 3);
  endorsementCap.value = Number(bm.inject_endorsement_cap ?? 5);
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
    await cfg.patch({ brand_memory: patch });
    toast.success("已保存");
  } catch (e: any) {
    toast.error(`保存失败：${cfg.error ?? e?.message ?? e}`);
    syncFromConfig();   // 回滚 UI 到真实值
  }
}

function onInject(v: boolean) { inject.value = v; save({ inject: v }); }
function onFactcheck(v: boolean) { factcheck.value = v; save({ factcheck: v }); }
function commitOwnBrands() {
  const list = ownBrands.value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean);
  save({ own_brands: list });
}
function commitVariantCap(v: number | string | null) {
  const n = Math.max(1, Number(v) || 3); variantCap.value = n; save({ inject_variant_cap: n });
}
function commitEndorsementCap(v: number | string | null) {
  const n = Math.max(1, Number(v) || 5); endorsementCap.value = n; save({ inject_endorsement_cap: n });
}
</script>

<template>
  <div class="rounded-card" :style="{ background: 'var(--card-2)', padding: '16px' }">
    <div class="flex items-center gap-2">
      <span class="inline-flex h-7 w-7 items-center justify-center rounded-lg" :style="{ background: 'var(--card)' }">
        <Icon name="stack" :size="15" />
      </span>
      <div>
        <div class="font-display text-[13.5px] font-semibold">品牌记忆</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          生成时注入型号事实 · 导出前事实核对 · 自有品牌
        </div>
      </div>
    </div>

    <div v-if="loading" class="mt-3 flex items-center gap-2 text-sm" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="14" /> 读取中…
    </div>

    <div v-else class="mt-4 flex flex-col gap-4">
      <FormField label="注入型号记忆" hint="生成时把命中型号的参数/认证/话术注入 LLM（关=今天行为）">
        <span data-test="toggle-inject">
          <FormToggle :model-value="inject" @update:model-value="onInject" />
        </span>
      </FormField>

      <FormField label="导出前事实核对" hint="成稿里白名单外的数字/认证拦截导出，弹审查面板放行">
        <span data-test="toggle-factcheck">
          <FormToggle :model-value="factcheck" @update:model-value="onFactcheck" />
        </span>
      </FormField>

      <FormField label="自有品牌" hint="判定主推 vs 竞品（顿号/逗号分隔，如 CEWEY、希喂）">
        <span data-test="own-brands">
          <FormInput :model-value="ownBrands" debounce="blur"
            @update:model-value="(v: any) => (ownBrands = String(v ?? ''))"
            @commit="commitOwnBrands" placeholder="CEWEY、希喂" />
        </span>
      </FormField>

      <div class="flex gap-4">
        <FormField label="话术变体上限/维度" hint="token 预算">
          <FormInput :model-value="variantCap" type="number" width="90" debounce="blur"
            @commit="commitVariantCap" />
        </FormField>
        <FormField label="背书注入条数上限" hint="token 预算">
          <FormInput :model-value="endorsementCap" type="number" width="90" debounce="blur"
            @commit="commitEndorsementCap" />
        </FormField>
      </div>
    </div>
  </div>
</template>
