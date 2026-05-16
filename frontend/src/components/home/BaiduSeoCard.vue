<script setup lang="ts">
/**
 * 百度 SEO 首页卡 — 撮要展示百度关键词命中率 + 近期异动。
 * 数据：GET /api/monitor/history/baidu-keyword?range=7d。
 * "详情 →" 跳转到监测中心 baidu tab。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

const sidecar = useSidecar();
const router = useRouter();
const { whenReady } = useSidecarReady();

type ChangeKind = "down" | "up" | "new" | "dropped" | "flat";

interface Kpis {
  monitored_keywords: number;
  brands_covered: number;
  avg_match_rate_today: number;
  changed_keywords: number;
  changed_up: number;
  changed_down: number;
  captcha_count: number;
}
interface Keyword {
  task_id: number;
  task_name: string;
  search_keyword: string;
  target_brand: string;
  matched_count: number;
  top_n: number;
  matched_ranks: number[];
  best_rank: number;
  change_kind: ChangeKind;
  checked_at: string | null;
}
interface BaiduResponse {
  kpis: Kpis;
  keywords: Keyword[];
}

const data = ref<BaiduResponse | null>(null);
const loaded = ref(false);

// Sort keywords by severity: dropped/down first, then new/up, then flat.
const CHANGE_ORDER: Record<ChangeKind, number> = {
  dropped: 0,
  down: 1,
  new: 2,
  up: 3,
  flat: 4,
};

const topKeywords = computed<Keyword[]>(() => {
  if (!data.value) return [];
  return [...data.value.keywords]
    .sort((a, b) => CHANGE_ORDER[a.change_kind] - CHANGE_ORDER[b.change_kind])
    .slice(0, 4);
});

function formatCheckedAt(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
  } catch {
    return "—";
  }
}

function arrowFor(kind: ChangeKind): { glyph: string; color: string } {
  if (kind === "up" || kind === "new") return { glyph: "▲", color: "#5e7848" };
  if (kind === "down" || kind === "dropped") return { glyph: "▼", color: "var(--red)" };
  return { glyph: "—", color: "#a89f8d" };
}

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/baidu-keyword", {
      params: { range: "7d" },
    });
    data.value = r.data;
  } catch {
    /* 静默失败 — 空状态顶住 */
  } finally {
    loaded.value = true;
  }
});
</script>

<template>
  <section
    class="relative flex h-full flex-col overflow-hidden"
    :style="{
      background: 'var(--card)',
      borderRadius: 'var(--radius-card)',
      border: '1px solid var(--line)',
      padding: '16px',
    }"
  >
    <!-- 标题区 -->
    <div class="mb-3 flex flex-shrink-0 items-center justify-between">
      <div>
        <div
          class="text-[10.5px] font-medium uppercase tracking-[1.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          MONITOR · 百度 SEO
        </div>
        <div
          class="font-display mt-1 font-bold"
          :style="{ fontSize: '18px', letterSpacing: '-0.4px' }"
        >
          百度关键词
        </div>
        <!--
          副标题已收敛到「排名异动 N」单条 —— 原来「监测 X 关键词 / 覆盖 Y
          品牌词 / 平均命中率」这条信息密度高但首页卡用户主要关心异动，
          所以只保留异动计数；详细 KPI 在监测中心详情页查看。
        -->
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          <template v-if="!loaded">加载中…</template>
          <template v-else-if="data && data.kpis.monitored_keywords > 0">
            排名异动 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.changed_keywords }}</b>
          </template>
          <template v-else>暂无百度关键词任务</template>
        </div>
      </div>
      <button
        type="button"
        class="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px]"
        :style="{
          background: 'var(--card-2)',
          color: 'var(--ink-2)',
          border: '1px solid var(--line)',
        }"
        @click="router.push({ name: 'monitor', query: { tab: 'baidu' } })"
      >
        详情
        <Icon name="arrowRight" :size="10" />
      </button>
    </div>

    <!-- 异动摘要块已与副标题合并，避免重复显示「排名异动 N」 -->

    <!-- 关键词列表 -->
    <div
      v-if="!loaded"
      class="flex min-h-0 flex-1 items-center justify-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      加载中…
    </div>
    <div
      v-else-if="topKeywords.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无百度关键词任务<br />
      <span class="text-[11px]">前往监测中心添加</span>
    </div>
    <div v-else class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-for="kw in topKeywords" :key="kw.task_id"
        class="flex items-center gap-2 rounded-[8px] p-2"
        :style="{ border: '1px solid rgba(28,26,23,0.06)', marginBottom: '4px', background: 'var(--card-2)' }"
      >
        <span
          class="flex-shrink-0 text-[12px] font-bold w-3 text-center"
          :style="{ color: arrowFor(kw.change_kind).color }"
        >{{ arrowFor(kw.change_kind).glyph }}</span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[11.5px] font-medium">{{ kw.search_keyword }}</div>
          <div class="mt-0.5 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
            <template v-if="kw.matched_ranks.length">
              target: {{ kw.target_brand }} · 命中 {{ kw.matched_ranks.map((r) => '#' + r).join(' ') }} ({{ kw.matched_count }}/{{ kw.top_n }})
            </template>
            <template v-else>未命中</template>
          </div>
        </div>
        <span class="flex-shrink-0 text-[10px]" :style="{ color: 'var(--ink-4)' }">
          {{ formatCheckedAt(kw.checked_at) }}
        </span>
      </div>
    </div>
  </section>
</template>
