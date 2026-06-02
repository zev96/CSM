<script setup lang="ts">
/**
 * GEO「选中关键词」三页签详情 —— 移植 design full-app.jsx 的右栏详情主体。
 * 概览 / 平台对比 / 竞争·信源 三个页签，独立滚动内容区。详情头(品牌·关键词·
 * 评级胶囊·副标·运行按钮) + 页签条 + 内容区。数据由父组件装配好的 `detail`
 * 传入（见 geoDetail.useGeoKeywordDetail）；本组件只负责布局/页签/散点取点。
 *
 * - 概览: BHero(GeoHero) → PlatformStrip(GeoPlatformStrip) → BTrend(GeoTrend)
 *         → HighlightTeasers(GeoHighlightTeasers)。内部跳转切页签。
 * - 平台对比: masonry 两列 PlatformBlock(GeoPlatformBlock)。
 * - 竞争·信源: BScatter(竞品) + RankHeatmap ; BScatter(信源) + SourceList。
 *
 * 配色/字号/间距/圆角严格照 README §页签 A/B/C。
 */
import { computed, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";
import GeoHero from "@/components/monitor/geo/GeoHero.vue";
import GeoPlatformStrip from "@/components/monitor/geo/GeoPlatformStrip.vue";
import GeoHighlightTeasers from "@/components/monitor/geo/GeoHighlightTeasers.vue";
import GeoPlatformBlock from "@/components/monitor/geo/GeoPlatformBlock.vue";
import GeoRankHeatmap from "@/components/monitor/geo/GeoRankHeatmap.vue";
import GeoSourceList from "@/components/monitor/geo/GeoSourceList.vue";
import GeoLegendDot from "@/components/monitor/geo/GeoLegendDot.vue";
import GeoTrend from "@/components/monitor/geo/charts/GeoTrend.vue";
import GeoScatter from "@/components/monitor/geo/charts/GeoScatter.vue";

import {
  bandColor,
  bandLabel,
  fmtDateTime,
  isFailed,
  targetAppears,
  targetAvgRank,
  platformShort,
  SRC_COLORS,
  COMPETITOR_BLUE,
  type KeywordDetail,
} from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  detail: KeywordDetail | null;
  loading: boolean;
  brand: string;
  brandTerms: string[];
  keyword: string;
  platformCount: number;
  running: boolean;
  taskId: number;
}>();
const emit = defineEmits<{
  (e: "run"): void;
  (e: "cancel"): void;
  (e: "edit"): void;
  (e: "delete"): void;
}>();

type Tab = "overview" | "matrix" | "compete";
const tab = ref<Tab>("overview");
const tabs: Array<{ k: Tab; t: string }> = [
  { k: "overview", t: "概览" },
  { k: "matrix", t: "平台对比" },
  { k: "compete", t: "竞争 · 信源" },
];

// 切关键词回到概览页签（跟 design 默认态一致）。
watch(
  () => props.keyword,
  () => {
    tab.value = "overview";
  },
);

const metric = computed(() => props.detail?.metric ?? null);
// 真实采集到的平台（metric / 竞品 / 散点 / 结论派生用）。
const platforms = computed(() => props.detail?.platforms ?? []);
// 展示用平台列表（含未跑占位卡）——各平台卡 / 平台对比卡片 / 热力矩阵列用。
// detail 不带 displayPlatforms（旧数据/未装配）时回退真实 platforms。
const displayPlatforms = computed(
  () => props.detail?.displayPlatforms ?? props.detail?.platforms ?? [],
);
const competitors = computed(() => props.detail?.competitors ?? []);
const board = computed(() => props.detail?.board ?? []);
const displayBrand = computed(
  () => props.brandTerms.find((t) => t && t.trim()) ?? props.brand ?? "",
);

// 评级胶囊（详情头）：弱曝光 60。颜色随档位。
const bandPillLabel = computed(() => bandLabel(metric.value?.status_band));
const bandPillScore = computed(() => Math.round((metric.value?.soc ?? 0) * 100));
const bandPillColor = computed(() => bandColor(metric.value?.status_band));

// 副标：N 个 AI 平台 · 最近运行 M/D HH:MM。
const subline = computed(() => {
  const n = props.platformCount || platforms.value.length;
  const run = fmtDateTime(props.detail?.lastRunIso);
  return `${n} 个 AI 平台 · 最近运行 ${run}`;
});

// ── 竞争·信源：散点取点 ───────────────────────────────────────────────
// 竞品散点：X=出现平台数/5, Y=(5-平均位次)/4（顶部#1 底部#5）。"榜首"(avgRank
// 最小)=蓝环；你=橙环。其他=灰无环。分母用平台数（>0），保证窄/宽都铺得开。
const denom = computed(() => Math.max(1, props.platformCount || platforms.value.length || 5));
const headName = computed(() => props.detail?.headCompetitor ?? "");

const compPoints = computed(() => {
  const pts = competitors.value.map((c) => {
    const isFirst = c.name === headName.value;
    return {
      nx: Math.min(1, c.appears / denom.value),
      ny: Math.max(0, Math.min(1, (5 - (c.avgRank || 5)) / 4)),
      r: isFirst ? 9 : 6.5,
      fill: isFirst ? COMPETITOR_BLUE : "var(--ink-4)",
      ring: isFirst,
    };
  });
  // 你（target）：X=提及平台数/denom, Y=(5-你的均位)/4，橙环。
  const youAppears = targetAppears(platforms.value);
  const youRank = targetAvgRank(platforms.value);
  pts.push({
    nx: Math.min(1, youAppears / denom.value),
    ny: Math.max(0, Math.min(1, (5 - youRank) / 4)),
    r: 9,
    fill: "var(--primary)",
    ring: true,
  });
  return pts;
});

// 信源散点：X=引用次数/max, Y=平台引用率(覆盖平台/denom)。每个信源专属色。
const srcMax = computed(() => Math.max(1, ...board.value.map((b) => b.count)));
const srcPoints = computed(() =>
  board.value.map((b, i) => ({
    nx: Math.min(1, b.count / srcMax.value),
    ny: Math.max(0, Math.min(1, b.platforms / denom.value)),
    r: 6.5,
    fill: SRC_COLORS[i % SRC_COLORS.length],
  })),
);

// 竞争结论文案（热力矩阵下方）：派生「{头号对手} 在 K 个平台排第 1；你在 X 夺冠，
// Y 未上榜。」缺数据时降级。
const competeConclusion = computed(() => {
  const head = headName.value;
  if (!head || competitors.value.length === 0) {
    return "暂无足够竞品数据 · 多平台采集后这里给出竞品压制格局。";
  }
  // 头号对手排第 1 的平台数。
  let headFirst = 0;
  for (const p of platforms.value) {
    const it = p.recommended.find((r) => r.name === head);
    if (it && it.position === 1) headFirst++;
  }
  const youFirst = platforms.value
    .filter((p) => !isFailed(p) && p.mentioned && p.rank === 1)
    .map((p) => platformShort(p.id));
  const youMissing = platforms.value
    .filter((p) => !isFailed(p) && !p.mentioned)
    .map((p) => platformShort(p.id));
  const youPart = youFirst.length
    ? `你在 ${youFirst.join("、")} 夺冠`
    : "你尚未在任何平台夺冠";
  const missPart = youMissing.length ? `，${youMissing.join(" / ")} 未上榜` : "";
  const headPart = headFirst ? `在 ${headFirst} 个平台排第 1` : "出现在多个平台";
  return `${head} ${headPart}；${youPart}${missPart}。`;
});

// matrix 总平台数（信源平台引用率分母）。
const matrixDenom = denom;
</script>

<template>
  <div
    class="flex h-full min-h-0 flex-col overflow-hidden"
    :style="{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-card)' }"
  >
    <!-- ════ 详情头 ════ -->
    <div
      class="flex flex-shrink-0 items-start justify-between"
      :style="{ gap: '12px', padding: '18px 22px 14px' }"
    >
      <div :style="{ minWidth: 0 }">
        <div class="flex items-center" :style="{ gap: '9px' }">
          <div class="font-display" :style="{ fontSize: '17px', fontWeight: 700 }">
            {{ displayBrand }}
            <span :style="{ color: 'var(--ink-3)', fontWeight: 500 }">· {{ keyword }}</span>
          </div>
          <span
            v-if="metric"
            :style="{ fontSize: '11px', fontWeight: 700, color: bandPillColor, background: 'var(--primary-soft)', borderRadius: '999px', padding: '2px 9px', fontVariantNumeric: 'tabular-nums' }"
          >{{ bandPillLabel }} {{ bandPillScore }}</span>
        </div>
        <div :style="{ fontSize: '11.5px', color: 'var(--ink-3)', marginTop: '3px' }">{{ subline }}</div>
      </div>
      <!-- 右上：运行/停止（主）+ 编辑/删除（次，圆形图标钮）。运行按钮 = 设计稿
           详情头 CTA；编辑/删除沿用旧 L2 头的次级动作，避免左列表为贴合设计稿的
           极简行（仅名+计数+药丸）而丢失任务管理入口。-->
      <div class="flex flex-shrink-0 items-center" :style="{ gap: '8px' }">
        <button
          v-if="!running"
          type="button"
          class="inline-flex items-center"
          :style="{ gap: '5px', padding: '7px 15px', fontSize: '12px', fontWeight: 600, color: '#fff', background: 'var(--primary)', border: 'none', borderRadius: '999px', cursor: 'pointer', fontFamily: 'inherit' }"
          title="立刻运行一次"
          @click="emit('run')"
        >
          <Icon name="play" :size="10" />
          <span>运行</span>
        </button>
        <button
          v-else
          type="button"
          class="inline-flex items-center"
          :style="{ gap: '5px', padding: '7px 15px', fontSize: '12px', fontWeight: 600, color: 'var(--red)', background: 'var(--card-2)', border: '1px solid var(--line)', borderRadius: '999px', cursor: 'pointer', fontFamily: 'inherit' }"
          title="停止监测"
          @click="emit('cancel')"
        >
          <Icon name="x" :size="10" />
          <span>停止</span>
        </button>
        <button
          type="button"
          class="inline-flex h-8 w-8 items-center justify-center"
          :style="{ borderRadius: '999px', background: 'var(--card-2)', border: '1px solid var(--line)', color: 'var(--ink-3)', cursor: 'pointer' }"
          title="编辑任务"
          @click="emit('edit')"
        >
          <Icon name="edit" :size="13" />
        </button>
        <button
          type="button"
          class="inline-flex h-8 w-8 items-center justify-center"
          :style="{ borderRadius: '999px', background: 'var(--card-2)', border: '1px solid var(--line)', color: 'var(--ink-3)', cursor: 'pointer' }"
          title="删除任务"
          @click="emit('delete')"
        >
          <Icon name="trash" :size="13" />
        </button>
      </div>
    </div>

    <!-- ════ 页签条 ════ -->
    <div :style="{ padding: '0 22px', flexShrink: 0 }">
      <div class="flex" :style="{ gap: '7px' }">
        <button
          v-for="x in tabs"
          :key="x.k"
          type="button"
          :style="{
            padding: '8px 16px',
            fontSize: '12.5px',
            fontWeight: 600,
            borderRadius: '999px',
            cursor: 'pointer',
            fontFamily: 'inherit',
            border: `1px solid ${tab === x.k ? 'transparent' : 'var(--line)'}`,
            background: tab === x.k ? 'var(--ink)' : 'var(--card)',
            color: tab === x.k ? '#fff' : 'var(--ink-2)',
          }"
          @click="tab = x.k"
        >{{ x.t }}</button>
      </div>
    </div>

    <!-- ════ 页签内容（唯一滚动区）════ -->
    <div
      class="geo-scroll min-h-0 flex-1 overflow-y-auto"
      :style="{ padding: '16px 22px 22px' }"
    >
      <!-- 加载占位 -->
      <div
        v-if="loading && !detail"
        class="py-10 text-center"
        :style="{ fontSize: '12px', color: 'var(--ink-3)' }"
      >加载卡位详情…</div>

      <template v-else>
        <!-- ──────── 页签 A · 概览 ──────── -->
        <div v-if="tab === 'overview'" class="flex flex-col" :style="{ gap: '13px' }">
          <div :style="{ padding: '16px 18px', borderRadius: '16px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
            <GeoHero :metric="metric" :conclusion="detail?.conclusion ?? ''" />
          </div>
          <GeoPlatformStrip :platforms="displayPlatforms" @more="tab = 'matrix'" />
          <div :style="{ padding: '14px 18px', borderRadius: '16px', background: 'var(--card)', border: '1px solid var(--line)' }">
            <GeoTrend :history="detail?.history ?? []" />
          </div>
          <GeoHighlightTeasers
            :head-competitor="detail?.headCompetitor ?? ''"
            :top-source="detail?.topSource ?? ''"
            @compete="tab = 'compete'"
          />
        </div>

        <!-- ──────── 页签 B · 平台对比 ──────── -->
        <div v-else-if="tab === 'matrix'">
          <div class="flex items-baseline justify-between" :style="{ marginBottom: '10px' }">
            <div class="font-display" :style="{ fontSize: '14px', fontWeight: 700 }">平台对比 · 各平台明细</div>
            <div :style="{ fontSize: '11px', color: 'var(--ink-3)' }">左为关于{{ displayBrand }}的原文，右为 AI 采用的信源</div>
          </div>
          <div
            v-if="displayPlatforms.length === 0"
            class="py-10 text-center"
            :style="{ fontSize: '12px', color: 'var(--ink-3)' }"
          >该关键词暂无平台采集结果 · 运行一次后显示各平台原文与信源。</div>
          <div v-else :style="{ columnCount: 2, columnGap: '14px' }">
            <GeoPlatformBlock
              v-for="p in displayPlatforms"
              :key="p.id"
              :platform="p"
              :brand="brand"
              :brand-terms="brandTerms"
            />
          </div>
        </div>

        <!-- ──────── 页签 C · 竞争 · 信源 ──────── -->
        <div v-else class="flex flex-col" :style="{ gap: '16px' }">
          <!-- 块 1 · 竞争品牌 -->
          <div :style="{ padding: '15px 17px', borderRadius: '16px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
            <div class="font-display" :style="{ fontSize: '14px', fontWeight: 700, marginBottom: '10px' }">
              竞争品牌 <span :style="{ fontSize: '10.5px', fontWeight: 500, color: 'var(--ink-3)' }">· 谁压在你前面</span>
            </div>
            <div
              v-if="competitors.length === 0"
              class="py-6 text-center"
              :style="{ fontSize: '11.5px', color: 'var(--ink-3)' }"
            >暂无竞品数据 · 多平台采集出现推荐列表后这里展示竞品定位与位次矩阵。</div>
            <div
              v-else
              :style="{ display: 'grid', gridTemplateColumns: '1fr 1.05fr', gap: '18px', alignItems: 'center' }"
            >
              <div>
                <GeoScatter
                  :points="compPoints"
                  :show-labels="false"
                  x-title="出现平台数"
                  y-title="平均位次"
                  y-top="#1"
                  y-bot="#5"
                  zone="强势区"
                />
                <div class="flex flex-wrap justify-center" :style="{ gap: '14px', marginTop: '8px' }">
                  <GeoLegendDot color="var(--ink-4)" label="其他品牌" />
                  <GeoLegendDot color="var(--primary)" :ring="true" :label="`${displayBrand}（你）`" />
                  <GeoLegendDot :color="COMPETITOR_BLUE" :ring="true" :label="`榜首 · ${headName || '—'}`" />
                </div>
              </div>
              <div>
                <div :style="{ fontSize: '11px', fontWeight: 700, color: 'var(--ink-2)', marginBottom: '8px' }">各平台具体位次</div>
                <GeoRankHeatmap :platforms="displayPlatforms" :competitors="competitors" :target-name="displayBrand" />
                <div :style="{ fontSize: '10.5px', color: 'var(--ink-3)', marginTop: '8px', lineHeight: 1.5 }">{{ competeConclusion }}</div>
              </div>
            </div>
          </div>

          <!-- 块 2 · 信源权重 -->
          <div :style="{ padding: '15px 17px', borderRadius: '16px', background: 'var(--card-2)', border: '1px solid var(--line)' }">
            <div class="font-display" :style="{ fontSize: '14px', fontWeight: 700, marginBottom: '10px' }">
              信源权重 <span :style="{ fontSize: '10.5px', fontWeight: 500, color: 'var(--ink-3)' }">· 近 30 天</span>
            </div>
            <div
              v-if="board.length === 0"
              class="py-6 text-center"
              :style="{ fontSize: '11.5px', color: 'var(--ink-3)' }"
            >暂无信源数据 · 运行后 AI 引用的来源域名会汇总到这里。</div>
            <div
              v-else
              :style="{ display: 'grid', gridTemplateColumns: '1fr 1.05fr', gap: '18px', alignItems: 'center' }"
            >
              <div>
                <GeoScatter
                  :points="srcPoints"
                  :show-labels="false"
                  x-title="引用次数"
                  y-title="平台引用率"
                  y-top="100%"
                  y-bot="0"
                  zone="高权重"
                />
                <div class="flex flex-wrap justify-center" :style="{ gap: '12px', marginTop: '8px' }">
                  <GeoLegendDot
                    v-for="(b, i) in board"
                    :key="b.domain"
                    :color="SRC_COLORS[i % SRC_COLORS.length]"
                    :label="b.domain"
                  />
                </div>
              </div>
              <div>
                <div :style="{ fontSize: '11px', fontWeight: 700, color: 'var(--ink-2)', marginBottom: '8px' }">权重排行榜</div>
                <GeoSourceList :board="board" :total="matrixDenom" :task-id="props.taskId" />
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
