<script setup lang="ts">
/**
 * 高权重信源榜卡（首页）—— 全部 GEO 任务近 7 天的高权重域名 top-N + 排名周对比。
 * 数据：GET /api/monitor/geo/citations/leaderboard?days=7&limit=8。
 * rank_delta：正=上升、负=下降、null=上一窗口未出现（新进）。
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

interface Row {
  domain: string;
  source_type: string;
  rank: number;
  rank_delta: number | null;
}

const sidecar = useSidecar();
const router = useRouter();
const { whenReady } = useSidecarReady();

const rows = ref<Row[]>([]);
const loaded = ref(false);

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/geo/citations/leaderboard", {
      params: { days: 7, limit: 8 },
    });
    rows.value = r.data?.leaderboard ?? [];
  } catch {
    /* 静默 */
  } finally {
    loaded.value = true;
  }
});

function deltaStyle(d: number | null) {
  if (d === null) return { background: "var(--yellow-soft)", color: "#7a5400" }; // 新进
  if (d > 0) return { background: "#dde7d2", color: "#4d6b2f" };
  if (d < 0) return { background: "#f3d3cd", color: "#a3382a" };
  return { background: "rgba(var(--ink-rgb),0.06)", color: "var(--ink-2)" };
}
function deltaText(d: number | null) {
  return d === null ? "新" : d === 0 ? "—" : String(Math.abs(d));
}
</script>

<template>
  <section
    class="card-frosted relative flex h-full flex-col overflow-hidden"
    :style="{ padding: '16px' }"
  >
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">高权重信源</div>
      <button
        type="button"
        class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情"
        @click="router.push({ name: 'monitor', query: { tab: 'geo' } })"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <div
      v-if="loaded && rows.length === 0"
      class="flex min-h-0 flex-1 flex-col items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无信源数据<br /><span class="text-[11px]">跑 GEO 监测后自动统计</span>
    </div>
    <div v-else class="mt-2 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <div
        v-for="r in rows"
        :key="r.domain"
        class="flex items-center gap-2 rounded-[10px] px-2 py-1.5"
      >
        <span
          class="font-mono w-4 flex-shrink-0 text-[12px] tabular-nums"
          :style="{ color: 'var(--ink-3)' }"
          >{{ r.rank }}</span
        >
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12px]" :style="{ color: 'var(--ink)' }">{{ r.domain }}</div>
        </div>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="deltaStyle(r.rank_delta)"
        >
          <Icon v-if="r.rank_delta !== null && r.rank_delta > 0" name="arrowUp" :size="9" />
          <Icon v-else-if="r.rank_delta !== null && r.rank_delta < 0" name="arrowDown" :size="9" />
          {{ deltaText(r.rank_delta) }}
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.trend-detail {
  background: rgba(var(--ink-rgb), 0.04);
  color: var(--ink-2);
  border: 1px solid rgba(var(--ink-rgb), 0.06);
  transition: background-color 0.12s ease;
}
.trend-detail:hover {
  background: rgba(var(--ink-rgb), 0.08);
}
</style>
