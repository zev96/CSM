<script setup lang="ts">
/**
 * 百度 SEO 首页卡 — Row 2 第 1 张。
 *
 *   ┌─────────────────────────────────────────┐
 *   │ MONITOR · 百度 SEO              [详情→]│
 *   │ 宠物家庭吸尘器推荐  近 7 天             │
 *   │ ◢ sparkline ◣                            │
 *   │ 周一  周二 ... 今天                       │
 *   │ ┌─────────────────────────────────────┐ │
 *   │ │ ★ 宠物家庭吸尘器推荐         [↗2]   │ │  ← 高亮主项
 *   │ ├─────────────────────────────────────┤ │
 *   │ │   扫地机器人推荐             [↘2]   │ │
 *   │ │   千元降噪耳机               [↘5]   │ │
 *   │ └─────────────────────────────────────┘ │
 *   └─────────────────────────────────────────┘
 *
 * 数据：GET /api/monitor/history/baidu-keyword?range=7d
 * Sparkline 暂用 fallback mock 序列（详见 Design.md §5.6），等后端 series
 * endpoint 落地后单独 PR 接入。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
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

// 排序：异动 > 平稳，把 dropped/down 放最前，让用户先看到掉名词。
const CHANGE_ORDER: Record<ChangeKind, number> = {
  dropped: 0,
  down: 1,
  new: 2,
  up: 3,
  flat: 4,
};

const sortedKeywords = computed<Keyword[]>(() => {
  if (!data.value) return [];
  return [...data.value.keywords]
    .sort((a, b) => CHANGE_ORDER[a.change_kind] - CHANGE_ORDER[b.change_kind])
    .slice(0, 3);
});

const topKeyword = computed(() => sortedKeywords.value[0] ?? null);
const restKeywords = computed(() => sortedKeywords.value.slice(1));

// fallback sparkline — 7 个点平稳上升，等后端给 series 再换真实数据。
const SPARK_FALLBACK = [3, 4, 4, 5, 5, 6, 7];
const SPARK_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "今天"];

function chipStyle(kind: ChangeKind) {
  if (kind === "up" || kind === "new")
    return { background: "#dde7d2", color: "#4d6b2f" };
  if (kind === "down" || kind === "dropped")
    return { background: "#f3d3cd", color: "#a3382a" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}

function chipIcon(kind: ChangeKind) {
  if (kind === "up" || kind === "new") return "arrowUp";
  if (kind === "down" || kind === "dropped") return "arrowDown";
  return "x"; // 持平：用 x 占位避免空字符串
}

function chipText(kw: Keyword) {
  if (kw.change_kind === "flat") return "持平";
  return String(kw.matched_count);
}

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/baidu-keyword", {
      params: { range: "7d" },
    });
    data.value = r.data;
  } catch {
    /* 静默：空状态顶住 */
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
    <div class="mb-2 flex flex-shrink-0 items-start justify-between">
      <div class="min-w-0">
        <div
          class="text-[10.5px] font-medium uppercase tracking-[1.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          Monitor · 百度 SEO
        </div>
        <div
          v-if="topKeyword"
          class="font-display mt-1 truncate font-semibold"
          :style="{ fontSize: '13px', color: 'var(--ink)' }"
        >
          {{ topKeyword.search_keyword }}
        </div>
        <div
          v-else
          class="font-display mt-1 font-semibold"
          :style="{ fontSize: '13px', color: 'var(--ink-3)' }"
        >
          百度关键词
        </div>
        <div class="mt-0.5 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          近 7 天
        </div>
      </div>
      <button
        type="button"
        class="inline-flex h-7 flex-shrink-0 items-center gap-1 rounded-full px-2.5 text-[11.5px]"
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

    <!-- Sparkline + 日期标签 -->
    <div class="mb-2 flex-shrink-0">
      <Sparkline
        :points="SPARK_FALLBACK"
        :axis-labels="SPARK_LABELS"
        :height="38"
        stroke="var(--primary)"
        :show-last="true"
        fluid
      />
    </div>

    <!-- 关键词列表 -->
    <div
      v-if="!loaded"
      class="flex min-h-0 flex-1 items-center justify-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      加载中…
    </div>
    <div
      v-else-if="sortedKeywords.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无百度关键词任务<br />
      <span class="text-[11px]">前往监测中心添加</span>
    </div>
    <div v-else class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <!-- 高亮主项：用 primary-soft 兜底，对应设计稿浅紫高亮带 -->
      <div
        v-if="topKeyword"
        class="flex items-center gap-2 rounded-[10px] px-2.5 py-2"
        :style="{
          background: 'var(--primary-soft)',
          border: '1px solid rgba(238,106,42,0.18)',
        }"
      >
        <div
          class="min-w-0 flex-1 truncate text-[12px] font-semibold"
          :style="{ color: 'var(--primary-deep)' }"
        >
          {{ topKeyword.search_keyword }}
        </div>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="chipStyle(topKeyword.change_kind)"
        >
          <Icon :name="chipIcon(topKeyword.change_kind)" :size="9" />
          {{ chipText(topKeyword) }}
        </span>
      </div>
      <!-- 次项：标准 card-2 底 -->
      <div
        v-for="kw in restKeywords"
        :key="kw.task_id"
        class="flex items-center gap-2 rounded-[10px] px-2.5 py-2"
        :style="{
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
        }"
      >
        <div class="min-w-0 flex-1 truncate text-[12px]">
          {{ kw.search_keyword }}
        </div>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="chipStyle(kw.change_kind)"
        >
          <Icon :name="chipIcon(kw.change_kind)" :size="9" />
          {{ chipText(kw) }}
        </span>
      </div>
    </div>
  </section>
</template>
