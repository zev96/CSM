<script setup lang="ts">
/**
 * 知乎排名页 —— 历史报告 tab 的「知乎排名」子页。
 * 数据从 GET /api/monitor/history/zhihu-ranking?range=1d|7d|30d。
 * drill-down 行点击 emit('navigate', {taskId})。
 */
import { ref, computed, onMounted, watch } from "vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import LineChart from "./LineChart.vue";

type Range = "1d" | "7d" | "30d";
type ChangeKind = "down" | "up" | "new" | "dropped" | "flat";
type Filter = "all" | "down" | "up" | "new" | "dropped";

interface Kpis {
  monitored_questions: number;
  questions_added_this_week: number;
  brands_covered: number;
  avg_share_today: number;
  avg_share_prev: number;
  hit_count_total: number;
  topn_total: number;
  changed_questions: number;
  changed_up: number;
  changed_down: number;
}
interface DailyPoint {
  date: string;
  avg_share: number;
  changed_count: number;
  changed_up: number;
  changed_down: number;
}
interface Question {
  task_id: number;
  title: string;
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
interface ZhihuResponse {
  range: Range;
  kpis: Kpis;
  daily_series: DailyPoint[];
  questions: Question[];
}

const emit = defineEmits<{ navigate: [payload: { taskId: number }] }>();

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();
const range = ref<Range>("7d");
const data = ref<ZhihuResponse | null>(null);
const loading = ref(false);
const filter = ref<Filter>("all");

async function load() {
  loading.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/zhihu-ranking", {
      params: { range: range.value },
    });
    data.value = r.data;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const filtered = computed<Question[]>(() => {
  if (!data.value) return [];
  if (filter.value === "all") return data.value.questions;
  return data.value.questions.filter((q) => q.change_kind === filter.value);
});

const chartLabels = computed(() =>
  (data.value?.daily_series ?? []).map((d) => d.date.slice(5)),
);
const chartSeries = computed(() => {
  if (!data.value) return [];
  return [
    { label: "占有率 %", color: "#ee6a2a", data: data.value.daily_series.map((d) => Math.round(d.avg_share * 100)) },
    { label: "异动问题数", color: "#1e1c19", data: data.value.daily_series.map((d) => d.changed_count) },
  ];
});

function fmtPct(x: number): string { return `${Math.round(x * 100)}%`; }
function fmtDeltaPts(curr: number, prev: number) {
  const diff = Math.round((curr - prev) * 100);
  if (diff > 0) return { text: `↑ ${diff} pts`, tone: "up" as const };
  if (diff < 0) return { text: `↓ ${Math.abs(diff)} pts`, tone: "down" as const };
  return { text: "持平", tone: "flat" as const };
}
function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function arrowFor(kind: ChangeKind): { glyph: string; color: string } {
  if (kind === "up" || kind === "new") return { glyph: "▲", color: "#5e7848" };
  if (kind === "down" || kind === "dropped") return { glyph: "▼", color: "var(--red)" };
  return { glyph: "—", color: "#a89f8d" };
}
function rankChangeText(q: Question): { text: string; tone: "up" | "down" | "flat" } {
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
    h-full + min-h-0 + flex-col 让 KPI/图表保持固定，「问题列表」块
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
      <!-- KPI 1: 监测问题数 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">监测问题数</div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.monitored_questions }}</div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          覆盖品牌词 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.brands_covered }}</b> 个
        </div>
      </div>
      <!-- KPI 2: 品牌占有率均值 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="flex justify-between items-start">
          <div class="flex items-center gap-1.5 text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">
            <span :style="{ width: '8px', height: '8px', borderRadius: '50%', background: '#ee6a2a' }" />
            品牌占有率（平均）
          </div>
          <span
            class="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            :style="{
              background: fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'down' ? 'rgba(216,90,72,0.12)' :
                          fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'up'   ? 'rgba(122,155,94,0.15)' : 'rgba(28,26,23,0.05)',
              color: fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'down' ? 'var(--red)' :
                     fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).tone === 'up'   ? '#5e7848' : 'var(--ink-3)',
            }"
          >{{ fmtDeltaPts(data.kpis.avg_share_today, data.kpis.avg_share_prev).text }}</span>
        </div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ fmtPct(data.kpis.avg_share_today) }}</div>
        <!-- Sparkline 真实 props 是 :points + :stroke + :height -->
        <Sparkline
          v-if="range !== '1d' && data.daily_series.length > 0"
          :points="data.daily_series.map((d) => d.avg_share * 100)"
          stroke="#ee6a2a"
          :height="28"
        />
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          命中位 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.hit_count_total }}</b> / {{ data.kpis.topn_total }}
        </div>
      </div>
      <!-- KPI 3: 异动问题数 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">排名异动问题</div>
        <div class="flex items-baseline gap-2">
          <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.changed_questions }}</div>
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
          <span><span :style="{ display:'inline-block', width:'8px', height:'8px', background:'#1e1c19', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />异动问题数</span>
        </div>
      </div>
      <LineChart :labels="chartLabels" :series="chartSeries" dual-axis />
    </div>

    <!--
      问题列表 —— 占满剩余高度，header (过滤器 + 计数) 固定，行列表
      内部滚动。这样问题再多滚动条也只出现在这块卡内，不会污染上面
      KPI / 图表。
    -->
    <div
      class="flex min-h-0 flex-1 flex-col"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '12px' }"
    >
      <div class="flex justify-between items-center mb-2 flex-shrink-0">
        <div class="text-[12.5px] font-semibold">
          问题列表 <span class="font-normal" :style="{ color: 'var(--ink-3)' }">({{ filtered.length }} 条 · 点行进详情)</span>
        </div>
        <div class="inline-flex gap-1 p-1 rounded-full" :style="{ background: 'var(--card-2)' }">
          <button
            v-for="f in (['all','down','up','new','dropped'] as Filter[])" :key="f"
            @click="filter = f"
            class="px-3 py-1 rounded-full text-[11.5px] font-medium"
            :style="{
              background: filter === f ? 'var(--dark)' : 'transparent',
              color: filter === f ? 'var(--card)' : 'var(--ink-3)',
            }"
          >
            {{ f === "all" ? "全部" : f === "down" ? "↓ 下降" : f === "up" ? "↑ 上升" : f === "new" ? "新上榜" : "掉出 Top" }}
          </button>
        </div>
      </div>
      <div v-if="!filtered.length" class="py-6 text-center text-[12px] flex-shrink-0" :style="{ color: 'var(--ink-3)' }">无符合条件的问题</div>
      <div v-else class="flex-1 min-h-0 overflow-y-auto">
        <div
          v-for="q in filtered" :key="q.task_id"
          @click="emit('navigate', { taskId: q.task_id })"
          class="grid items-center gap-2.5 cursor-pointer"
          :style="{
            gridTemplateColumns: '24px 1.6fr 100px 110px 80px 18px',
            padding: '9px 12px',
            fontSize: '11.5px',
            borderRadius: '8px',
            borderTop: '1px solid rgba(28,26,23,0.06)',
          }"
          @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
          @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <div class="text-[14px] text-center" :style="{ color: arrowFor(q.change_kind).color }">{{ arrowFor(q.change_kind).glyph }}</div>
          <div>
            <div :style="{ color: 'var(--ink)' }">{{ q.title }}</div>
            <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
              target:
              <span class="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10.5px]"
                :style="{ background: 'rgba(238,106,42,0.12)', color: '#c9521f' }">{{ q.target_brand }}</span>
              <span v-if="q.matched_ranks.length"> · 命中位 {{ q.matched_ranks.map((r) => "#" + r).join(" ") }} ({{ q.matched_count }}/{{ q.top_n }})</span>
            </div>
          </div>
          <div>
            <div class="text-[12px] font-semibold">{{ q.matched_count }} / {{ q.top_n }}</div>
            <div :style="{ height: '6px', background: 'rgba(28,26,23,0.06)', borderRadius: '3px', overflow: 'hidden', marginTop: '4px' }">
              <div :style="{ height: '100%', background: '#ee6a2a', borderRadius: '3px', width: `${Math.min(100, (q.matched_count / q.top_n) * 100)}%` }" />
            </div>
          </div>
          <div>
            <span
              class="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium"
              :style="{
                background: rankChangeText(q).tone === 'up' ? 'rgba(122,155,94,0.15)' :
                            rankChangeText(q).tone === 'down' ? 'rgba(216,90,72,0.12)' : 'rgba(28,26,23,0.05)',
                color: rankChangeText(q).tone === 'up' ? '#5e7848' :
                       rankChangeText(q).tone === 'down' ? 'var(--red)' : 'var(--ink-3)',
              }"
            >{{ rankChangeText(q).text }}</span>
          </div>
          <div :style="{ color: 'var(--ink-3)' }">{{ fmtTime(q.checked_at) }}</div>
          <div class="text-[16px] text-center" :style="{ color: 'var(--ink-4)', lineHeight: 1 }">›</div>
        </div>
      </div>
    </div>
  </div>
</template>
