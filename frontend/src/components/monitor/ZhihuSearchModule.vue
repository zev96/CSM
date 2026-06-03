<script setup lang="ts">
/**
 * 知乎搜索排名监控模块 —— 拉 zhihu_search 任务、跑、展示最新结果的前 10
 * 命中情况。数据形状对齐 csm_core/monitor/platforms/zhihu_search.py 的 metric。
 */
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { subscribe } from "@/api/client";
import { useToast } from "@/composables/useToast";
import AddTaskModal from "./AddTaskModal.vue";

interface ResultItem {
  rank: number;
  title: string;
  content_type: string;
  url: string;
  voteup_count: number;
  author_name: string;
  matches_brand: boolean;
  matched_brand: string | null;
  matched_field: string | null;
  excerpt: string;
}
interface KeywordResult {
  keyword: string;
  results: ResultItem[];
  matched_count: number;
  first_rank: number;
  result_count: number;
  empty_reason: string | null;
  api_code: number | null;
  fetch_error: string | null;
}
interface Task {
  id: number;
  type: string;
  name: string;
  target_url: string;
  enabled: boolean;
  schedule_cron: string;
  last_check_at: string | null;
  last_status: string | null;
  config?: Record<string, any>;
}

const sidecar = useSidecar();
const toast = useToast();

const tasks = ref<Task[]>([]);
const selectedId = ref<number | null>(null);
const latestMetric = ref<Record<string, any> | null>(null);
const latestStatus = ref<string | null>(null);
const running = ref<Set<number>>(new Set());
const showModal = ref(false);
const editingTask = ref<Task | null>(null);

const selected = computed(() => tasks.value.find((t) => t.id === selectedId.value) || null);
const keywordResults = computed<KeywordResult[]>(() => latestMetric.value?.keywords ?? []);

async function loadTasks() {
  // GET /api/monitor/tasks → { count, tasks: [...] }（已核对 routes/monitor.py:41-48）
  const r = await sidecar.client.get("/api/monitor/tasks", { params: { type: "zhihu_search" } });
  tasks.value = r.data.tasks ?? [];
  if (selectedId.value === null && tasks.value.length) {
    selectTask(tasks.value[0].id);
  }
}

async function loadLatest(taskId: number) {
  // GET /api/monitor/results → { task_id, count, results: [...] }，行含 .metric / .status
  // （已核对 routes/monitor.py:175-183 + services/monitor_service.py:result_to_dict）
  const r = await sidecar.client.get("/api/monitor/results", { params: { task_id: taskId, limit: 1 } });
  const rows = r.data.results ?? [];
  if (rows.length) {
    latestMetric.value = rows[0].metric ?? null;
    latestStatus.value = rows[0].status ?? null;
  } else {
    latestMetric.value = null;
    latestStatus.value = null;
  }
}

async function selectTask(id: number) {
  selectedId.value = id;
  await loadLatest(id);
}

async function runNow(id: number) {
  running.value = new Set(running.value).add(id);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${id}/run-now`, {});
  } catch (e: any) {
    toast.error(`触发失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    const s = new Set(running.value); s.delete(id); running.value = s;
  }
}

async function removeTask(id: number) {
  if (!confirm("确认删除这个知乎搜索监控任务？")) return;
  await sidecar.client.delete(`/api/monitor/tasks/${id}`);
  if (selectedId.value === id) { selectedId.value = null; latestMetric.value = null; }
  await loadTasks();
}

function openAdd() { editingTask.value = null; showModal.value = true; }
function openEdit(t: Task) { editingTask.value = t; showModal.value = true; }

async function onTaskSaved() {
  showModal.value = false;
  await loadTasks();
  if (selectedId.value !== null) await loadLatest(selectedId.value);
}

let stopSSE: (() => void) | null = null;
onMounted(async () => {
  await loadTasks();
  stopSSE = subscribe("/api/monitor/events", {
    finished: async (d: any) => {
      const s = new Set(running.value); s.delete(d?.task_id); running.value = s;
      await loadTasks();
      const sel = selectedId.value;
      if (sel !== null && d?.task_id === sel) await loadLatest(sel);
    },
    failed: async (d: any) => {
      const s = new Set(running.value); s.delete(d?.task_id); running.value = s;
      await loadTasks();
    },
  });
});
onUnmounted(() => { if (stopSSE) stopSSE(); });
</script>

<template>
  <div class="flex gap-4">
    <!-- 左：任务列表 -->
    <div class="w-[240px] shrink-0 flex flex-col gap-2">
      <button class="text-[12.5px] px-3 py-2 rounded bg-[var(--ink)] text-white" @click="openAdd">
        + 新增知乎搜索监控
      </button>
      <div
        v-for="t in tasks" :key="t.id"
        class="px-3 py-2 rounded cursor-pointer text-[12.5px] border"
        :style="{
          background: t.id === selectedId ? 'var(--card-2)' : 'transparent',
          borderColor: 'var(--line)',
        }"
        @click="selectTask(t.id)"
      >
        <div class="font-medium truncate">{{ t.name }}</div>
        <div class="text-[11px] text-[var(--ink-3)]">
          {{ t.last_status ?? "未运行" }} · {{ t.schedule_cron }}
        </div>
      </div>
      <div v-if="!tasks.length" class="text-[12px] text-[var(--ink-3)] px-1">
        还没有知乎搜索监控任务。
      </div>
    </div>

    <!-- 右：详情 -->
    <div class="flex-1 min-w-0">
      <div v-if="!selected" class="text-[13px] text-[var(--ink-3)] p-6">
        从左侧选择或新建一个任务。
      </div>
      <div v-else class="flex flex-col gap-3">
        <div class="flex items-center gap-2">
          <div class="text-[14px] font-medium">{{ selected.name }}</div>
          <a :href="selected.target_url" target="_blank" class="text-[11.5px] text-[var(--primary-deep)] hover:underline">知乎搜索页 ↗</a>
          <div class="ml-auto flex gap-2">
            <button class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" :disabled="running.has(selected.id)" @click="runNow(selected.id)">
              {{ running.has(selected.id) ? "运行中…" : "立即执行" }}
            </button>
            <button class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" @click="openEdit(selected)">编辑</button>
            <button class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" @click="removeTask(selected.id)">删除</button>
          </div>
        </div>

        <div v-if="latestStatus === 'error'" class="text-[12px] text-red-600">
          鉴权失败：检查设置页的知乎 Access Secret，或系统时钟是否准确。
        </div>
        <div v-if="latestStatus === 'risk_control'" class="text-[12px] text-amber-600">
          被知乎频率/配额限制（30001），稍后重试。
        </div>
        <div v-if="!latestMetric" class="text-[12px] text-[var(--ink-3)]">还没有结果，点「立即执行」。</div>

        <!-- 每个关键词一张卡 -->
        <div v-for="kw in keywordResults" :key="kw.keyword" class="border rounded p-3" :style="{ borderColor: 'var(--line)' }">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-[13px] font-medium">{{ kw.keyword }}</span>
            <span v-if="kw.first_rank > 0" class="text-[11px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">
              首位命中 #{{ kw.first_rank }} · 共 {{ kw.matched_count }} 条
            </span>
            <span v-else class="text-[11px] px-1.5 py-0.5 rounded bg-[var(--card-2)] text-[var(--ink-3)]">前 10 无命中</span>
            <span v-if="kw.fetch_error" class="text-[11px] text-red-600">{{ kw.fetch_error }}</span>
            <span v-else-if="kw.empty_reason" class="text-[11px] text-[var(--ink-3)]">知乎无结果：{{ kw.empty_reason }}</span>
          </div>
          <table class="w-full text-[12px]">
            <thead class="text-[var(--ink-3)]">
              <tr><th class="text-left w-8">#</th><th class="text-left">标题</th><th class="text-left w-16">类型</th><th class="text-left w-20">作者</th><th class="text-right w-14">赞同</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="r in kw.results" :key="r.rank"
                :style="{ background: r.matches_brand ? 'rgba(34,197,94,0.08)' : 'transparent' }"
              >
                <td>{{ r.rank }}</td>
                <td class="truncate max-w-[320px]">
                  <a :href="r.url" target="_blank" class="hover:underline">{{ r.title }}</a>
                  <span v-if="r.matches_brand" class="ml-1 text-[10px] px-1 rounded bg-green-200 text-green-800">命中:{{ r.matched_brand }}({{ r.matched_field }})</span>
                </td>
                <td>{{ r.content_type }}</td>
                <td class="truncate max-w-[80px]">{{ r.author_name }}</td>
                <td class="text-right">{{ r.voteup_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <AddTaskModal
      v-model:open="showModal"
      :default-type="'zhihu_search' as any"
      :editing-task="editingTask as any"
      @created="onTaskSaved"
      @updated="onTaskSaved"
    />
  </div>
</template>
