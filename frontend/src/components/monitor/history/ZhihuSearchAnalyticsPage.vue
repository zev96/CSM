<script setup lang="ts">
/**
 * 知乎搜索分析页 —— 历史报告 tab 的「知乎搜索」子页。
 * 数据从 GET /api/monitor/history/zhihu-search?range=1d|7d|30d。
 * drill-down 行点击 emit('navigate', {taskId})。
 */
import { ref, computed, onMounted, watch } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import LineChart from "./LineChart.vue";

type Range = "1d" | "7d" | "30d";
type ChangeKind = "down" | "up" | "new" | "dropped" | "flat";
// Filter 按用户要求收窄到 3 项 —— 新上榜 / 掉出 Top 两个分类视图下线，
// 用户认为太碎；up/down 已经覆盖核心异动场景。
type Filter = "all" | "down" | "up";

interface Kpis {
  monitored_keywords: number;
  brands_covered: number;
  avg_match_rate_today: number;
  avg_match_rate_prev: number;
  hit_count_total: number;
  topn_total: number;
  changed_keywords: number;
  changed_up: number;
  changed_down: number;
}
interface DailyPoint {
  date: string;
  avg_match_rate: number;
  changed_count: number;
  changed_up: number;
  changed_down: number;
}
interface KeywordRow {
  task_id: number;
  task_name: string;
  search_keyword: string;
  target_brand: string;
  matched_count: number;
  matched_count_prev: number | null;
  top_n: number;
  matched_ranks: number[];
  best_rank: number;
  best_rank_prev: number | null;
  change_kind: ChangeKind;
  checked_at: string | null;
}
interface ZhihuSearchResponse {
  range: Range;
  kpis: Kpis;
  daily_series: DailyPoint[];
  keywords: KeywordRow[];
}

const emit = defineEmits<{ navigate: [payload: { taskId: number }] }>();

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();
const range = ref<Range>("7d");
const data = ref<ZhihuSearchResponse | null>(null);
const loading = ref(false);
const filter = ref<Filter>("all");

async function load() {
  loading.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/zhihu-search", {
      params: { range: range.value },
    });
    data.value = r.data;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const filtered = computed<KeywordRow[]>(() => {
  if (!data.value) return [];
  if (filter.value === "all") return data.value.keywords;
  return data.value.keywords.filter((q) => q.change_kind === filter.value);
});

const chartLabels = computed(() =>
  (data.value?.daily_series ?? []).map((d) => d.date.slice(5)),
);
const chartSeries = computed(() => {
  if (!data.value) return [];
  return [
    { label: "占有率 %", color: "#ee6a2a", data: data.value.daily_series.map((d) => Math.round(d.avg_match_rate * 100)) },
    { label: "异动关键词数", color: "var(--ink)", data: data.value.daily_series.map((d) => d.changed_count) },
  ];
});

function fmtPct(x: number): string { return `${Math.round(x * 100)}%`; }
function fmtDeltaPts(curr: number, prev: number) {
  const diff = Math.round((curr - prev) * 100);
  if (diff > 0) return { text: `↑ ${diff} pts`, tone: "up" as const };
  if (diff < 0) return { text: `↓ ${Math.abs(diff)} pts`, tone: "down" as const };
  return { text: "持平", tone: "flat" as const };
}
// fmtTime / arrowFor 已下线 —— 关键词列表行 column 重构后不再显示检查时间，
// 也不再用左侧三角箭头标记 change_kind（状态列箭头已覆盖语义）。
function rankChangeText(q: KeywordRow): { text: string; tone: "up" | "down" | "flat" } {
  if (q.change_kind === "dropped") return { text: `#${q.best_rank_prev} → 无`, tone: "down" };
  if (q.change_kind === "new") return { text: `无 → #${q.best_rank}`, tone: "up" };
  if (q.best_rank_prev == null) return { text: "首次", tone: "flat" };
  if (q.best_rank === q.best_rank_prev) return { text: `#${q.best_rank} 持平`, tone: "flat" };
  const tone = q.best_rank < q.best_rank_prev ? "up" : "down";
  return { text: `#${q.best_rank_prev} → #${q.best_rank}`, tone };
}
</script>

<template>
  <div v-if="loading && !data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">加载中…</div>
  <div v-else-if="!data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">暂无数据</div>
  <!--
    h-full + min-h-0 + flex-col 让 KPI/图表保持固定，「关键词列表」块
    单独 flex-1 内部滚动。父 wrapper 是 overflow-hidden，不会再串到
    整个历史报告页面。
  -->
  <div v-else class="flex h-full min-h-0 flex-col gap-3">
    <!-- range picker -->
    <div class="flex items-center justify-end flex-shrink-0">
      <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card)', border: '1px solid var(--line)' }">
        <button
          v-for="r in (['1d','7d','30d'] as Range[])" :key="r"
          @click="range = r"
          class="px-3.5 py-1 rounded-full text-[12px] font-medium"
          :style="{
            background: range === r ? 'var(--dark)' : 'transparent',
            color: range === r ? 'var(--card)' : 'var(--ink-3)',
          }"
        >{{ r === "1d" ? "最近 1 天" : r === "7d" ? "最近 7 天" : "最近 30 天" }}</button>
      </div>
    </div>

    <!-- 3 KPI —— 固定，不滚 -->
    <div class="grid grid-cols-3 gap-2.5 flex-shrink-0">
      <!-- KPI 1: 监测关键词数 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">监测关键词数</div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.monitored_keywords }}</div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          覆盖品牌词 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.brands_covered }}</b> 个
        </div>
      </div>
      <!-- KPI 2: 平均命中率 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="flex justify-between items-start">
          <div class="flex items-center gap-1.5 text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">
            <span :style="{ width: '8px', height: '8px', borderRadius: '50%', background: '#ee6a2a' }" />
            品牌占有率
          </div>
          <span
            class="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            :style="{
              background: fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'down' ? 'rgba(216,90,72,0.12)' :
                          fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'up'   ? 'rgba(122,155,94,0.15)' : 'rgba(var(--ink-rgb),0.05)',
              color: fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'down' ? 'var(--red)' :
                     fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'up'   ? '#5e7848' : 'var(--ink-3)',
            }"
          >{{ fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).text }}</span>
        </div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ fmtPct(data.kpis.avg_match_rate_today) }}</div>
        <!-- Sparkline 按用户要求移除 —— 切 range 时直接换数字即可，
             不再画 7d/30d 的趋势小曲线（主图区已有大图覆盖趋势）。 -->
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          卡位 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.hit_count_total }}</b> / {{ data.kpis.topn_total }}
        </div>
      </div>
      <!-- KPI 3: 异动关键词 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">异动关键词</div>
        <div class="flex items-baseline gap-2">
          <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.changed_keywords }}</div>
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
            <span :style="{ color: 'var(--red)' }">↓ {{ data.kpis.changed_down }}</span>
            <span class="mx-1">·</span>
            <span :style="{ color: '#5e7848' }">↑ {{ data.kpis.changed_up }}</span>
          </div>
        </div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">近 {{ range === "1d" ? "1 天" : range === "7d" ? "7 天" : "30 天" }}累计</div>
      </div>
    </div>

    <!-- 主图（1d 时隐藏）—— 固定，不滚 -->
    <div
      v-if="range !== '1d'"
      class="flex-shrink-0"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
    >
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">占有率与异动趋势</div>
        <div class="flex gap-3 text-[11px]" :style="{ color: 'var(--ink-2)' }">
          <span><span :style="{ display:'inline-block', width:'8px', height:'8px', background:'#ee6a2a', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />占有率 %</span>
          <span><span :style="{ display:'inline-block', width:'8px', height:'8px', background:'var(--ink)', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />异动关键词数</span>
        </div>
      </div>
      <LineChart :labels="chartLabels" :series="chartSeries" dual-axis />
    </div>

    <!--
      关键词列表 —— 占满剩余高度，header (过滤器 + 计数) 固定，行列表
      内部滚动。这样关键词再多滚动条也只出现在这块卡内，不会污染上面
      KPI / 图表。
    -->
    <div
      class="flex min-h-0 flex-1 flex-col"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '12px' }"
    >
      <div class="flex justify-between items-center mb-2 flex-shrink-0">
        <!-- 「(N 条 · 点行进详情)」副标按用户要求移除 -->
        <div class="text-[12.5px] font-semibold">
          关键词列表
        </div>
        <!-- 过滤 pivot 收窄到 3 项：全部 / 下降 / 上升 -->
        <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)' }">
          <button
            v-for="f in (['all','down','up'] as Filter[])" :key="f"
            @click="filter = f"
            class="px-3 py-1 rounded-full text-[11.5px] font-medium"
            :style="{
              background: filter === f ? 'var(--dark)' : 'transparent',
              color: filter === f ? 'var(--card)' : 'var(--ink-3)',
            }"
          >
            {{ f === "all" ? "全部" : f === "down" ? "↓ 下降" : "↑ 上升" }}
          </button>
        </div>
      </div>
      <!--
        表格：固定 header 行 + 滚动 body。grid 模板拆 4 列：
          关键词 / 命中数 / 排名 / 状态
        每列宽度比例固定，header 和 body 共享同一个 gridTemplateColumns
        保证对齐。
      -->
      <div
        class="grid items-center gap-2.5 flex-shrink-0 text-[11px] uppercase"
        :style="{
          gridTemplateColumns: '1.6fr 80px 80px 60px',
          padding: '8px 12px',
          letterSpacing: '1px',
          color: 'var(--ink-3)',
          borderBottom: '1px solid var(--line)',
        }"
      >
        <div>关键词</div>
        <div class="text-center">卡位</div>
        <div class="text-center">排名</div>
        <div class="text-center">状态</div>
      </div>
      <div v-if="!filtered.length" class="py-6 text-center text-[12px] flex-shrink-0" :style="{ color: 'var(--ink-3)' }">无符合条件的关键词</div>
      <div v-else class="flex-1 min-h-0 overflow-y-auto">
        <div
          v-for="q in filtered" :key="`${q.task_id}-${q.search_keyword}`"
          @click="emit('navigate', { taskId: q.task_id })"
          class="grid items-center gap-2.5 cursor-pointer"
          :style="{
            gridTemplateColumns: '1.6fr 80px 80px 60px',
            padding: '11px 12px',
            fontSize: '12px',
            borderRadius: '8px',
            borderTop: '1px solid rgba(var(--ink-rgb),0.06)',
          }"
          @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
          @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <!-- 关键词 —— truncate 防止挤压其他列 -->
          <div :style="{ color: 'var(--ink)' }" class="truncate" :title="q.search_keyword">{{ q.search_keyword }}</div>
          <!-- 命中数：matched_count，0 显示「无」-->
          <div class="text-center font-semibold">
            <template v-if="q.matched_count > 0">{{ q.matched_count }}</template>
            <span v-else :style="{ color: 'var(--ink-3)', fontWeight: 'normal' }">无</span>
          </div>
          <!-- 排名：best_rank（最高排名），未命中显示「无」-->
          <div class="text-center font-semibold">
            <template v-if="q.best_rank > 0">#{{ q.best_rank }}</template>
            <span v-else :style="{ color: 'var(--ink-3)', fontWeight: 'normal' }">无</span>
          </div>
          <!-- 状态：上下箭头（up 绿 / down 橙 / 其他黑 -） -->
          <div class="text-center font-bold text-[14px]"
            :style="{
              color: rankChangeText(q).tone === 'up' ? '#5e7848'
                : rankChangeText(q).tone === 'down' ? 'var(--primary, #ee6a2a)'
                : 'var(--ink, #1c1a17)',
            }"
            :title="rankChangeText(q).text"
          >{{ rankChangeText(q).tone === 'up' ? '↑' : rankChangeText(q).tone === 'down' ? '↓' : '-' }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
