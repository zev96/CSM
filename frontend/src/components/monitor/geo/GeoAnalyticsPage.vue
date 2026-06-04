<script setup lang="ts">
/**
 * GEO 数据中心分析页 —— 跨关键词聚合矩阵 + 高权重信源榜 + 曝光趋势。
 * 自包含：自己加载 geo_query 任务列表 + useGeoAnalytics。
 */
import { ref, computed, onMounted, watch } from "vue";

import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useGeoAnalytics, type PlatformVM } from "@/components/monitor/geo/geoDetail";
import GeoKeywordMatrix from "@/components/monitor/geo/GeoKeywordMatrix.vue";
import GeoSourceList from "@/components/monitor/geo/GeoSourceList.vue";
import GeoPlatformBlock from "@/components/monitor/geo/GeoPlatformBlock.vue";
import GeoTrend from "@/components/monitor/geo/charts/GeoTrend.vue";
import type { Task } from "@/utils/monitor-types";

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();

// ── 任务列表 ───────────────────────────────────────────────────────────
const tasks = ref<Task[]>([]);
const tasksLoading = ref(false);
const tasksFailed = ref(false);

async function loadTasks(): Promise<void> {
  tasksLoading.value = true;
  tasksFailed.value = false;
  try {
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: "geo_query" },
    });
    tasks.value = r.data?.tasks ?? [];
  } catch {
    tasksFailed.value = true;
    tasks.value = [];
  } finally {
    tasksLoading.value = false;
  }
}

// ── 选中任务 ──────────────────────────────────────────────────────────
const selectedTaskId = ref<number | null>(null);
const selectedTask = computed<Task | null>(
  () => tasks.value.find((t) => t.id === selectedTaskId.value) ?? null,
);

// ── 派生（镜像 GeoTaskModule）────────────────────────────────────────
const brand = computed<string>(
  () => String(selectedTask.value?.config?.brand ?? selectedTask.value?.name ?? ""),
);
const brandTerms = computed<string[]>(() => {
  const b = brand.value;
  const aliases: string[] = Array.isArray(selectedTask.value?.config?.brand_aliases)
    ? (selectedTask.value!.config!.brand_aliases as unknown[]).filter(Boolean).map(String)
    : [];
  return [b, ...aliases].filter(Boolean);
});
const configuredKeywords = computed<string[]>(() => {
  const kws = selectedTask.value?.config?.keywords;
  return Array.isArray(kws) ? kws.filter(Boolean).map(String) : [];
});
const configuredPlatforms = computed<string[]>(() => {
  const ps = selectedTask.value?.config?.platforms;
  return Array.isArray(ps) ? ps.filter(Boolean).map(String) : [];
});

// ── GEO 分析数据 ───────────────────────────────────────────────────────
const { analytics, loading } = useGeoAnalytics(
  selectedTaskId,
  brandTerms,
  configuredKeywords,
  configuredPlatforms,
);

// ── 选中格 ─────────────────────────────────────────────────────────────
const selectedCell = ref<PlatformVM | null>(null);

function onCell(p: { keyword: string; platformId: string }): void {
  selectedCell.value = analytics.value?.matrix[p.keyword]?.[p.platformId] ?? null;
}

watch(selectedTaskId, () => {
  selectedCell.value = null;
});

// ── KPI computeds ─────────────────────────────────────────────────────
const kwCount = computed(() => analytics.value?.keywords.length ?? 0);
const socPct = computed(() => Math.round((analytics.value?.metric?.soc ?? 0) * 100));
const sentiment = computed(() => analytics.value?.metric?.sentiment_score ?? 0);
const sourceCount = computed(() => analytics.value?.board.length ?? 0);

// ── 任务显示名 ─────────────────────────────────────────────────────────
function taskLabel(t: Task): string {
  const b = String(t.config?.brand ?? t.name ?? "");
  return b || t.name;
}

// ── 生命周期 ───────────────────────────────────────────────────────────
onMounted(async () => {
  try {
    await whenReady();
    await loadTasks();
    if (tasks.value.length > 0) {
      selectedTaskId.value = tasks.value[0].id;
    }
  } catch {
    tasksFailed.value = true;
  }
});
</script>

<template>
  <div class="flex h-full min-h-0 flex-col" :style="{ gap: '16px' }">

    <!-- ── 顶部：任务选择器 ─────────────────────────────────────────────── -->
    <div class="flex flex-shrink-0 items-center" :style="{ gap: '10px' }">
      <span :style="{ fontSize: '11px', color: 'var(--ink-3)', flexShrink: 0 }">监测任务</span>
      <select
        v-if="tasks.length > 0"
        v-model.number="selectedTaskId"
        :style="{
          fontSize: '12.5px',
          fontWeight: 600,
          color: 'var(--ink)',
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '6px 10px',
          cursor: 'pointer',
          fontFamily: 'inherit',
          outline: 'none',
        }"
      >
        <option v-for="t in tasks" :key="t.id" :value="t.id">{{ taskLabel(t) }}</option>
      </select>
    </div>

    <!-- ── 空态：无 GEO 任务 ───────────────────────────────────────────── -->
    <div
      v-if="!tasksLoading && tasks.length === 0"
      class="flex flex-1 items-center justify-center"
      :style="{ fontSize: '13px', color: 'var(--ink-3)' }"
    >
      暂无 GEO 任务，去监测中心新建
    </div>

    <!-- ── 加载中 ───────────────────────────────────────────────────────── -->
    <div
      v-else-if="loading && !analytics"
      class="flex flex-1 items-center justify-center"
      :style="{ fontSize: '13px', color: 'var(--ink-3)' }"
    >
      加载中…
    </div>

    <!-- ── 主体内容 ─────────────────────────────────────────────────────── -->
    <template v-else-if="analytics">

      <!-- KPI 四格 -->
      <div
        class="flex-shrink-0"
        :style="{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }"
      >
        <div
          v-for="kpi in [
            { label: '监测关键词数', value: String(kwCount) },
            { label: '平均曝光率', value: socPct + '%' },
            { label: '平均情感', value: sentiment.toFixed(2) },
            { label: '高权重信源', value: String(sourceCount) },
          ]"
          :key="kpi.label"
          :style="{
            background: 'var(--card-2)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner, 10px)',
            padding: '12px 14px',
          }"
        >
          <div :style="{ fontSize: '9.5px', color: 'var(--ink-3)', marginBottom: '4px', letterSpacing: '0.5px' }">{{ kpi.label }}</div>
          <div class="font-display" :style="{ fontSize: '22px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ kpi.value }}</div>
        </div>
      </div>

      <!-- 关键词 × AI 平台矩阵 -->
      <div
        class="flex-shrink-0"
        :style="{
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-inner, 10px)',
          padding: '14px 16px',
        }"
      >
        <div :style="{ fontSize: '12px', fontWeight: 700, color: 'var(--ink)', marginBottom: '12px' }">关键词 × AI 平台</div>
        <GeoKeywordMatrix
          :keywords="analytics.keywords"
          :platform-ids="analytics.platformIds"
          :matrix="analytics.matrix"
          @cell="onCell"
        />
      </div>

      <!-- 点格后展示该格回答原文 + 引用信源 -->
      <div v-if="selectedCell" class="flex-shrink-0">
        <GeoPlatformBlock
          :platform="selectedCell"
          :brand="brand"
          :brand-terms="brandTerms"
        />
      </div>

      <!-- 下半：信源榜 + 曝光趋势（并排） -->
      <div
        class="flex min-h-0"
        :style="{ gap: '16px', flex: '1 1 auto' }"
      >
        <!-- 高权重信源榜 -->
        <div
          class="flex min-h-0 flex-col"
          :style="{
            flex: '1 1 50%',
            background: 'var(--card-2)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner, 10px)',
            padding: '14px 16px',
          }"
        >
          <div :style="{ fontSize: '12px', fontWeight: 700, color: 'var(--ink)', marginBottom: '10px', flexShrink: 0 }">高权重信源榜</div>
          <GeoSourceList
            :board="analytics.board"
            :total="analytics.platformIds.length"
            :task-id="selectedTaskId ?? 0"
            keyword=""
          />
        </div>

        <!-- 曝光趋势 -->
        <div
          v-if="analytics.history.length"
          :style="{
            flex: '1 1 50%',
            background: 'var(--card-2)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner, 10px)',
            padding: '14px 16px',
          }"
        >
          <GeoTrend :history="analytics.history" />
        </div>
      </div>

    </template>

  </div>
</template>
