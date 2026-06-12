<script setup lang="ts">
import { ref, watch } from "vue";

import Dialog from "@/components/ui/Dialog.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useMiningStore } from "@/stores/mining";

const props = defineProps<{
  /** v-model:visible from parent */
  visible: boolean;
  jobId: number | null;
  /** Shown in dialog title for context */
  jobKeyword: string;
}>();

const emit = defineEmits<{
  (e: "update:visible", v: boolean): void;
}>();

const store = useMiningStore();

// ── form state ──────────────────────────────────────────────────────────────
const taskNamePrefix = ref("");
const topN = ref(5);
// 与批量导入监测任务一致：手动触发 / 每天 HH:MM。手动 → schedule_cron=null
// （后端把 null 落库成 "manual"，跟批量导入产出的任务行一致）。
const scheduleMode = ref<"manual" | "daily">("manual");
const dailyTime = ref("09:00");

// ── reset when modal opens ───────────────────────────────────────────────────
watch(
  () => props.visible,
  (v) => {
    if (!v) return;
    taskNamePrefix.value = "";
    topN.value = 5;
    scheduleMode.value = "manual";
    dailyTime.value = "09:00";
    // Clear any previous result/error from the store so reopening is fresh.
    store.syncResult = null;
    store.syncError = null;
  },
);

// ── actions ──────────────────────────────────────────────────────────────────
async function onConfirm() {
  if (props.jobId === null) return;
  if (!taskNamePrefix.value.trim()) return;
  try {
    await store.syncToMonitor(props.jobId, {
      task_name_prefix: taskNamePrefix.value.trim(),
      top_n: topN.value,
      schedule_cron: scheduleMode.value === "manual" ? null : dailyTime.value,
    });
  } catch {
    // syncToMonitor re-throws after recording store.syncError; the error is
    // already surfaced via the red pill below. Swallow here so it doesn't
    // bubble up as an unhandled promise rejection (Tauri shows a native
    // error dialog for those).
  }
  // Do NOT auto-close — user reads result then closes manually.
}

function close() {
  if (store.syncingJobId !== null) return; // don't close mid-sync
  emit("update:visible", false);
}
</script>

<template>
  <Dialog
    :open="visible"
    size="md"
    :title="jobKeyword ? `同步到监控 · ${jobKeyword}` : '同步到监控'"
    show-close
    :closable="store.syncingJobId === null"
    @update:open="close"
  >
    <!-- Subtitle below Dialog's title; mirrors BatchImportTaskModal spacing. -->
    <div class="mb-4 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
      将该任务下已写评论的视频同步为监测任务（默认未启用，可在监测中心手动开启）
    </div>

    <div class="flex flex-col gap-4">
      <!-- 任务名前缀 —— 每条监控任务名 = `${前缀} - <视频 ID 尾段>` -->
      <div class="flex items-center gap-2">
        <label
          class="text-[12px] font-medium"
          :style="{ color: 'var(--ink-2)', minWidth: '72px' }"
        >任务名前缀</label>
        <input
          v-model="taskNamePrefix"
          type="text"
          placeholder="如：0528-吸尘器（每条视频会自动加上视频 ID 后缀）"
          class="bg-card-2 focus:bg-card-white outline-none transition-colors"
          :style="{
            flex: 1,
            height: '34px',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '0 12px',
            fontSize: '12.5px',
            color: 'var(--ink)',
          }"
        >
      </div>

      <!-- 监控数量 top_n + 计划 —— 底部双列，与批量导入一致 -->
      <div class="grid grid-cols-2 gap-4">
        <div>
          <div class="mb-1 text-[12px] font-medium" :style="{ color: 'var(--ink-2)' }">
            <span title="希望评论排在前几位（默认 5）。后台始终扫描前 150 条，能看到真实位置。">
              监控数量 top_n
            </span>
          </div>
          <input
            type="number"
            :value="topN"
            min="1"
            max="50"
            class="bg-card-2 focus:bg-card-white outline-none transition-colors"
            :style="{
              width: '100%',
              height: '34px',
              padding: '0 12px',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              fontSize: '12.5px',
              color: 'var(--ink)',
            }"
            @change="(e) => (topN = Number((e.target as HTMLInputElement).value) || 5)"
          >
        </div>
        <div>
          <div class="mb-1 text-[12px] font-medium" :style="{ color: 'var(--ink-2)' }">
            计划
          </div>
          <div class="flex items-center gap-2">
            <div class="flex-1">
              <FormSelect
                :model-value="scheduleMode"
                :options="[
                  { label: '手动触发', value: 'manual' },
                  { label: '每天', value: 'daily' },
                ]"
                width="100%"
                @update:model-value="(v) => (scheduleMode = v as 'manual' | 'daily')"
              />
            </div>
            <input
              v-if="scheduleMode === 'daily'"
              v-model="dailyTime"
              placeholder="HH:MM"
              class="bg-card-2 focus:bg-card-white outline-none transition-colors"
              :style="{
                width: '90px',
                height: '34px',
                padding: '0 10px',
                border: '1px solid var(--line)',
                borderRadius: '8px',
                fontSize: '12.5px',
                color: 'var(--ink)',
              }"
            >
          </div>
        </div>
      </div>

      <!-- 成功结果 -->
      <div
        v-if="store.syncResult"
        class="text-[12px]"
        :style="{
          background: 'rgba(108,155,93,0.10)',
          border: '1px solid rgba(108,155,93,0.35)',
          borderRadius: '10px',
          padding: '10px 12px',
          color: 'var(--ink-2)',
          lineHeight: 1.6,
        }"
      >
        已创建
        <b :style="{ color: 'var(--ink)' }">{{ store.syncResult.created }}</b>
        条监控任务，跳过重复
        <b :style="{ color: 'var(--ink)' }">{{ store.syncResult.skipped_dup }}</b>
        条，无草稿
        <b :style="{ color: 'var(--ink)' }">{{ store.syncResult.skipped_no_draft }}</b>
        条。
      </div>

      <!-- 错误 -->
      <div
        v-if="store.syncError"
        class="text-[12px]"
        :style="{
          background: 'rgba(216,90,72,0.08)',
          border: '1px solid rgba(216,90,72,0.35)',
          borderRadius: '10px',
          padding: '10px 12px',
          color: 'var(--red, #d85a48)',
          lineHeight: 1.55,
        }"
      >
        {{ store.syncError }}
      </div>
    </div>

    <template #footer>
      <div class="flex-1" />
      <button
        type="button"
        :style="{
          background: 'transparent',
          border: '1px solid var(--line)',
          color: 'var(--ink-2)',
          padding: '7px 18px',
          fontSize: '12.5px',
          borderRadius: '999px',
        }"
        :disabled="store.syncingJobId !== null"
        @click="close"
      >取消</button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5"
        :style="{
          background: taskNamePrefix.trim() ? 'var(--dark)' : 'var(--card-2)',
          color: taskNamePrefix.trim() ? 'var(--card-white)' : 'var(--ink-3)',
          padding: '7px 18px',
          fontSize: '12.5px',
          fontWeight: 500,
          borderRadius: '999px',
          cursor: taskNamePrefix.trim() && store.syncingJobId === null ? 'pointer' : 'not-allowed',
          opacity: store.syncingJobId !== null ? 0.6 : 1,
        }"
        :disabled="store.syncingJobId !== null || !taskNamePrefix.trim()"
        @click="onConfirm"
      >
        <Spinner v-if="store.syncingJobId !== null" :size="12" />
        <Icon v-else name="upload" :size="13" />
        <span>{{ store.syncingJobId !== null ? "同步中…" : "同步" }}</span>
      </button>
    </template>
  </Dialog>
</template>
