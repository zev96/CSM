<script setup lang="ts">
/**
 * GEO 数据中心分析页（重构对齐图二/三）——
 *   概览条（关键词 + 覆盖分布 + 曝光率/情感环比）
 *   关键词 × AI平台 · 覆盖卡：[重点 | 覆盖榜] 切换
 *     重点  = 待优化关键词 + 各平台覆盖率近 5 周
 *     覆盖榜 = 关键词 × 平台覆盖表（点格展开该平台 AI 原文 + 信源）
 *   下半：高权重信源榜 + 曝光趋势（三段堆叠面积）
 * 自包含：自己加载 geo_query 任务列表 + useGeoAnalytics。
 */
import { ref, computed, onMounted, watch } from "vue";

import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useGeoAnalytics, type PlatformVM } from "@/components/monitor/geo/geoDetail";
import GeoOverviewBar from "@/components/monitor/geo/GeoOverviewBar.vue";
import GeoCoverageBoard from "@/components/monitor/geo/GeoCoverageBoard.vue";
import GeoFocusPanel from "@/components/monitor/geo/GeoFocusPanel.vue";
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

// ── 视图切换 + 选中格（覆盖榜下钻）─────────────────────────────────────
const view = ref<"focus" | "board">("focus");
const selectedCell = ref<PlatformVM | null>(null);
const selectedCellKey = ref<{ keyword: string; platformId: string } | null>(null);

function onCell(p: { keyword: string; platformId: string }): void {
  const cell = analytics.value?.matrix[p.keyword]?.[p.platformId] ?? null;
  selectedCell.value = cell;
  selectedCellKey.value = cell ? { keyword: p.keyword, platformId: p.platformId } : null;
}
function clearCell(): void {
  selectedCell.value = null;
  selectedCellKey.value = null;
}

watch(selectedTaskId, clearCell);
watch(view, (v) => {
  if (v === "focus") clearCell(); // 原文下钻只属于覆盖榜
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
  <div class="flex h-full min-h-0 flex-col" :style="{ gap: '14px' }">

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

      <!-- 概览条 -->
      <GeoOverviewBar
        :kw-count="kwCount"
        :coverage="analytics.coverage"
        :soc-pct="socPct"
        :soc-delta="analytics.socDelta"
        :sentiment="sentiment"
        :sentiment-delta="analytics.sentimentDelta"
      />

      <!-- 关键词 × AI平台 · 覆盖 -->
      <div
        class="flex min-h-0 flex-col"
        :style="{
          flex: '1.1 1 0',
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-inner, 10px)',
          padding: '14px 16px',
        }"
      >
        <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
          <div :style="{ fontSize: '12px', fontWeight: 700, color: 'var(--ink)' }">关键词 × AI平台 · 覆盖</div>
          <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card)', border: '1px solid var(--line)' }">
            <button
              v-for="t in [{ k: 'focus', l: '重点' }, { k: 'board', l: '覆盖榜' }]"
              :key="t.k"
              type="button"
              class="px-3.5 py-1 rounded-full text-[12px] font-medium"
              :style="{
                background: view === t.k ? 'var(--dark)' : 'transparent',
                color: view === t.k ? 'var(--card)' : 'var(--ink-3)',
                border: 'none', cursor: 'pointer',
              }"
              @click="view = (t.k as 'focus' | 'board')"
            >{{ t.l }}</button>
          </div>
        </div>

        <GeoFocusPanel
          v-if="view === 'focus'"
          :to-improve="analytics.toImprove"
          :platform-weekly="analytics.platformWeekly"
        />
        <GeoCoverageBoard
          v-else
          :rows="analytics.keywordRows"
          :platform-ids="analytics.platformIds"
          :selected="selectedCellKey"
          @cell="onCell"
        />
      </div>

      <!-- 覆盖榜下钻：该平台 AI 原文 + 引用信源 -->
      <div
        v-if="view === 'board' && selectedCell"
        class="flex-shrink-0"
        :style="{ maxHeight: '300px', overflowY: 'auto' }"
      >
        <div class="mb-1 flex items-center justify-between">
          <div :style="{ fontSize: '11px', color: 'var(--ink-3)' }">
            {{ selectedCellKey?.keyword }} · 平台原文
          </div>
          <button
            type="button"
            :style="{ fontSize: '11px', color: 'var(--ink-3)', background: 'transparent', border: 'none', cursor: 'pointer' }"
            @click="clearCell"
          >收起 ✕</button>
        </div>
        <GeoPlatformBlock :platform="selectedCell" :brand="brand" :brand-terms="brandTerms" />
      </div>

      <!-- 下半：信源榜 + 曝光趋势（并排） -->
      <div class="flex min-h-0" :style="{ gap: '16px', flex: '1 1 0' }">
        <!-- 高权重信源榜 -->
        <div
          class="flex min-h-0 flex-col"
          :style="{
            flex: '1 1 52%',
            background: 'var(--card-2)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner, 10px)',
            padding: '14px 16px',
          }"
        >
          <div class="mb-2 flex flex-shrink-0 items-baseline gap-2">
            <div :style="{ fontSize: '12px', fontWeight: 700, color: 'var(--ink)' }">高权重信源榜</div>
            <div :style="{ fontSize: '11px', color: 'var(--ink-3)' }">{{ sourceCount }} 条</div>
          </div>
          <GeoSourceList
            :board="analytics.board"
            :total="analytics.platformIds.length"
          />
        </div>

        <!-- 曝光趋势 -->
        <div
          class="flex min-h-0 flex-col"
          :style="{
            flex: '1 1 48%',
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
