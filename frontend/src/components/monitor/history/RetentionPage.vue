<script setup lang="ts">
/**
 * 评论留存率页 —— 历史报告 tab 的「评论留存率」子页。
 *
 * 数据从 GET /api/monitor/history/comment-retention?range=1d|7d|30d 拉。
 * range 切换时重新 fetch；1d 时隐藏主折线（24h 内无法画）。
 * drill-down 行点击 emit('navigate', {platform, batchName, taskId})。
 */
import { ref, computed, onMounted, watch } from "vue";
// Sparkline 已下线（用户要求 KPI 卡不再显示小曲线，主图区覆盖趋势）
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
  /** 评论被删/折叠时的最后已知排名（后端 rank_from / rank_to 字段）。
   *  目前 backend 总是 None，UI 列直接显示「无」；待后端补 prev-snapshot
   *  追踪后即可不改 UI 自动生效。 */
  rank_from?: number | null;
  rank_to?: number | null;
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
  douyin_comment: "var(--ink)", // 抖音黑：走 ink token，暗色翻白避免折线/图例点隐形
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

// fmtTime 已下线 —— 事件列表 column 重构后不再显示检查时间。
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
  <!--
    Root：`flex h-full min-h-0 flex-col` —— 跟 ZhihuRankingPage /
    BaiduSEOAnalytics 同模式。h-full 吃满父级、min-h-0 解锁收缩，
    flex-col 排版三段：range picker / KPI / 图 全部 flex-shrink-0
    保持固定，最后的「被删/折叠评论详情」卡用 flex-1 + min-h-0 +
    overflow-y-auto 让列表行内部滚动。这样上面的图表不会跟着滚。
  -->
  <div v-else class="flex h-full min-h-0 flex-col gap-3">
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

    <!-- 3 KPI cards —— flex-shrink-0 锁定自然高度，不参与下方列表的伸缩 -->
    <div class="grid grid-cols-3 gap-2.5 flex-shrink-0">
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
                : 'rgba(var(--ink-rgb),0.05)',
              color: fmtDelta(p.rate_today, p.rate_prev).tone === 'up' ? 'var(--green-deep)'
                : fmtDelta(p.rate_today, p.rate_prev).tone === 'down' ? 'var(--red)'
                : 'var(--ink-3)',
            }"
          >{{ fmtDelta(p.rate_today, p.rate_prev).text }}</span>
        </div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1, letterSpacing: '-0.5px' }">
          {{ fmtPct(p.rate_today) }}
        </div>
        <!-- KPI Sparkline 按用户要求移除（切 range 直接换数字，下面主图区
             覆盖趋势）。 -->
        <div class="flex justify-between text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          <span>在显 <b :style="{ color: 'var(--ink)' }">{{ p.current_retained }}</b> / {{ p.current_total }}</span>
          <span>被删 <b :style="{ color: 'var(--red)' }">{{ p.current_deleted }}</b></span>
        </div>
      </div>
    </div>

    <!-- 主图（1d 时隐藏）—— flex-shrink-0 让图表保持自然高度，不随下方列表收缩 -->
    <div
      v-if="range !== '1d'"
      class="flex-shrink-0"
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

    <!--
      drill-down 表 —— 卡本身 flex-1 + min-h-0 + overflow-hidden 吃完
      KPI/图剩下的纵向空间；卡内 header 用 flex-shrink-0 锁顶部，列表
      行容器再套一层 flex-1 + min-h-0 + overflow-y-auto，把滚动锁在
      列表里。这样上面的 KPI、留存率趋势图、range picker 全部不动，
      只有评论行可以上下滑。
    -->
    <div
      class="flex min-h-0 flex-1 flex-col overflow-hidden"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '12px' }"
    >
      <div class="flex justify-between items-center mb-2 flex-shrink-0">
        <!-- 「(N 条 · 点行进详情)」副标按用户要求移除 -->
        <div class="text-[12.5px] font-semibold">
          被删 / 折叠评论详情
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
      <!--
        表格：固定 header 行 + 滚动 body。grid 4 列：
          平台 / 评论内容 / 排名 / 状态
        - 平台：原 chip
        - 评论内容：truncate（comment_text）
        - 排名：rank_from/to（后端目前总是 None → 显示「无」；待后端补
          prev-snapshot 追踪后 UI 自动生效）
        - 状态：deleted → 黑色 "-"，folded → 橙色 ↓
        移除了之前的检查时间列 + › chevron 列。
      -->
      <div
        class="grid items-center gap-2 flex-shrink-0 text-[11px] uppercase"
        :style="{
          gridTemplateColumns: '60px 1fr 80px 60px',
          padding: '8px 12px',
          letterSpacing: '1px',
          color: 'var(--ink-3)',
          borderBottom: '1px solid var(--line)',
        }"
      >
        <div>平台</div>
        <div>评论内容</div>
        <div class="text-center">排名</div>
        <div class="text-center">状态</div>
      </div>
      <div v-if="!filteredEvents.length" class="py-6 text-center text-[12px] flex-shrink-0" :style="{ color: 'var(--ink-3)' }">
        无被删 / 折叠记录
      </div>
      <div v-else class="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div
          v-for="e in filteredEvents" :key="e.task_id + '-' + e.at"
          @click="emit('navigate', { platform: e.platform, batchName: e.batch_name, taskId: e.task_id })"
          class="grid items-center gap-2 cursor-pointer transition-colors"
          :style="{
            gridTemplateColumns: '60px 1fr 80px 60px',
            padding: '11px 12px',
            fontSize: '12px',
            borderRadius: '8px',
            borderTop: '1px solid rgba(var(--ink-rgb),0.06)',
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
          <div :style="{ color: 'var(--ink)' }" class="truncate" :title="e.comment_text || '（无文本）'">
            {{ e.comment_text || "（无文本）" }}
          </div>
          <!-- 排名：rank_from 或 rank_to 任一存在就显示，否则「无」 -->
          <div class="text-center font-semibold">
            <template v-if="(e.rank_from ?? e.rank_to ?? 0) > 0">
              #{{ e.rank_from ?? e.rank_to }}
            </template>
            <span v-else :style="{ color: 'var(--ink-3)', fontWeight: 'normal' }">无</span>
          </div>
          <!--
            状态：deleted 黑色 "-"（被删或无），folded 橙色 ↓（折叠/降权）。
            hover title 给完整状态说明。
          -->
          <div class="text-center font-bold text-[14px]"
            :style="{
              color: e.status === 'folded' ? 'var(--primary, #ee6a2a)' : 'var(--ink, #1c1a17)',
            }"
            :title="e.status === 'folded' ? '评论被折叠（仍在显但被降权）' : '评论被删除'"
          >{{ e.status === 'folded' ? '↓' : '-' }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
