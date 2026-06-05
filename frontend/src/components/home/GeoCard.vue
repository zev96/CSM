<script setup lang="ts">
/**
 * GEO · AI 卡位 card（曝光率 soc）— 首页监测卡。
 *
 * 视图抽到 KeywordTrendCard。本组件负责数据获取 + 严重度映射 →
 * KeywordTrendItem[]，并把行点击转 router.push 跳到监测中心 geo tab
 * 对应任务。
 *
 * 数据：GET /api/monitor/summary, platforms.geo_query.tasks。
 * geo_query 没有 prev 快照 —— delta 通过 series 最后两个点的 soc 差值计算。
 * 当前值取 kpi_snapshot.soc（0–1），展示时乘 100 转百分比整数。
 * yMax 固定 100（soc 上限 = 100%）。
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
  soc: number;
}
interface MonitorTaskRow {
  id: number;
  name: string;
  enabled: boolean;
  latest: MonitorSnapshot | null;
  kpi_snapshot?: { soc: number; sentiment: number; mentioned: number };
  series?: SeriesPoint[];
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

function socPct(t: MonitorTaskRow): number {
  return Math.round(Number(t.kpi_snapshot?.soc ?? 0) * 100);
}

function socDelta(t: MonitorTaskRow): number | null {
  const s = t.series ?? [];
  if (s.length < 2) return null;
  return Math.round((s[s.length - 1].soc - s[s.length - 2].soc) * 100);
}

function severity(t: MonitorTaskRow): Severity {
  if (!t.latest) return "info";
  if (t.latest.status === "failed" || t.latest.status === "risk_control")
    return "alert";
  const delta = socDelta(t);
  if (delta === null) return "info";
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
  if (!t.latest) return { text: "—", icon: "", kind: mapKind(sev) }; // 真·无数据 → "—"，不显示 0%
  // 有 latest（即有当前曝光值）：始终展示当前 soc%，有趋势时带箭头
  const pct = `${socPct(t)}%`;
  if (sev === "up") return { text: pct, icon: "arrowUp", kind: mapKind(sev) };
  if (sev === "down") return { text: pct, icon: "arrowDown", kind: mapKind(sev) };
  return { text: pct, icon: "", kind: mapKind(sev) }; // flat / 有值无趋势 → soc% 无箭头
}

function rowSeries(t: MonitorTaskRow): number[] | undefined {
  if (!t.series || t.series.length === 0) return undefined;
  return t.series.map((p) => Math.round(p.soc * 100));
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
      yMax: 100,
    })),
);

const subLabel = computed(() => "近 7 天");

const SPARK_FALLBACK = [20, 25, 22, 28, 30, 27, 32];
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
    tasks.value = r.data.platforms?.geo_query?.tasks ?? [];
  } catch {
    /* 静默：空状态顶住 */
  } finally {
    loaded.value = true;
  }
});

function goDetail() {
  router.push({ name: "monitor", query: { tab: "geo" } });
}

function onItemClick(item: KeywordTrendItem) {
  router.push({
    name: "monitor",
    query: { tab: "geo", task: item.id },
  });
}
</script>

<template>
  <KeywordTrendCard
    category="GEO · AI 卡位"
    :sub-label="subLabel"
    :axis-labels="SPARK_LABELS"
    :items="items"
    :fallback-series="SPARK_FALLBACK"
    :loaded="loaded"
    empty-title="暂无 GEO 任务"
    empty-hint="前往监测中心添加"
    @detail="goDetail"
    @item-click="onItemClick"
  />
</template>
