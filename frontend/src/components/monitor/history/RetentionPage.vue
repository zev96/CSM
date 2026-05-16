<script setup lang="ts">
/**
 * 评论留存率页 —— 历史报告 tab 的「评论留存率」子页。
 *
 * 数据从 GET /api/monitor/history/comment-retention?range=1d|7d|30d 拉。
 * range 切换时重新 fetch；1d 时隐藏主折线（24h 内无法画）。
 * drill-down 行点击 emit('navigate', {platform, batchName, taskId})。
 */
import { ref, computed, onMounted, watch } from "vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import LineChart from "./LineChart.vue";

type Range = "1d" | "7d" | "30d";
type PlatformKey = "bilibili_comment" | "douyin_comment" | "kuaishou_comment";

interface PlatformView {
  label: string;
  current_retained: number;
  current_total: number;
  current_deleted: number;
  rate_today: number;
  rate_prev: number;
  daily_series: Array<{ date: string; retained: number; total: number; rate: number }>;
}
interface DeletionEvent {
  platform: PlatformKey;
  task_id: number;
  batch_name: string;
  video_title: string;
  comment_text: string;
  status: "deleted" | "folded";
  at: string;
}
interface RetentionResponse {
  range: Range;
  platforms: Record<PlatformKey, PlatformView>;
  events: DeletionEvent[];
}

const emit = defineEmits<{
  navigate: [payload: { platform: PlatformKey; batchName: string; taskId: number }];
}>();

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();
const range = ref<Range>("7d");
const data = ref<RetentionResponse | null>(null);
const loading = ref(false);
const eventFilter = ref<"all" | PlatformKey>("all");

const PLATFORM_COLOR: Record<PlatformKey, string> = {
  bilibili_comment: "#ee6a2a",
  douyin_comment: "#1e1c19",
  kuaishou_comment: "#f5c042",
};
const PLATFORM_CHIP_BG: Record<PlatformKey, string> = {
  bilibili_comment: "rgba(238,106,42,0.15)",
  douyin_comment: "rgba(30,28,25,0.10)",
  kuaishou_comment: "rgba(245,192,66,0.18)",
};
const PLATFORM_CHIP_FG: Record<PlatformKey, string> = {
  bilibili_comment: "#c9521f",
  douyin_comment: "#1c1a17",
  kuaishou_comment: "#8a6810",
};

async function load() {
  loading.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/comment-retention", {
      params: { range: range.value },
    });
    data.value = r.data;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const platformList = computed(() => {
  if (!data.value) return [];
  return (["bilibili_comment", "douyin_comment", "kuaishou_comment"] as PlatformKey[]).map((k) => ({
    key: k,
    color: PLATFORM_COLOR[k],
    ...data.value!.platforms[k],
  }));
});

const filteredEvents = computed(() => {
  if (!data.value) return [];
  return eventFilter.value === "all"
    ? data.value.events
    : data.value.events.filter((e) => e.platform === eventFilter.value);
});

const chartLabels = computed(() => {
  const series = data.value?.platforms.bilibili_comment.daily_series ?? [];
  return series.map((s) => s.date.slice(5));  // "MM-DD"
});
const chartSeries = computed(() =>
  platformList.value.map((p) => ({
    label: p.label,
    color: p.color,
    data: p.daily_series.map((d) => Math.round(d.rate * 100)),
  })),
);

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function fmtPct(x: number): string { return `${Math.round(x * 100)}%`; }
function fmtDelta(curr: number, prev: number): { text: string; tone: "up" | "down" | "flat" } {
  const diff = Math.round((curr - prev) * 100);
  if (diff > 0) return { text: `↑ ${diff} pts`, tone: "up" };
  if (diff < 0) return { text: `↓ ${Math.abs(diff)} pts`, tone: "down" };
  return { text: "持平", tone: "flat" };
}
</script>

<template>
  <div v-if="loading && !data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">
    加载中…
  </div>
  <div v-else-if="!data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">
    暂无数据
  </div>
  <div v-else class="flex flex-col gap-3">
    <!-- range picker -->
    <div class="flex items-center justify-end flex-shrink-0">
      <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card)', border: '1px solid var(--line)' }">
        <button
          v-for="r in (['1d','7d','30d'] as Range[])" :key="r"
          @click="range = r"
          class="px-3.5 py-1 rounded-full text-[12px] font-medium transition-colors"
          :style="{
            background: range === r ? 'var(--dark)' : 'transparent',
            color: range === r ? 'var(--card)' : 'var(--ink-3)',
          }"
        >
          {{ r === "1d" ? "最近 1 天" : r === "7d" ? "最近 7 天" : "最近 30 天" }}
        </button>
      </div>
    </div>

    <!-- 3 KPI cards -->
    <div class="grid grid-cols-3 gap-2.5">
      <div
        v-for="p in platformList" :key="p.key"
        :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
        class="flex flex-col gap-1.5"
      >
        <div class="flex justify-between items-start">
          <div class="flex items-center gap-1.5 text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">
            <span :style="{ width: '8px', height: '8px', borderRadius: '50%', background: p.color }" />
            {{ p.label }}
          </div>
          <span
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            :style="{
              background: fmtDelta(p.rate_today, p.rate_prev).tone === 'up' ? 'rgba(122,155,94,0.15)'
                : fmtDelta(p.rate_today, p.rate_prev).tone === 'down' ? 'rgba(216,90,72,0.12)'
                : 'rgba(28,26,23,0.05)',
              color: fmtDelta(p.rate_today, p.rate_prev).tone === 'up' ? '#5e7848'
                : fmtDelta(p.rate_today, p.rate_prev).tone === 'down' ? 'var(--red)'
                : 'var(--ink-3)',
            }"
          >{{ fmtDelta(p.rate_today, p.rate_prev).text }}</span>
        </div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1, letterSpacing: '-0.5px' }">
          {{ fmtPct(p.rate_today) }}
        </div>
        <Sparkline
          v-if="range !== '1d' && p.daily_series.length > 0"
          :points="p.daily_series.map((d) => d.rate * 100)"
          :stroke="p.color"
          :height="28"
        />
        <div class="flex justify-between text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          <span>在显 <b :style="{ color: 'var(--ink)' }">{{ p.current_retained }}</b> / {{ p.current_total }}</span>
          <span>被删 <b :style="{ color: 'var(--red)' }">{{ p.current_deleted }}</b></span>
        </div>
      </div>
    </div>

    <!-- 主图（1d 时隐藏） -->
    <div
      v-if="range !== '1d'"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
    >
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">留存率趋势（按日）</div>
        <div class="flex gap-3 text-[11px]" :style="{ color: 'var(--ink-2)' }">
          <span v-for="p in platformList" :key="p.key">
            <span :style="{ display:'inline-block', width:'8px', height:'8px', background:p.color, borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />{{ p.label }}
          </span>
        </div>
      </div>
      <LineChart :labels="chartLabels" :series="chartSeries" :y-axis-formatter="(v) => `${v}%`" />
    </div>

    <!-- drill-down 表 -->
    <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '12px' }">
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">
          被删 / 折叠评论详情 <span class="font-normal" :style="{ color: 'var(--ink-3)' }">({{ filteredEvents.length }} 条 · 点行进详情)</span>
        </div>
        <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)' }">
          <button
            v-for="f in (['all','bilibili_comment','douyin_comment','kuaishou_comment'] as const)" :key="f"
            @click="eventFilter = f"
            class="px-3 py-1 rounded-full text-[11.5px] font-medium"
            :style="{
              background: eventFilter === f ? 'var(--dark)' : 'transparent',
              color: eventFilter === f ? 'var(--card)' : 'var(--ink-3)',
            }"
          >
            {{ f === "all" ? "全部" : f === "bilibili_comment" ? "B 站" : f === "douyin_comment" ? "抖音" : "快手" }}
          </button>
        </div>
      </div>
      <div v-if="!filteredEvents.length" class="py-6 text-center text-[12px]" :style="{ color: 'var(--ink-3)' }">
        无被删 / 折叠记录
      </div>
      <div v-else>
        <div
          v-for="e in filteredEvents" :key="e.task_id + '-' + e.at"
          @click="emit('navigate', { platform: e.platform, batchName: e.batch_name, taskId: e.task_id })"
          class="grid items-center gap-2 cursor-pointer transition-colors"
          :style="{
            gridTemplateColumns: '60px 1fr 110px 80px 18px',
            padding: '9px 12px',
            fontSize: '11.5px',
            borderRadius: '8px',
            borderTop: '1px solid rgba(28,26,23,0.06)',
          }"
          @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
          @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <div>
            <span
              class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
              :style="{ background: PLATFORM_CHIP_BG[e.platform], color: PLATFORM_CHIP_FG[e.platform] }"
            >{{ e.platform === "bilibili_comment" ? "B 站" : e.platform === "douyin_comment" ? "抖音" : "快手" }}</span>
          </div>
          <div>
            <div :style="{ color: 'var(--ink)' }">{{ e.comment_text || "（无文本）" }}</div>
            <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">{{ e.video_title }} · {{ e.batch_name }} 批次</div>
          </div>
          <div>
            <span
              class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
              :style="{ background: 'rgba(216,90,72,0.12)', color: 'var(--red)' }"
            >在显 → 无</span>
          </div>
          <div :style="{ color: 'var(--ink-3)' }">{{ fmtTime(e.at) }}</div>
          <div class="text-[16px] text-center" :style="{ color: 'var(--ink-4)', lineHeight: 1 }">›</div>
        </div>
      </div>
    </div>
  </div>
</template>
