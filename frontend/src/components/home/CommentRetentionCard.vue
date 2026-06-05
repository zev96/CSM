<script setup lang="ts">
/**
 * 评论留存率卡（首页）—— 改用专用 7 天端点。
 *   大% = 各平台今日聚合 retained/total；徽章 = 较上周（rate_prev）；
 *   折线 = 每日留存率；平台 tab（全部 / B站 / 快手 / 抖音）切换。
 * 数据：GET /api/monitor/history/comment-retention?range=7d。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

interface DayPoint {
  date: string;
  retained: number;
  total: number;
  rate: number;
}
interface PlatformData {
  label: string;
  current_retained: number;
  current_total: number;
  rate_today: number;
  rate_prev: number;
  daily_series: DayPoint[];
}

const sidecar = useSidecar();
const router = useRouter();
const { whenReady } = useSidecarReady();

const platforms = ref<Record<string, PlatformData>>({});
const loaded = ref(false);

const ORDER: [string, string][] = [
  ["bilibili_comment", "B 站"],
  ["kuaishou_comment", "快手"],
  ["douyin_comment", "抖音"],
];
const activeKey = ref<string | null>(null); // null = 聚合

const available = computed(() => ORDER.filter(([k]) => platforms.value[k]));

const aggRate = computed(() => {
  let ret = 0;
  let tot = 0;
  for (const [k] of available.value) {
    const p = platforms.value[k];
    ret += p.current_retained;
    tot += p.current_total;
  }
  return tot ? ret / tot : 0;
});
// rate_prev 按今日 total 加权聚合（各平台体量不同，简单平均会偏）。
const aggPrev = computed(() => {
  let s = 0;
  let tot = 0;
  for (const [k] of available.value) {
    const p = platforms.value[k];
    s += p.rate_prev * p.current_total;
    tot += p.current_total;
  }
  return tot ? s / tot : 0;
});

const shownRate = computed(() =>
  activeKey.value ? (platforms.value[activeKey.value]?.rate_today ?? 0) : aggRate.value,
);
const shownPrev = computed(() =>
  activeKey.value ? (platforms.value[activeKey.value]?.rate_prev ?? 0) : aggPrev.value,
);
const deltaPct = computed(() => Math.round((shownRate.value - shownPrev.value) * 100));

// 折线：单平台 → 其每日 rate；聚合 → 逐日跨平台 sum(retained)/sum(total)。
const series = computed<number[]>(() => {
  if (activeKey.value) {
    return (platforms.value[activeKey.value]?.daily_series ?? []).map((d) =>
      Math.round(d.rate * 100),
    );
  }
  const avail = available.value.map(([k]) => platforms.value[k]);
  const len = avail.reduce((m, p) => Math.max(m, p.daily_series?.length ?? 0), 0);
  const out: number[] = [];
  for (let i = 0; i < len; i++) {
    let ret = 0;
    let tot = 0;
    for (const p of avail) {
      const d = p.daily_series?.[i];
      if (d) {
        ret += d.retained;
        tot += d.total;
      }
    }
    out.push(tot ? Math.round((ret / tot) * 100) : 0);
  }
  return out;
});

const sparkColor = computed(() => {
  const p = Math.round(shownRate.value * 100);
  return p >= 80 ? "var(--green)" : p >= 50 ? "#e8a04a" : "var(--red)";
});

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/comment-retention", {
      params: { range: "7d" },
    });
    platforms.value = r.data?.platforms ?? {};
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
    :style="{ padding: '16px' }"
  >
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">评论留存率</div>
      <button
        type="button"
        class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情"
        @click="router.push({ name: 'monitor', query: { tab: 'comment' } })"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <div class="mt-2 flex flex-shrink-0 items-baseline gap-2">
      <div
        class="font-display font-bold"
        :style="{ fontSize: '40px', lineHeight: 1, letterSpacing: '-1px', color: 'var(--ink)' }"
      >
        {{ available.length ? Math.round(shownRate * 100) + "%" : "—" }}
      </div>
      <span
        v-if="available.length"
        class="inline-flex h-5 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
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
        {{ Math.abs(deltaPct) }}%
      </span>
    </div>

    <div class="mt-2 mb-2 flex-shrink-0">
      <Sparkline
        :points="series"
        :height="48"
        :stroke="sparkColor"
        :show-last="true"
        :y-min="0"
        :y-max="100"
        fluid
      />
    </div>

    <div
      v-if="loaded && available.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无评论留存数据
    </div>
    <div v-else class="mt-auto flex flex-shrink-0 gap-1">
      <button
        type="button"
        class="rounded-full px-2.5 py-1 text-[11px]"
        :style="
          activeKey === null
            ? { background: 'var(--ink)', color: '#fff' }
            : { background: 'var(--card-2)', color: 'var(--ink-2)' }
        "
        @click="activeKey = null"
      >
        全部
      </button>
      <button
        v-for="[k, label] in available"
        :key="k"
        type="button"
        class="rounded-full px-2.5 py-1 text-[11px]"
        :style="
          activeKey === k
            ? { background: 'var(--ink)', color: '#fff' }
            : { background: 'var(--card-2)', color: 'var(--ink-2)' }
        "
        @click="activeKey = k"
      >
        {{ label }}
      </button>
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
