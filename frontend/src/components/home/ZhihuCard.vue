<script setup lang="ts">
/**
 * 知乎问题 — Row 2 第 2 张监测卡。
 *
 * 替换原 RankAlertsCard。视觉风格对齐 BaiduSeoCard：
 *   - 标题区（小标 / 大标 / 副标 / 详情按钮）
 *   - sparkline + 日期标签
 *   - 列表：高亮主项 + 2 个次项，主项是排名最差或预警最严重的任务
 *
 * 数据：GET /api/monitor/summary, platforms.zhihu_question.tasks。
 * 预警阈值参考 [ZHIHU_MIN_MATCHED] 和 cfg.monitor.alert_top_n。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

const sidecar = useSidecar();
const cfg = useConfig();
const router = useRouter();
const { whenReady } = useSidecarReady();

interface MonitorTaskRow {
  id: number;
  name: string;
  enabled: boolean;
  latest: {
    status: string;
    rank: number;
    checked_at: string | null;
    metric?: Record<string, any>;
  } | null;
}

const tasks = ref<MonitorTaskRow[]>([]);
const loaded = ref(false);

const topN = computed(() => cfg.data?.monitor?.alert_top_n ?? 5);
const ZHIHU_MIN_MATCHED = 3;

type Severity = "alert" | "warn" | "ok" | "info";
const SEVERITY_ORDER: Record<Severity, number> = {
  alert: 0,
  warn: 1,
  info: 2,
  ok: 3,
};

function severity(t: MonitorTaskRow): Severity {
  if (!t.latest) return "info";
  if (t.latest.status === "failed" || t.latest.status === "risk_control")
    return "alert";
  if (t.latest.status !== "ok") return "info";
  const rank = t.latest.rank;
  const matched = Number(t.latest.metric?.matched_count ?? 0);
  if (rank < 1 || rank > topN.value) return "warn";
  if (matched < ZHIHU_MIN_MATCHED) return "warn";
  return "ok";
}

interface Row {
  id: number;
  name: string;
  severity: Severity;
  chipText: string;
  chipIcon: string;
}

function buildRow(t: MonitorTaskRow): Row {
  const sev = severity(t);
  const rank = t.latest?.rank ?? -1;
  const matched = Number(t.latest?.metric?.matched_count ?? 0);
  let chipText: string;
  let chipIcon: string;
  if (sev === "alert") {
    chipText = "风控";
    chipIcon = "alert";
  } else if (sev === "warn" && (rank < 1 || rank > topN.value)) {
    chipText = `#${rank > 0 ? rank : "-"}`;
    chipIcon = "arrowDown";
  } else if (sev === "warn") {
    chipText = `${matched} 命中`;
    chipIcon = "arrowDown";
  } else if (sev === "ok") {
    chipText = `#${rank}`;
    chipIcon = "arrowUp";
  } else {
    chipText = "—";
    chipIcon = "x";
  }
  return { id: t.id, name: t.name, severity: sev, chipText, chipIcon };
}

const sortedRows = computed<Row[]>(() =>
  tasks.value
    .map(buildRow)
    .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
    .slice(0, 3),
);

const topRow = computed(() => sortedRows.value[0] ?? null);
const restRows = computed(() => sortedRows.value.slice(1));

const subLabel = computed(() => {
  if (!loaded.value) return "加载中…";
  if (tasks.value.length === 0) return "暂无知乎任务";
  const alerts = sortedRows.value.filter(
    (r) => r.severity === "alert" || r.severity === "warn",
  ).length;
  if (alerts > 0) return `${alerts} 个预警`;
  return "全部上榜";
});

const SPARK_FALLBACK = [2, 3, 3, 4, 5, 5, 6];
const SPARK_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "今天"];

function chipStyle(sev: Severity) {
  if (sev === "alert") return { background: "#f3d3cd", color: "#a3382a" };
  if (sev === "warn")
    return { background: "var(--yellow-soft)", color: "#7a5400" };
  if (sev === "ok") return { background: "#dde7d2", color: "#4d6b2f" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}

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
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
        知乎问题
      </div>
      <button
        type="button"
        class="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full"
        :style="{
          background: 'var(--card-2)',
          color: 'var(--ink-2)',
          border: '1px solid var(--line)',
        }"
        title="详情"
        @click="router.push({ name: 'monitor', query: { tab: 'zhihu' } })"
      >
        <Icon name="arrowRight" :size="11" />
      </button>
    </div>

    <!-- 大标：当前主问题 + 状态 chip -->
    <div class="mt-2 flex flex-shrink-0 items-center gap-2">
      <div
        class="font-display min-w-0 flex-1 truncate font-bold"
        :style="{ fontSize: '15px', color: 'var(--ink)' }"
      >
        {{ topRow ? topRow.name : "知乎排名" }}
      </div>
      <span
        v-if="topRow"
        class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
        :style="chipStyle(topRow.severity)"
      >
        <Icon :name="topRow.chipIcon" :size="9" />
        {{ topRow.chipText }}
      </span>
    </div>
    <div class="mt-0.5 mb-2 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
      近 7 天 · {{ subLabel }}
    </div>

    <!-- Sparkline -->
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

    <!-- 任务列表 -->
    <div
      v-if="!loaded"
      class="flex min-h-0 flex-1 items-center justify-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      加载中…
    </div>
    <div
      v-else-if="sortedRows.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无知乎任务<br />
      <span class="text-[11px]">前往监测中心添加</span>
    </div>
    <div v-else class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <!-- 高亮主项：深橙底 + 暖色字 -->
      <div
        v-if="topRow"
        class="flex items-center gap-2 rounded-[10px] px-2.5 py-2"
        :style="{
          background: 'var(--primary)',
          border: '1px solid var(--primary)',
        }"
      >
        <div
          class="min-w-0 flex-1 truncate text-[12px] font-semibold"
          :style="{ color: 'var(--yellow)' }"
        >
          {{ topRow.name }}
        </div>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="{
            background: 'var(--primary-deep)',
            color: 'var(--yellow)',
          }"
        >
          <Icon :name="topRow.chipIcon" :size="9" />
          {{ topRow.chipText }}
        </span>
      </div>
      <!-- 次项：白底简洁行 -->
      <div
        v-for="r in restRows"
        :key="r.id"
        class="flex items-center gap-2 rounded-[10px] px-2.5 py-2"
        :style="{ background: 'transparent' }"
      >
        <div class="min-w-0 flex-1 truncate text-[12px]">{{ r.name }}</div>
        <span
          class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
          :style="chipStyle(r.severity)"
        >
          <Icon :name="r.chipIcon" :size="9" />
          {{ r.chipText }}
        </span>
      </div>
    </div>
  </section>
</template>
