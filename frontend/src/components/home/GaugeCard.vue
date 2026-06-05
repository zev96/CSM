<script setup lang="ts">
/**
 * GEO 半圆仪表盘卡（首页）—— 全局品牌曝光率 soc(0-100) + 较上周 delta。
 * 数据：GET /api/monitor/geo/summary?range=7d → { soc, delta, band }。
 * band 复用后端 geo.metrics 阈值（hidden<0.2 / weak<0.5 / strong）。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

const sidecar = useSidecar();
const router = useRouter();
const { whenReady } = useSidecarReady();

const soc = ref(0);
const delta = ref(0);
const band = ref<"hidden" | "weak" | "strong">("hidden");
const loaded = ref(false);

const pct = computed(() => Math.round(soc.value * 100));
const deltaPct = computed(() => Math.round(delta.value * 100));
const BAND_LABEL = { hidden: "低曝光", weak: "中等曝光", strong: "高曝光" } as const;

// 半圆：半径 80，弧从左端 (10,90) 经顶 bulge 到右端 (170,90)。弧长 = π·r。
const R = 80;
const ARC = Math.PI * R;
const ARC_PATH = `M 10 ${R + 10} A ${R} ${R} 0 0 1 ${R * 2 + 10} ${R + 10}`;
const dash = computed(() => `${(pct.value / 100) * ARC} ${ARC}`);
const arcColor = computed(() =>
  pct.value >= 50 ? "var(--green)" : pct.value >= 20 ? "#e8a04a" : "var(--red)",
);

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/geo/summary", {
      params: { range: "7d" },
    });
    soc.value = r.data?.soc ?? 0;
    delta.value = r.data?.delta ?? 0;
    band.value = r.data?.band ?? "hidden";
  } catch {
    /* 静默 */
  } finally {
    loaded.value = true;
  }
});
</script>

<template>
  <section
    class="card-frosted relative flex h-full flex-col overflow-hidden"
    :style="{ padding: '16px', containerType: 'size' }"
  >
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">GEO</div>
      <button
        type="button"
        class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情"
        @click="router.push({ name: 'monitor', query: { tab: 'geo' } })"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <div class="flex min-h-0 flex-1 flex-col items-center justify-center">
      <svg :viewBox="`0 0 ${R * 2 + 20} ${R + 30}`" :style="{ width: '100%', maxWidth: 'clamp(150px, 84cqh, 380px)' }">
        <path :d="ARC_PATH" fill="none" stroke="rgba(28,26,23,0.08)" :stroke-width="12" stroke-linecap="round" />
        <path
          :d="ARC_PATH"
          fill="none"
          :stroke="arcColor"
          :stroke-width="12"
          stroke-linecap="round"
          :stroke-dasharray="dash"
          :style="{ transition: 'stroke-dasharray .6s ease' }"
        />
        <text :x="R + 10" :y="R + 2" text-anchor="middle" class="font-display font-bold" :style="{ fontSize: '34px', fill: 'var(--ink)' }">
          {{ loaded ? pct : "—" }}
        </text>
        <text :x="R + 10" :y="R + 22" text-anchor="middle" :style="{ fontSize: '11px', fill: arcColor }">
          {{ BAND_LABEL[band] }}
        </text>
      </svg>
      <span
        v-if="loaded"
        class="mt-3 inline-flex h-5 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
        :style="
          deltaPct > 0
            ? { background: '#dde7d2', color: '#4d6b2f' }
            : deltaPct < 0
              ? { background: '#f3d3cd', color: '#a3382a' }
              : { background: 'rgba(28,26,23,0.06)', color: 'var(--ink-2)' }
        "
      >
        <Icon v-if="deltaPct > 0" name="arrowUp" :size="9" />
        <Icon v-else-if="deltaPct < 0" name="arrowDown" :size="9" />
        {{ Math.abs(deltaPct) }}% 较上周
      </span>
    </div>
  </section>
</template>

<style scoped>
.trend-detail {
  background: rgba(28, 26, 23, 0.04);
  color: var(--ink-2);
  border: 1px solid rgba(28, 26, 23, 0.06);
  transition: background-color 0.12s ease;
}
.trend-detail:hover {
  background: rgba(28, 26, 23, 0.08);
}
</style>
