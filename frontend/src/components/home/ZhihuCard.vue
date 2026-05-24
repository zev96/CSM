<script setup lang="ts">
/**
 * 知乎问题 — Row 2 第 2 张监测卡。
 *
 * 视图抽到 KeywordTrendCard。本组件负责数据获取 + 严重度映射 →
 * KeywordTrendItem[]，并把行点击转 router.push 跳到监测中心知乎 tab
 * 对应任务。
 *
 * 全量映射不再 slice(0, 3) —— 大窗口下列表区自然多露任务。
 *
 * 数据：GET /api/monitor/summary, platforms.zhihu_question.tasks。
 * 每条 task 现在包含 ``latest`` / ``prev`` / ``series`` / ``top_n``，
 * 让卡片可以本地算"卡位数量变化"徽章 + 真实趋势 sparkline，无需对
 * 每条任务再单发 /api/monitor/results。
 *
 * 徽章语义按用户要求重做：
 *   - 显示"卡位数量变化"（matched_count delta），不再混杂排名 #N。
 *   - "↑+2" / "↓-1" 文本只是符号 + 数字，去掉了旧的"命中"后缀。
 *   - 首次抓取（无 prev）→ "—"；alert/risk_control 仍优先显示风控。
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
  matched_count: number;
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

// 排序优先级：风控/失败 > 数量下滑 > 持平 > 上升 > 无数据。徽章 kind
// 用同一个键。
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
  return Number(snap.metric?.matched_count ?? 0);
}

function severity(t: MonitorTaskRow): Severity {
  if (!t.latest) return "info";
  if (t.latest.status === "failed" || t.latest.status === "risk_control")
    return "alert";
  if (!t.prev) return "info"; // 还没历史 → 没法算 delta
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
  // 纯箭头 + 绝对值数字，按用户要求不带 +/- 符号 —— 方向由 icon 表达，
  // 重复一份 ASCII 符号是冗余（↑ 已经"就是加"，↓ 已经"就是减"）。
  const absDelta = Math.abs(matchedCount(t.latest) - matchedCount(t.prev));
  if (sev === "up")
    return { text: String(absDelta), icon: "arrowUp", kind: mapKind(sev) };
  if (sev === "down")
    return { text: String(absDelta), icon: "arrowDown", kind: mapKind(sev) };
  // flat（变化 = 0）：纯 "—"，不带 icon
  return { text: "—", icon: "", kind: mapKind(sev) };
}

// 真实 sparkline 数据：series oldest→newest 的 matched_count。无 series
// 时让 KeywordTrendCard fallback 到 SPARK_FALLBACK（开发兜底）。
function rowSeries(t: MonitorTaskRow): number[] | undefined {
  if (!t.series || t.series.length === 0) return undefined;
  return t.series.map((p) => p.matched_count);
}

// 首页这张卡列表最多 15 条；完整列表走右上「→」按钮跳到监测中心知乎 tab。
const items = computed<KeywordTrendItem[]>(() =>
  [...tasks.value]
    .sort((a, b) => SEVERITY_ORDER[severity(a)] - SEVERITY_ORDER[severity(b)])
    .slice(0, 15)
    .map((t) => ({
      id: t.id,
      label: t.name,
      badge: rowBadge(t),
      series: rowSeries(t),
      // Y 轴上限 = 该关键词 Top-N（命中条数的容量上限），让 sparkline
      // 显示"占比"而不是被微小波动放大的相对趋势。
      yMax: typeof t.top_n === "number" && t.top_n > 0 ? t.top_n : undefined,
    })),
);

const subLabel = computed(() => "近 7 天");

const SPARK_FALLBACK = [2, 3, 3, 4, 5, 5, 6];
// 横轴标签：7 天日（"22"），不带月份；今天在最末。跟 series 长度一致
// 让 X 轴和数据点对齐。原本 14 天，用户反馈太长，缩到 7 天。
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
    tasks.value = r.data.platforms?.zhihu_question?.tasks ?? [];
  } catch {
    /* 静默：空状态顶住 */
  } finally {
    loaded.value = true;
  }
});

function goDetail() {
  router.push({ name: "monitor", query: { tab: "zhihu" } });
}

// 点击任务行 → 跳到监测中心知乎 tab + 该任务。MonitorView 的
// ZhihuMonitorModule 暴露 selectTask(taskId)，task query 当前透传，
// 父组件后续可接住自动 highlight。
function onItemClick(item: KeywordTrendItem) {
  router.push({
    name: "monitor",
    query: { tab: "zhihu", task: item.id },
  });
}
</script>

<template>
  <KeywordTrendCard
    category="知乎问题"
    :sub-label="subLabel"
    :axis-labels="SPARK_LABELS"
    :items="items"
    :fallback-series="SPARK_FALLBACK"
    :loaded="loaded"
    empty-title="暂无知乎任务"
    empty-hint="前往监测中心添加"
    @detail="goDetail"
    @item-click="onItemClick"
  />
</template>
