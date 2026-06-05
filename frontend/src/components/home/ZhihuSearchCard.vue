<script setup lang="ts">
/**
 * 知乎搜索 — 首页监测卡。
 *
 * 视图抽到 KeywordTrendCard。本组件负责数据获取 + 严重度映射 →
 * KeywordTrendItem[]，并把行点击转 router.push 跳到监测中心知乎搜索 tab
 * 对应任务。
 *
 * 数据：GET /api/monitor/summary, platforms.zhihu_search.tasks。
 * 每条 task 包含 latest / prev / series，series 中每个点的 matched 字段
 * 即 metric.total_matches，用于 sparkline + delta 徽章。
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

interface MonitorSnapshot {
  status: string;
  rank: number;
  checked_at: string | null;
  metric?: Record<string, any>;
}
interface SeriesPoint {
  checked_at: string | null;
  matched: number;
}
interface MonitorTaskRow {
  id: number;
  name: string;
  enabled: boolean;
  latest: MonitorSnapshot | null;
  prev?: MonitorSnapshot | null;
  series?: SeriesPoint[];
  top_n?: number;
}

const tasks = ref<MonitorTaskRow[]>([]);
const loaded = ref(false);

type Severity = "alert" | "down" | "flat" | "up" | "info";
const SEVERITY_ORDER: Record<Severity, number> = {
  alert: 0,
  down: 1,
  flat: 2,
  up: 3,
  info: 4,
};

function matchedCount(snap: MonitorSnapshot | null | undefined): number {
  if (!snap) return 0;
  return Number(snap.metric?.total_matches ?? 0);
}

function severity(t: MonitorTaskRow): Severity {
  if (!t.latest) return "info";
  if (t.latest.status === "failed" || t.latest.status === "risk_control")
    return "alert";
  if (!t.prev) return "info";
  const delta = matchedCount(t.latest) - matchedCount(t.prev);
  if (delta > 0) return "up";
  if (delta < 0) return "down";
  return "flat";
}

function mapKind(sev: Severity): BadgeKind {
  if (sev === "alert") return "alert";
  if (sev === "down") return "down";
  if (sev === "up") return "up";
  return "flat";
}

function rowBadge(t: MonitorTaskRow) {
  const sev = severity(t);
  if (sev === "alert") return { text: "风控", icon: "alert", kind: mapKind(sev) };
  if (sev === "info") return { text: "—", icon: "", kind: mapKind(sev) };
  const absDelta = Math.abs(matchedCount(t.latest) - matchedCount(t.prev));
  if (sev === "up")
    return { text: String(absDelta), icon: "arrowUp", kind: mapKind(sev) };
  if (sev === "down")
    return { text: String(absDelta), icon: "arrowDown", kind: mapKind(sev) };
  return { text: "—", icon: "", kind: mapKind(sev) };
}

function rowSeries(t: MonitorTaskRow): number[] | undefined {
  if (!t.series || t.series.length === 0) return undefined;
  return t.series.map((p) => p.matched);
}

const items = computed<KeywordTrendItem[]>(() =>
  [...tasks.value]
    .sort((a, b) => SEVERITY_ORDER[severity(a)] - SEVERITY_ORDER[severity(b)])
    .slice(0, 15)
    .map((t) => ({
      id: t.id,
      label: t.name,
      badge: rowBadge(t),
      series: rowSeries(t),
      yMax: typeof t.top_n === "number" && t.top_n > 0 ? t.top_n : undefined,
    })),
);

const subLabel = computed(() => "近 7 天");

const SPARK_FALLBACK = [2, 3, 3, 4, 5, 5, 6];
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
    const r = await sidecar.client.get("/api/monitor/summary");
    tasks.value = r.data.platforms?.zhihu_search?.tasks ?? [];
  } catch {
    /* 静默：空状态顶住 */
  } finally {
    loaded.value = true;
  }
});

function goDetail() {
  router.push({ name: "monitor", query: { tab: "zhihu_search" } });
}

function onItemClick(item: KeywordTrendItem) {
  router.push({
    name: "monitor",
    query: { tab: "zhihu_search", task: item.id },
  });
}
</script>

<template>
  <KeywordTrendCard
    category="知乎搜索"
    :sub-label="subLabel"
    :axis-labels="SPARK_LABELS"
    :items="items"
    :fallback-series="SPARK_FALLBACK"
    :loaded="loaded"
    empty-title="暂无知乎搜索任务"
    empty-hint="前往监测中心添加"
    @detail="goDetail"
    @item-click="onItemClick"
  />
</template>
