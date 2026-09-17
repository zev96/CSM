<script setup lang="ts">
/**
 * 百度 SEO 历史页 —— 历史报告 tab 的「百度关键词」子页。
 * 数据从 GET /api/monitor/history/baidu-keyword?range=1d|7d|30d。
 * drill-down 行点击 emit('navigate', {taskId})。
 */
import { ref, computed, onMounted, watch } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import LineChart from "./LineChart.vue";

type Range = "1d" | "7d" | "30d";
type ChangeKind = "down" | "up" | "new" | "dropped" | "flat";
// Filter 按用户要求收窄到 3 项（全部/下降/上升），原先 4 项太碎。
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
  captcha_count: number;
  news_present_count: number;
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
  /** 默认 SERP 命中条数（百度普通搜索结果命中目标品牌的条数） */
  matched_count: number;
  matched_count_prev: number | null;
  /** 资讯 SERP 命中条数（百度资讯/新闻区命中目标品牌的条数）—— 后端
   *  history_service.py 新加的字段，沿用 default_results 同样的
   *  matches_brand sum 逻辑。 */
  news_matched_count: number;
  top_n: number;
  matched_ranks: number[];
  best_rank: number;
  best_rank_prev: number | null;
  change_kind: ChangeKind;
  checked_at: string | null;
}
interface BaiduResponse {
  range: Range;
  kpis: Kpis;
  daily_series: DailyPoint[];
  keywords: KeywordRow[];
}

const emit = defineEmits<{ navigate: [payload: { taskId: number }] }>();

const sidecar = useSidecar();
const { whenReady } = useSidecarReady();
const range = ref<Range>("7d");
const data = ref<BaiduResponse | null>(null);
const loading = ref(false);
const filter = ref<Filter>("all");

async function load() {
  loading.value = true;
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/baidu-keyword", {
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
  return data.value.keywords.filter((k) => k.change_kind === filter.value);
});

const chartLabels = computed(() =>
  (data.value?.daily_series ?? []).map((d) => d.date.slice(5)),
);
const chartSeries = computed(() => {
  if (!data.value) return [];
  // 按用户要求把"命中率"折线从蓝色 #2563eb 改成应用主色调橙色 #ee6a2a。
  // "异动关键词数" 走 var(--ink) 让暗色主题自动反色。
  return [
    { label: "命中率 %", color: "#ee6a2a", data: data.value.daily_series.map((d) => Math.round(d.avg_match_rate * 100)) },
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
// fmtTime / arrowFor 已下线 —— 关键词列表 column 重构后不再显示检查时间，
// 也不再用左侧三角箭头标记 change_kind（状态列箭头已覆盖语义）。
function rankChangeText(k: KeywordRow): { text: string; tone: "up" | "down" | "flat" } {
  if (k.change_kind === "dropped") return { text: `#${k.best_rank_prev} → 无`, tone: "down" };
  if (k.change_kind === "new") return { text: `无 → #${k.best_rank}`, tone: "up" };
  if (k.best_rank_prev == null) return { text: "首次", tone: "flat" };
  if (k.best_rank < 0) return { text: "未命中", tone: "flat" };
  if (k.best_rank === k.best_rank_prev) return { text: `#${k.best_rank} 持平`, tone: "flat" };
  const tone = k.best_rank < k.best_rank_prev ? "up" : "down";
  return { text: `#${k.best_rank_prev} → #${k.best_rank}`, tone };
}
</script>

<template>
  <div v-if="loading && !data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">加载中…</div>
  <div v-else-if="!data" class="py-10 text-center" :style="{ color: 'var(--ink-3)', fontSize: '12px' }">暂无数据</div>
  <!-- 跟 ZhihuRankingPage 同模式：h-full + min-h-0 + flex-col，让
       关键词列表块内部滚动，KPI / 主图 / range picker 固定。 -->
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

    <!-- 3 KPI cards —— 固定 -->
    <div class="grid grid-cols-3 gap-2.5 flex-shrink-0">
      <!-- KPI 1: 监测关键词数 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">监测关键词数</div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.monitored_keywords }}</div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          覆盖品牌词 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.brands_covered }}</b> 个
        </div>
      </div>
      <!-- KPI 2: 命中率均值 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="flex justify-between items-start">
          <div class="flex items-center gap-1.5 text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">
            <span :style="{ width: '8px', height: '8px', borderRadius: '50%', background: '#ee6a2a' }" />
            命中率（平均）
          </div>
          <span
            class="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            :style="{
              background: fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'down' ? 'rgba(216,90,72,0.12)' :
                          fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'up'   ? 'rgba(122,155,94,0.15)' : 'rgba(var(--ink-rgb),0.05)',
              color: fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'down' ? 'var(--red)' :
                     fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).tone === 'up'   ? 'var(--green-deep)' : 'var(--ink-3)',
            }"
          >{{ fmtDeltaPts(data.kpis.avg_match_rate_today, data.kpis.avg_match_rate_prev).text }}</span>
        </div>
        <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ fmtPct(data.kpis.avg_match_rate_today) }}</div>
        <!-- Sparkline 按用户要求移除（切 range 直接换数字，主图区已覆盖趋势）-->
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          命中位 <b :style="{ color: 'var(--ink)' }">{{ data.kpis.hit_count_total }}</b> / {{ data.kpis.topn_total }}
        </div>
      </div>
      <!-- KPI 3: 排名异动关键词 -->
      <div :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }" class="flex flex-col gap-1.5">
        <div class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">排名异动关键词</div>
        <div class="flex items-baseline gap-2">
          <div class="font-display font-bold" :style="{ fontSize: '28px', lineHeight: 1 }">{{ data.kpis.changed_keywords }}</div>
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
            <span :style="{ color: 'var(--red)' }">↓ {{ data.kpis.changed_down }}</span>
            <span class="mx-1">·</span>
            <span :style="{ color: 'var(--green-deep)' }">↑ {{ data.kpis.changed_up }}</span>
          </div>
        </div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
          近 {{ range === "1d" ? "1 天" : range === "7d" ? "7 天" : "30 天" }}累计
          <template v-if="data.kpis.captcha_count > 0">
            <span class="ml-1" :style="{ color: 'var(--yellow-deep)' }">· 验证码 {{ data.kpis.captcha_count }}</span>
          </template>
        </div>
      </div>
    </div>

    <!-- 主图（1d 时隐藏）—— 固定 -->
    <div
      v-if="range !== '1d'"
      class="flex-shrink-0"
      :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-inner)', padding: '14px' }"
    >
      <div class="flex justify-between items-center mb-2">
        <div class="text-[12.5px] font-semibold">命中率与异动趋势</div>
        <!-- 图例小点：命中率改为主色调橙色（#ee6a2a），跟折线一致 -->
        <div class="flex gap-3 text-[11px]" :style="{ color: 'var(--ink-2)' }">
          <span><span :style="{ display:'inline-block', width:'8px', height:'8px', background:'#ee6a2a', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />命中率 %</span>
          <span><span :style="{ display:'inline-block', width:'8px', height:'8px', background:'var(--ink)', borderRadius:'50%', marginRight:'5px', verticalAlign:'middle' }" />异动关键词数</span>
        </div>
      </div>
      <LineChart :labels="chartLabels" :series="chartSeries" dual-axis />
    </div>

    <!--
      关键词列表 —— 占满剩余高度，header 固定，行列表内部滚动。
      跟 ZhihuRankingPage 的问题列表同模式。
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
        <!-- Filter pivot 收窄到 3 项：全部 / 下降 / 上升 -->
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
        表格：固定 header 行 + 滚动 body。
          关键词 / 默认卡位 / 资讯卡位 / 状态
        默认卡位 = matched_count（百度默认 SERP 命中）；
        资讯卡位 = news_matched_count（百度新闻区命中）；
        都没命中显示「无」；状态走 rankChangeText.tone → 箭头。
      -->
      <div
        class="grid items-center gap-2.5 flex-shrink-0 text-[11px] uppercase"
        :style="{
          gridTemplateColumns: '1.8fr 80px 80px 60px',
          padding: '8px 12px',
          letterSpacing: '1px',
          color: 'var(--ink-3)',
          borderBottom: '1px solid var(--line)',
        }"
      >
        <div>关键词</div>
        <div class="text-center">默认卡位</div>
        <div class="text-center">资讯卡位</div>
        <div class="text-center">状态</div>
      </div>
      <div v-if="!filtered.length" class="py-6 text-center text-[12px] flex-shrink-0" :style="{ color: 'var(--ink-3)' }">无符合条件的关键词</div>
      <div v-else class="flex-1 min-h-0 overflow-y-auto">
        <div
          v-for="k in filtered" :key="k.task_id"
          @click="emit('navigate', { taskId: k.task_id })"
          class="grid items-center gap-2.5 cursor-pointer"
          :style="{
            gridTemplateColumns: '1.8fr 80px 80px 60px',
            padding: '11px 12px',
            fontSize: '12px',
            borderRadius: '8px',
            borderTop: '1px solid rgba(var(--ink-rgb),0.06)',
          }"
          @mouseenter="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
          @mouseleave="(ev) => ((ev.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <div :style="{ color: 'var(--ink)' }" class="truncate" :title="k.search_keyword">{{ k.search_keyword }}</div>
          <div class="text-center font-semibold">
            <template v-if="k.matched_count > 0">{{ k.matched_count }}</template>
            <span v-else :style="{ color: 'var(--ink-3)', fontWeight: 'normal' }">无</span>
          </div>
          <div class="text-center font-semibold">
            <template v-if="k.news_matched_count > 0">{{ k.news_matched_count }}</template>
            <span v-else :style="{ color: 'var(--ink-3)', fontWeight: 'normal' }">无</span>
          </div>
          <div class="text-center font-bold text-[14px]"
            :style="{
              color: rankChangeText(k).tone === 'up' ? 'var(--green-deep)'
                : rankChangeText(k).tone === 'down' ? 'var(--primary, #ee6a2a)'
                : 'var(--ink, #1c1a17)',
            }"
            :title="rankChangeText(k).text"
          >{{ rankChangeText(k).tone === 'up' ? '↑' : rankChangeText(k).tone === 'down' ? '↓' : '-' }}</div>
          <!-- 末列 › chevron 已移除 —— 行整体可点跳 detail，箭头是冗余装饰 -->
        </div>
      </div>
    </div>
  </div>
</template>
