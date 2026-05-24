<script setup lang="ts">
/**
 * 百度 SEO 首页卡 — Row 2 第 1 张。
 *
 * 视图抽到 KeywordTrendCard。本组件负责数据获取 + Keyword[] → KeywordTrendItem[]
 * 映射 + 行点击转 router.push 跳到监测中心百度 tab 对应任务。
 *
 * 全量映射不再 slice(0, 3) —— 窗口拉大时 KeywordTrendCard 的列表区
 * (flex-1 + overflow-y-auto) 跟着涨高，更多关键词自动露出来直到塞满；
 * 小窗口则滚动。
 *
 * 数据：GET /api/monitor/history/baidu-keyword?range=7d
 * Sparkline 暂用全局 fallback；后端 per-keyword series 接入后给 mapped
 * item 加 series 字段即可，UI 自动用上。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import KeywordTrendCard, {
  type BadgeKind,
  type KeywordTrendItem,
} from "@/components/home/KeywordTrendCard.vue";
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

function mapKind(k: ChangeKind): BadgeKind {
  if (k === "up" || k === "new") return "up";
  if (k === "down" || k === "dropped") return "down";
  return "flat";
}

function badgeIcon(k: ChangeKind): string {
  if (k === "up" || k === "new") return "arrowUp";
  if (k === "down" || k === "dropped") return "arrowDown";
  return ""; // flat：徽章只显示文字 "—"
}

function badgeText(kw: Keyword): string {
  if (kw.change_kind === "flat") return "—";
  return String(kw.matched_count);
}

// 首页这张卡列表最多 15 条（避免数据多时把 DOM 塞过满 / 列表撑太长）；
// 完整列表走右上「→」按钮跳到监测中心百度 tab 看。
const items = computed<KeywordTrendItem[]>(() => {
  if (!data.value) return [];
  return [...data.value.keywords]
    .sort((a, b) => CHANGE_ORDER[a.change_kind] - CHANGE_ORDER[b.change_kind])
    .slice(0, 15)
    .map((kw) => ({
      id: kw.task_id,
      label: kw.search_keyword,
      badge: {
        text: badgeText(kw),
        icon: badgeIcon(kw.change_kind),
        kind: mapKind(kw.change_kind),
      },
    }));
});

const SPARK_FALLBACK = [3, 4, 4, 5, 5, 6, 7];
// 横轴标签：7 天日（"22"），不带月份；今天在最末。在 component setup
// 时算一次，跟 hero dateLabel 同语义（hero remount 时跟着重算）。
const SPARK_LABELS = ((): string[] => {
  const out: string[] = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
    out.push(String(d.getDate()));
  }
  return out;
})();

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

function goDetail() {
  router.push({ name: "monitor", query: { tab: "baidu" } });
}

// 点击关键词行 → 跳到监测中心百度 tab + 该任务。MonitorView 现在
// 只读 tab query；task query 暂时透传不处理，留待 BaiduRankingPage
// 后续接 task 路由 highlight。
function onItemClick(item: KeywordTrendItem) {
  router.push({
    name: "monitor",
    query: { tab: "baidu", task: item.id },
  });
}
</script>

<template>
  <KeywordTrendCard
    category="百度 SEO"
    sub-label="近 7 天"
    :axis-labels="SPARK_LABELS"
    :items="items"
    :fallback-series="SPARK_FALLBACK"
    :loaded="loaded"
    empty-title="暂无百度关键词任务"
    empty-hint="前往监测中心添加"
    @detail="goDetail"
    @item-click="onItemClick"
  />
</template>
