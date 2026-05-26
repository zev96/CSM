<script setup lang="ts">
import { ref, watch } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Icon from "@/components/ui/Icon.vue";
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
const schedCron = ref("");

// ── reset when modal opens ───────────────────────────────────────────────────
watch(
  () => props.visible,
  (v) => {
    if (!v) return;
    taskNamePrefix.value = "";
    topN.value = 5;
    schedCron.value = "";
    // Clear any previous result/error from the store so reopening is fresh.
    store.syncResult = null;
    store.syncError = null;
  },
);

// ── actions ──────────────────────────────────────────────────────────────────
async function onConfirm() {
  if (props.jobId === null) return;
  if (!taskNamePrefix.value.trim()) return;
  await store.syncToMonitor(props.jobId, {
    task_name_prefix: taskNamePrefix.value.trim(),
    top_n: topN.value,
    schedule_cron: schedCron.value.trim() || null,
  });
  // Do NOT auto-close — user reads result then closes manually.
}

function close() {
  emit("update:visible", false);
}
</script>

<template>
  <Dialog
    :open="visible"
    :title="jobKeyword ? `同步到监控 · ${jobKeyword}` : '同步到监控'"
    size="md"
    :show-close="true"
    @update:open="close"
  >
    <!-- ── form ─────────────────────────────────────────────────────────── -->
    <div class="flex flex-col gap-5">

      <!-- task_name_prefix -->
      <div>
        <label class="text-[11.5px] font-semibold mb-1.5 block">
          任务名前缀
          <span class="text-red-400 ml-0.5">*</span>
        </label>
        <div
          class="flex items-center"
          style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 14px; padding: 0 14px; height: 44px;"
        >
          <input
            v-model="taskNamePrefix"
            placeholder="批次-1"
            class="sync-input flex-1 bg-transparent outline-none"
            style="font-size: 14px; color: var(--ink);"
          />
          <button
            v-if="taskNamePrefix"
            @click="taskNamePrefix = ''"
            class="inline-flex items-center justify-center"
            style="width: 22px; height: 22px; border-radius: 999px; color: var(--ink-3);"
          >
            <Icon name="x" :size="12" />
          </button>
        </div>
      </div>

      <!-- top_n -->
      <div>
        <label class="text-[11.5px] font-semibold mb-1.5 block">
          监控数量 top_n
        </label>
        <div class="flex items-center gap-3">
          <!-- stepper buttons mirroring existing range-style controls -->
          <button
            @click="topN = Math.max(1, topN - 1)"
            class="inline-flex items-center justify-center flex-shrink-0"
            style="width: 32px; height: 32px; border-radius: 8px; background: var(--card-2); border: 1px solid var(--line); color: var(--ink-2);"
          >
            <Icon name="minus" :size="12" />
          </button>
          <span
            class="font-display font-bold flex-1 text-center"
            style="font-size: 22px; letter-spacing: -0.5px; color: var(--primary-deep);"
          >{{ topN }}</span>
          <button
            @click="topN = Math.min(50, topN + 1)"
            class="inline-flex items-center justify-center flex-shrink-0"
            style="width: 32px; height: 32px; border-radius: 8px; background: var(--card-2); border: 1px solid var(--line); color: var(--ink-2);"
          >
            <Icon name="plus" :size="12" />
          </button>
        </div>
        <div class="text-[10.5px] mt-1" style="color: var(--ink-4);">
          范围 1–50，每个视频最多同步该数量的视频到监控
        </div>
      </div>

      <!-- schedule_cron -->
      <div>
        <label class="text-[11.5px] font-semibold mb-1.5 block">
          执行计划 (cron)
        </label>
        <div
          class="flex items-center"
          style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 14px; padding: 0 14px; height: 44px;"
        >
          <input
            v-model="schedCron"
            placeholder="留空=手动触发"
            class="sync-input flex-1 bg-transparent outline-none font-mono"
            style="font-size: 13px; color: var(--ink);"
          />
          <button
            v-if="schedCron"
            @click="schedCron = ''"
            class="inline-flex items-center justify-center"
            style="width: 22px; height: 22px; border-radius: 999px; color: var(--ink-3);"
          >
            <Icon name="x" :size="12" />
          </button>
        </div>
      </div>

      <!-- ── success result ──────────────────────────────────────────────── -->
      <div
        v-if="store.syncResult"
        class="flex items-start gap-2.5 px-3.5 py-3"
        style="background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.30); border-radius: 12px;"
      >
        <span
          style="width: 26px; height: 26px; border-radius: 8px; background: rgba(34,197,94,0.15); color: #15803d; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px;"
        >
          <Icon name="check" :size="13" />
        </span>
        <div class="text-[12px] leading-relaxed" style="color: var(--ink-2);">
          已创建
          <b class="font-display" style="color: var(--ink); font-size: 14px;">{{ store.syncResult.created }}</b>
          条监控任务，跳过重复
          <b style="color: var(--ink);">{{ store.syncResult.skipped_dup }}</b>
          条，无草稿
          <b style="color: var(--ink);">{{ store.syncResult.skipped_no_draft }}</b>
          条。
        </div>
      </div>

      <!-- ── error ──────────────────────────────────────────────────────── -->
      <div
        v-if="store.syncError"
        class="flex items-start gap-2.5 px-3.5 py-3"
        style="background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.28); border-radius: 12px;"
      >
        <span
          style="width: 26px; height: 26px; border-radius: 8px; background: rgba(239,68,68,0.12); color: #dc2626; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px;"
        >
          <Icon name="alert-triangle" :size="13" />
        </span>
        <div class="text-[12px] leading-relaxed" style="color: #dc2626;">
          {{ store.syncError }}
        </div>
      </div>

    </div>

    <!-- ── footer ─────────────────────────────────────────────────────────── -->
    <template #footer>
      <div class="flex-1" />
      <Btn variant="ghost" @click="close">取消</Btn>
      <Btn
        variant="solid"
        :disabled="!taskNamePrefix.trim() || store.syncingJobId !== null"
        @click="onConfirm"
      >
        <span
          v-if="store.syncingJobId !== null"
          class="inline-block animate-spin"
          style="width: 12px; height: 12px; border: 2px solid rgba(255,255,255,0.4); border-top-color: white; border-radius: 999px;"
        />
        <Icon v-else name="upload" :size="12" />
        同步
      </Btn>
    </template>
  </Dialog>
</template>

<style scoped>
.sync-input:focus-visible {
  outline: none;
}
</style>
