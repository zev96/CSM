<script setup lang="ts">
/**
 * 百度关键词工作台 —— 与知乎问题工作台同款双卡布局。
 * 左：富任务表（搜索关键词 / 上次 / 变化 / 状态 / 操作）
 * 右：3 KPI + sparkline + 前 10 条结果 + 最新资讯
 */
import { ref, computed, onMounted, watch } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import Sparkline from "@/components/ui/Sparkline.vue";
import Pill from "@/components/ui/Pill.vue";
import Icon from "@/components/ui/Icon.vue";

// ──────────────────────────── types ────────────────────────────

interface BaiduResultRow {
  rank: number;
  title: string;
  url: string;
  host: string;
  matches_brand: boolean;
  matched_brand: string | null;
  source: "http" | "browser";
  content_preview: string;
  fetch_error: string | null;
}

interface BaiduMetric {
  search_keyword: string;
  target_brands: string[];
  serp_url: string;
  default_results: BaiduResultRow[];
  news_results: BaiduResultRow[];
  default_matched_count: number;
  default_first_rank: number;
  news_first_rank: number;
  news_present: boolean;
  engine: string;
  headless: boolean;
  captcha_hit: boolean;
}

interface TaskItem {
  id: number;
  name: string;
  type: string;
  config: { search_keyword: string; target_brands: string[] };
  last_check_at: string | null;
  last_status: string | null;
  schedule_cron?: string;
}

interface ResultItem {
  task_id: number;
  checked_at: string;
  status: string;
  rank: number;
  metric: BaiduMetric | null;
  error_message: string | null;
}

// ──────────────────────────── emits ────────────────────────────

const emit = defineEmits<{
  (e: "add-task"): void;
  (e: "batch-import"): void;
  (e: "edit-task", task: TaskItem): void;
}>();

// ──────────────────────────── store / composables ────────────────────────────

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();
const toast = useToast();

// ──────────────────────────── state ────────────────────────────

const tasks = ref<TaskItem[]>([]);
const selectedId = ref<number | null>(null);
const history = ref<ResultItem[]>([]);
const loadingTasks = ref(false);
const loadingHistory = ref(false);
const runningNow = ref(false);

// ──────────────────────────── derived ────────────────────────────

const selectedTask = computed(() =>
  tasks.value.find((t) => t.id === selectedId.value) ?? null,
);

const latestResult = computed(() =>
  history.value.length > 0 ? history.value[0] : null,
);

const latestMetric = computed<BaiduMetric | null>(
  () => latestResult.value?.metric ?? null,
);

const prevMetric = computed<BaiduMetric | null>(
  () => (history.value.length > 1 ? history.value[1]?.metric ?? null : null),
);

// Trend chart: history is newest-first from API; reverse for chronological
const chronoHistory = computed(() => [...history.value].reverse());

// Sparkline: default_first_rank, replace -1/missing with null (line break)
const sparkPoints = computed<number[]>(() =>
  chronoHistory.value
    .slice(-14)
    .map((r) => {
      const v = r.metric?.default_first_rank ?? -1;
      return v > 0 ? v : 0;
    })
    .filter((v) => v > 0),
);

const sparkLabels = computed<string[]>(() => {
  const slice = chronoHistory.value.slice(-14);
  if (slice.length <= 6) return slice.map((r) => r.checked_at.slice(5, 10));
  // Show ~4 evenly spaced labels
  const step = Math.floor(slice.length / 3);
  return [0, step, step * 2, slice.length - 1].map(
    (i) => slice[Math.min(i, slice.length - 1)].checked_at.slice(5, 10),
  );
});

// Delta for the selected task only
const rankDelta = computed<number | null>(() => {
  const cur = latestMetric.value?.default_first_rank ?? -1;
  const prv = prevMetric.value?.default_first_rank ?? -1;
  if (cur <= 0 && prv <= 0) return null;
  if (cur <= 0) return null; // fell out
  if (prv <= 0) return null; // first time
  return prv - cur; // positive = improved rank (lower number = better)
});

// ──────────────────────────── helpers ────────────────────────────

type PillTone = "ok" | "warn" | "alert" | "info";

interface TaskRowState {
  statusLabel: string;
  tone: PillTone;
  isFirst: boolean; // first-ever result (no prev)
}

function taskRowState(task: TaskItem): TaskRowState {
  const s = task.last_status;
  if (!task.last_check_at || !s) return { statusLabel: "未跑", tone: "info", isFirst: false };
  if (s === "captcha") return { statusLabel: "验证码", tone: "warn", isFirst: false };
  if (s === "error" || s === "fail") return { statusLabel: "失败", tone: "alert", isFirst: false };
  if (s === "ok") {
    // Use history if this is the selected task, otherwise fall back to last_status only
    if (task.id === selectedId.value) {
      const m = latestMetric.value;
      if (!m) return { statusLabel: "未跑", tone: "info", isFirst: false };
      if (m.captcha_hit) return { statusLabel: "验证码", tone: "warn", isFirst: false };
      if (m.default_matched_count > 0) return { statusLabel: "上榜", tone: "ok", isFirst: history.value.length <= 1 };
      return { statusLabel: "未命中", tone: "warn", isFirst: history.value.length <= 1 };
    }
    return { statusLabel: "正常", tone: "ok", isFirst: false };
  }
  return { statusLabel: s, tone: "info", isFirst: false };
}

function scheduleLabel(cron?: string): string {
  if (!cron || cron === "manual") return "手动";
  return cron;
}

// ──────────────────────────── data loading ────────────────────────────

async function loadTasks() {
  loadingTasks.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/tasks", {
      params: { type: "baidu_keyword" },
    });
    tasks.value = r.data.tasks ?? [];
    if (tasks.value.length > 0 && selectedId.value === null) {
      selectedId.value = tasks.value[0].id;
    }
  } catch (e: any) {
    toast.error(`加载任务列表失败: ${e?.message ?? e}`);
  } finally {
    loadingTasks.value = false;
  }
}

async function loadHistory(id: number) {
  loadingHistory.value = true;
  history.value = [];
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/results", {
      params: { task_id: id, limit: 30 },
    });
    history.value = r.data.results ?? [];
  } catch (e: any) {
    toast.error(`加载历史记录失败: ${e?.message ?? e}`);
  } finally {
    loadingHistory.value = false;
  }
}

async function runNow() {
  if (!selectedId.value || runningNow.value) return;
  runningNow.value = true;
  try {
    await whenReady();
    await sidecar.client.post(`/api/monitor/tasks/${selectedId.value}/run-now`);
    toast.info("已派发，结果会通过 SSE 流推回");
  } catch (e: any) {
    toast.error(`派发失败: ${e?.message ?? e}`);
  } finally {
    runningNow.value = false;
  }
}

async function runNowTask(id: number) {
  if (id !== selectedId.value) {
    selectedId.value = id;
  }
  runNow();
}

async function deleteTask(task: TaskItem) {
  if (!confirm(`确认删除任务「${task.name}」？此操作不可恢复。`)) return;
  try {
    await whenReady();
    await sidecar.client.delete(`/api/monitor/tasks/${task.id}`);
    toast.success("已删除");
    if (selectedId.value === task.id) selectedId.value = null;
    await loadTasks();
  } catch (e: any) {
    toast.error(`删除失败: ${e?.message ?? e}`);
  }
}

function openEdit(task: TaskItem) {
  emit("edit-task", task);
}

// ──────────────────────────── lifecycle ────────────────────────────

onMounted(loadTasks);

watch(selectedId, (id) => {
  if (id !== null) loadHistory(id);
});
</script>

<template>
  <div class="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr] h-full">

    <!-- ═══════════════════════════════════════════════════════════
         LEFT CARD: 监测任务表
    ════════════════════════════════════════════════════════════════ -->
    <section
      class="flex min-h-0 flex-col"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '22px',
      }"
    >
      <!-- Card header -->
      <div class="mb-3 flex flex-shrink-0 items-center justify-between gap-3">
        <div class="min-w-0">
          <div class="font-display text-[14px] font-semibold">监测任务</div>
          <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
            百度搜索 · 默认 + 最新资讯 · 自家命中
          </div>
        </div>
        <div class="flex flex-shrink-0 gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px]"
            :style="{
              background: 'transparent',
              color: 'var(--ink-2)',
              border: '1px solid var(--line)',
              borderRadius: '999px',
            }"
            @click="emit('batch-import')"
          >
            <Icon name="folder" :size="12" />
            <span>批量导入</span>
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium"
            :style="{
              background: 'var(--primary-deep)',
              color: '#fff',
              borderRadius: '999px',
            }"
            @click="emit('add-task')"
          >
            <Icon name="plus" :size="12" />
            <span>新增任务</span>
          </button>
        </div>
      </div>

      <!-- Table: fills remaining height -->
      <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <!-- Header row -->
        <div
          class="grid flex-shrink-0 items-center py-2 text-[11px] uppercase"
          :style="{
            gridTemplateColumns: '1.6fr .7fr .5fr .5fr .5fr 1.4fr',
            letterSpacing: '1.2px',
            color: 'var(--ink-3)',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <div>搜索关键词</div>
          <div>类型</div>
          <div>上次</div>
          <div>变化</div>
          <div>状态</div>
          <div>操作</div>
        </div>

        <!-- Loading state -->
        <div
          v-if="loadingTasks"
          class="py-10 text-center text-[12px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          加载中…
        </div>

        <!-- Empty state -->
        <div
          v-else-if="tasks.length === 0"
          class="py-10 text-center text-[12.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          暂无百度关键词任务 · 点击「新增任务」开始监测
        </div>

        <!-- Task rows -->
        <template v-else>
          <div
            v-for="(t, i) in tasks"
            :key="t.id"
            class="grid cursor-pointer items-center transition"
            :style="{
              gridTemplateColumns: '1.6fr .7fr .5fr .5fr .5fr 1.4fr',
              background: selectedId === t.id ? 'var(--card-2)' : 'transparent',
              borderBottom: i < tasks.length - 1 ? '1px solid var(--line)' : 'none',
              padding: '14px 8px',
              borderRadius: '10px',
            }"
            @click="selectedId = t.id"
          >
            <!-- 搜索关键词 -->
            <div class="min-w-0">
              <div class="truncate text-[13px] font-medium">{{ t.name }}</div>
              <div
                class="truncate text-[11px] mt-0.5"
                :style="{ color: 'var(--ink-3)' }"
              >{{ t.config.search_keyword }}</div>
            </div>

            <!-- 类型 -->
            <div class="text-[12px]" :style="{ color: 'var(--ink-2)' }">百度关键词</div>

            <!-- 上次：N/10 + 首条 #M (only for selected task with data) -->
            <div class="font-display text-[13px] font-bold">
              <template v-if="t.id === selectedId && latestMetric">
                <span>{{ latestMetric.default_matched_count }}/10</span>
                <div
                  class="text-[10.5px] font-normal mt-0.5"
                  :style="{ color: 'var(--ink-3)' }"
                >
                  首条
                  {{ latestMetric.default_first_rank > 0 ? `#${latestMetric.default_first_rank}` : '—' }}
                </div>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>

            <!-- 变化 (only for selected task) -->
            <div>
              <template v-if="t.id === selectedId && history.length > 0">
                <template v-if="history.length === 1">
                  <Pill tone="info">首次</Pill>
                </template>
                <template v-else-if="rankDelta === null">
                  <span :style="{ color: 'var(--ink-3)' }">—</span>
                </template>
                <template v-else-if="rankDelta > 0">
                  <Pill tone="ok">
                    <Icon name="arrowUp" :size="10" />
                    +{{ rankDelta }}
                  </Pill>
                </template>
                <template v-else-if="rankDelta < 0">
                  <Pill tone="warn">
                    <Icon name="arrowDown" :size="10" />
                    {{ rankDelta }}
                  </Pill>
                </template>
                <Pill v-else tone="info">持平</Pill>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>

            <!-- 状态 -->
            <div>
              <Pill :tone="taskRowState(t).tone">{{ taskRowState(t).statusLabel }}</Pill>
            </div>

            <!-- 操作 -->
            <div class="flex items-center gap-0.5">
              <button
                type="button"
                class="whitespace-nowrap text-[11px]"
                :style="{
                  padding: '4px 10px',
                  borderRadius: '999px',
                  color: 'var(--primary-deep)',
                  cursor: 'pointer',
                }"
                @click.stop="runNowTask(t.id)"
              >立刻监测</button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--ink-3)' }"
                title="编辑任务"
                @click.stop="openEdit(t)"
              >
                <Icon name="edit" :size="13" />
              </button>
              <button
                type="button"
                class="inline-flex h-7 w-7 items-center justify-center"
                :style="{ borderRadius: '999px', color: 'var(--ink-3)' }"
                title="删除任务"
                @click.stop="deleteTask(t)"
              >
                <Icon name="trash" :size="13" />
              </button>
            </div>
          </div>
        </template>
      </div>
    </section>

    <!-- ═══════════════════════════════════════════════════════════
         RIGHT CARD: 任务详情
    ════════════════════════════════════════════════════════════════ -->
    <section
      class="flex min-h-0 flex-col overflow-y-auto"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '22px',
      }"
    >
      <!-- Empty state -->
      <div
        v-if="!selectedTask"
        class="flex flex-1 items-center justify-center"
        :style="{ color: 'var(--ink-3)', fontSize: '12.5px' }"
      >
        请在左侧选择任务
      </div>

      <template v-else>
        <!-- Header: task name + buttons -->
        <div class="flex flex-shrink-0 items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="font-display text-[14px] font-semibold truncate" style="max-width: 260px;">
              {{ selectedTask.name.length > 30 ? selectedTask.name.slice(0, 30) + '…' : selectedTask.name }}
            </div>
            <div class="text-[11.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">百度关键词</div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-1.5">
            <button
              type="button"
              class="inline-flex items-center gap-1 px-3 py-1.5 text-[11.5px]"
              :style="{
                background: 'var(--card-2)',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
              }"
              title="编辑任务"
              @click="openEdit(selectedTask)"
            >
              <Icon name="edit" :size="12" />
              <span>编辑</span>
            </button>
            <a
              v-if="latestMetric?.serp_url"
              :href="latestMetric.serp_url"
              target="_blank"
              rel="noopener"
              class="inline-flex items-center gap-1 px-3 py-1.5 text-[11.5px]"
              :style="{
                background: 'var(--card-2)',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
                textDecoration: 'none',
              }"
              title="在浏览器打开 SERP"
            >
              <Icon name="external" :size="12" />
              <span>SERP 链接</span>
            </a>
          </div>
        </div>

        <!-- Loading state -->
        <div
          v-if="loadingHistory"
          class="mt-4 text-center text-[12px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          加载中…
        </div>

        <!-- KPI 三联 -->
        <div class="mt-3 grid grid-cols-3 gap-3">
          <!-- 本次首条排名 -->
          <div
            :style="{
              padding: '12px',
              borderRadius: '12px',
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
            }"
          >
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">本次首条排名</div>
            <div class="font-display mt-1 font-bold" :style="{ fontSize: '18px' }">
              <template v-if="latestMetric">
                {{ latestMetric.default_first_rank > 0 ? `#${latestMetric.default_first_rank}` : '—' }}
                <div class="mt-0.5 text-[10.5px] font-normal" :style="{ color: 'var(--ink-3)' }">
                  命中 {{ latestMetric.default_matched_count }} 条 / 10
                </div>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>
          </div>

          <!-- 上次首条排名 -->
          <div
            :style="{
              padding: '12px',
              borderRadius: '12px',
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
            }"
          >
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">上次首条排名</div>
            <div class="font-display mt-1 font-bold" :style="{ fontSize: '18px' }">
              <template v-if="prevMetric">
                {{ prevMetric.default_first_rank > 0 ? `#${prevMetric.default_first_rank}` : '—' }}
                <div class="mt-0.5 text-[10.5px] font-normal" :style="{ color: 'var(--ink-3)' }">
                  命中 {{ prevMetric.default_matched_count }} 条 / 10
                </div>
              </template>
              <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
            </div>
          </div>

          <!-- 检查频率 -->
          <div
            :style="{
              padding: '12px',
              borderRadius: '12px',
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
            }"
          >
            <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">检查频率</div>
            <div class="font-display mt-1 font-bold" :style="{ fontSize: '14px' }">
              {{ scheduleLabel(selectedTask.schedule_cron) }}
            </div>
          </div>
        </div>

        <!-- Sparkline: 最近 14 次排名 -->
        <div class="mt-5">
          <div class="mb-2 text-[12px] font-semibold">最近 14 次排名</div>
          <Sparkline
            v-if="sparkPoints.length > 1"
            :points="sparkPoints"
            :width="380"
            :height="70"
            stroke="var(--primary, #ee6a2a)"
            :axis-labels="sparkLabels"
            fluid
          />
          <div v-else class="text-[11.5px] italic" :style="{ color: 'var(--ink-3)' }">
            无历史数据 —— 跑几次「立刻监测」后会成线。
          </div>
        </div>

        <!-- 没有 metric 数据 -->
        <div
          v-if="!loadingHistory && !latestMetric"
          class="mt-6 py-6 text-center text-[12px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          暂无检查记录
        </div>

        <template v-if="latestMetric">
          <!-- 前 10 条结果 -->
          <div class="mt-4">
            <div class="mb-2 flex items-center justify-between">
              <div class="text-[12px] font-semibold">前 10 条结果</div>
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                自家命中
                <span :style="{ color: 'var(--primary-deep)', fontWeight: 600 }">
                  {{ latestMetric.default_matched_count }}
                </span>
                条
              </div>
            </div>
            <template v-if="latestMetric.default_results.length">
              <div
                v-for="row in latestMetric.default_results"
                :key="row.rank"
                class="mb-1.5 flex items-start gap-3"
                :style="{
                  padding: '10px',
                  borderRadius: '10px',
                  background: row.matches_brand ? 'var(--primary-soft)' : 'var(--card-2)',
                  border: '1px solid ' + (row.matches_brand ? 'rgba(238,106,42,0.3)' : 'var(--line)'),
                }"
              >
                <!-- Rank pill -->
                <span
                  class="font-display text-[13px] font-bold flex-shrink-0"
                  :style="{
                    width: '22px',
                    color: row.matches_brand ? 'var(--primary-deep)' : 'var(--ink-2)',
                  }"
                >#{{ row.rank }}</span>
                <!-- Title + host row -->
                <div class="min-w-0 flex-1">
                  <a
                    :href="row.url"
                    target="_blank"
                    rel="noopener"
                    class="block text-[12.5px] font-medium leading-snug"
                    :style="{
                      color: 'var(--ink)',
                      textDecoration: 'none',
                      display: '-webkit-box',
                      WebkitLineClamp: '2',
                      WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                    }"
                    :title="row.title"
                  >{{ row.title }}</a>
                  <div class="flex items-center gap-2 mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                    <span class="truncate">{{ row.host }}</span>
                    <span
                      v-if="row.matches_brand"
                      class="flex-shrink-0 ml-auto"
                      :style="{ color: 'var(--primary-deep)', fontWeight: 600 }"
                    >自家 · {{ row.matched_brand }}</span>
                  </div>
                </div>
              </div>
            </template>
            <div
              v-else
              class="py-4 text-center text-[11.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              无结果
            </div>
          </div>

          <!-- 最新资讯 (only when news_present) -->
          <div v-if="latestMetric.news_present" class="mt-4">
            <div class="mb-2 flex items-center justify-between">
              <div class="text-[12px] font-semibold">
                最新资讯
                <span class="text-[11px] font-normal ml-1" :style="{ color: 'var(--ink-3)' }">
                  （{{ latestMetric.news_results.length }} 条）
                </span>
              </div>
              <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                <span v-if="latestMetric.news_first_rank > 0">
                  首位 <b :style="{ color: 'var(--primary-deep)' }">#{{ latestMetric.news_first_rank }}</b>
                </span>
                <span v-else>未命中</span>
              </div>
            </div>
            <template v-if="latestMetric.news_results.length">
              <div
                v-for="row in latestMetric.news_results"
                :key="row.rank"
                class="mb-1.5 flex items-start gap-3"
                :style="{
                  padding: '10px',
                  borderRadius: '10px',
                  background: row.matches_brand ? 'var(--primary-soft)' : 'var(--card-2)',
                  border: '1px solid ' + (row.matches_brand ? 'rgba(238,106,42,0.3)' : 'var(--line)'),
                }"
              >
                <span
                  class="font-display text-[13px] font-bold flex-shrink-0"
                  :style="{
                    width: '22px',
                    color: row.matches_brand ? 'var(--primary-deep)' : 'var(--ink-2)',
                  }"
                >#{{ row.rank }}</span>
                <div class="min-w-0 flex-1">
                  <a
                    :href="row.url"
                    target="_blank"
                    rel="noopener"
                    class="block text-[12.5px] font-medium leading-snug"
                    :style="{
                      color: 'var(--ink)',
                      textDecoration: 'none',
                      display: '-webkit-box',
                      WebkitLineClamp: '2',
                      WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                    }"
                    :title="row.title"
                  >{{ row.title }}</a>
                  <div class="flex items-center gap-2 mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                    <span class="truncate">{{ row.host }}</span>
                    <span
                      v-if="row.matches_brand"
                      class="flex-shrink-0 ml-auto"
                      :style="{ color: 'var(--primary-deep)', fontWeight: 600 }"
                    >自家 · {{ row.matched_brand }}</span>
                  </div>
                </div>
              </div>
            </template>
            <div
              v-else
              class="py-4 text-center text-[11.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              无资讯结果
            </div>
          </div>
        </template>
      </template>
    </section>
  </div>
</template>
