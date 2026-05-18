<script setup lang="ts">
/**
 * 左栏任务列表里的一项。
 *
 * 视觉：
 *   - 选中态：浅色背景 + 左侧 3px 橙色竖条
 *   - 「抓取中」状态额外在底部展示进度条
 *   - 状态 pill 跟 job.status 映射到颜色 + 文案
 *
 * 数据来源：
 *   - keyword / status / progress / platforms / started_at 都来自 MiningJob
 *   - 累计抓取数取 progress 里所有平台 got 之和(实际持久化的 video 数会被
 *     dedup 影响略低,这里展示用够准)
 */
import { computed } from "vue";
import type { MiningJob, Platform } from "@/stores/mining";

const props = defineProps<{
  job: MiningJob;
  selected: boolean;
  /** True if this job is the one currently in flight (SSE-driven). */
  running: boolean;
}>();

defineEmits<{ (e: "select"): void }>();

const PLATFORM_META: Record<Platform, { letter: string; color: string }> = {
  bilibili: { letter: "B", color: "#fb7299" },
  douyin: { letter: "D", color: "#1c1a17" },
  kuaishou: { letter: "K", color: "#ff6633" },
};

const STATUS_LABEL: Record<string, string> = {
  pending: "等待",
  running: "抓取中",
  done: "完成",
  partial_done: "完成",
  failed: "失败",
  cancelled: "取消",
  interrupted: "中断",
};

const STATUS_TONE: Record<string, { bg: string; fg: string }> = {
  pending: { bg: "rgba(28,26,23,0.08)", fg: "var(--ink-3)" },
  running: { bg: "rgba(238,106,42,0.16)", fg: "#b34d12" },
  done: { bg: "rgba(96,138,72,0.18)", fg: "#4d6b2f" },
  partial_done: { bg: "rgba(96,138,72,0.18)", fg: "#4d6b2f" },
  failed: { bg: "rgba(196,68,57,0.16)", fg: "var(--red)" },
  cancelled: { bg: "rgba(28,26,23,0.08)", fg: "var(--ink-3)" },
  interrupted: { bg: "rgba(28,26,23,0.08)", fg: "var(--ink-3)" },
};

const status = computed(() => props.job.status);
const isRunning = computed(() => props.running || status.value === "running");

const totalGot = computed(() => {
  // Sum got across all platforms in the progress map.
  let n = 0;
  for (const plat of props.job.platforms) {
    const pp = props.job.progress?.[plat];
    if (pp?.got) n += pp.got;
  }
  return n;
});

const totalTarget = computed(() => {
  let n = 0;
  for (const plat of props.job.platforms) {
    const pp = props.job.progress?.[plat];
    if (pp?.target) n += pp.target;
  }
  // Fallback to target_per_platform × platforms.length if progress missing.
  return n || props.job.target_per_platform * props.job.platforms.length;
});

const progressPct = computed(() => {
  if (totalTarget.value === 0) return 0;
  return Math.min(100, (totalGot.value / totalTarget.value) * 100);
});

const dateLabel = computed(() => {
  const src = props.job.started_at || props.job.created_at;
  if (!src) return "";
  const d = new Date(src);
  if (isNaN(d.getTime())) return "";
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${m}月${day}日 ${hh}:${mm}`;
});

const statusLabel = computed(() => STATUS_LABEL[status.value] || status.value);
const statusTone = computed(() => STATUS_TONE[status.value] || STATUS_TONE.pending);
</script>

<template>
  <button
    type="button"
    @click="$emit('select')"
    :style="{
      position: 'relative',
      display: 'block',
      width: '100%',
      textAlign: 'left',
      padding: '13px 14px 14px 17px',
      background: selected ? 'var(--card-2)' : 'transparent',
      border: 'none',
      borderRadius: '12px',
      cursor: 'pointer',
      overflow: 'hidden',
    }"
  >
    <!-- Selected-state orange vertical bar -->
    <span
      v-if="selected"
      :style="{
        position: 'absolute',
        top: '12px',
        bottom: '12px',
        left: '6px',
        width: '3px',
        borderRadius: '999px',
        background: 'var(--primary)',
      }"
    />

    <!-- Row 1: keyword + status pill -->
    <div class="flex items-center justify-between gap-2">
      <span class="font-display font-semibold text-[13.5px] truncate" style="color: var(--ink); flex: 1; min-width: 0;">
        {{ job.keyword }}
      </span>
      <span
        class="inline-flex items-center gap-1 flex-shrink-0"
        :style="{
          fontSize: '10.5px',
          fontWeight: 600,
          padding: '2px 8px',
          borderRadius: '999px',
          background: statusTone.bg,
          color: statusTone.fg,
        }"
      >
        <span
          v-if="isRunning"
          :style="{
            width: '5px', height: '5px', borderRadius: '999px',
            background: 'currentColor',
            animation: 'tlpulse 1.4s ease-in-out infinite',
          }"
        />
        {{ statusLabel }}
      </span>
    </div>

    <!-- Row 2: platform letter badges + count -->
    <div class="flex items-center gap-1.5 mt-2.5">
      <span
        v-for="p in job.platforms"
        :key="p"
        :style="{
          width: '17px', height: '17px', borderRadius: '5px',
          background: PLATFORM_META[p].color, color: '#fff',
          fontSize: '9.5px', fontWeight: 800,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }"
      >{{ PLATFORM_META[p].letter }}</span>
      <span class="text-[11px]" style="color: var(--ink-3); margin-left: 4px;">
        · {{ totalGot }} 条
      </span>
    </div>

    <!-- Row 3: date -->
    <div class="text-[10.5px] mt-1.5" style="color: var(--ink-4); font-feature-settings: 'tnum';">
      {{ dateLabel }}
    </div>

    <!-- Progress bar (running only) -->
    <div
      v-if="isRunning"
      :style="{
        marginTop: '10px',
        height: '3px',
        background: 'rgba(28,26,23,0.08)',
        borderRadius: '999px',
        overflow: 'hidden',
      }"
    >
      <div
        :style="{
          height: '100%',
          width: progressPct + '%',
          background: 'linear-gradient(90deg, var(--yellow), var(--primary))',
          borderRadius: '999px',
          transition: 'width .3s ease',
        }"
      />
    </div>
  </button>
</template>

<style scoped>
@keyframes tlpulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
</style>
