<script setup lang="ts">
/**
 * 数据中心 —— 从原 MonitorView 的 "report" tab 抽出来的一级 view，
 * 在左导航栏单独成项（route name = "data-center"，icon = fileText）。
 *
 * 内部结构沿用原 report tab 的 sub-pivot + 3 个 sub-page 渲染：
 *   - 评论平台 → RetentionPage
 *   - 知乎排名 → ZhihuRankingPage
 *   - 百度排名 → BaiduSEOAnalytics
 *
 * sub-page 的 @navigate 事件转成 router.push 到监测中心对应 tab + 详
 * 情参数。MonitorView 当前只接 tab query；platform/batch/task 透传留
 * 待 MonitorView 后续 watch query 自动 selectBatchAndVideo / selectTask。
 */
import { ref } from "vue";
import { useRouter } from "vue-router";

import RetentionPage from "@/components/monitor/history/RetentionPage.vue";
import ZhihuRankingPage from "@/components/monitor/history/ZhihuRankingPage.vue";
import BaiduSEOAnalytics from "@/components/monitor/history/BaiduSEOAnalytics.vue";
import GeoAnalyticsPage from "@/components/monitor/history/GeoAnalyticsPage.vue";

type HistorySubtab = "retention" | "zhihu" | "baidu" | "geo";

const router = useRouter();
const historySubtab = ref<HistorySubtab>("retention");

// 顶部右侧 pivot 选项 —— 按用户要求去掉前置 icon，并把顺序调整为
// 知乎排名 / 平台评论 / 百度排名（跟 MonitorView 的 zhihu/comment/baidu
// 顺序一致）。默认选中依然是 'retention'（业务定的"默认看评论留存"），
// 列表顺序只影响展示位置。
const HISTORY_TABS: Array<{ k: HistorySubtab; l: string }> = [
  { k: "zhihu", l: "知乎排名" },
  { k: "retention", l: "平台评论" },
  { k: "baidu", l: "百度排名" },
  { k: "geo", l: "AI 卡位" },
];

function goToCommentTask(payload: {
  platform: "bilibili_comment" | "douyin_comment" | "kuaishou_comment";
  batchName: string;
  taskId: number;
}) {
  const platformSubtab =
    payload.platform === "bilibili_comment"
      ? "bilibili"
      : payload.platform === "douyin_comment"
        ? "douyin"
        : "kuaishou";
  router.push({
    name: "monitor",
    query: {
      tab: "comment",
      platform: platformSubtab,
      batch: payload.batchName,
      task: payload.taskId,
    },
  });
}

function goToZhihuTask(payload: { taskId: number }) {
  router.push({
    name: "monitor",
    query: { tab: "zhihu", task: payload.taskId },
  });
}

function goToBaiduTask(_payload: { taskId: number }) {
  router.push({ name: "monitor", query: { tab: "baidu" } });
}

function goToGeoTask(payload: { taskId: number }) {
  router.push({
    name: "monitor",
    query: { tab: "geo", task: payload.taskId },
  });
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '24px' }">
    <!--
      顶部：title + pivot ——
      按用户要求，sub-pivot（评论平台 / 知乎排名 / 百度排名）从卡内搬到
      标题行右侧，跟 MonitorView 的 tab 位置一致；title 下面的「日报 ·
      周报 · 按时间倒序」subtitle 一并移除。卡内原本的 section header
      （"评论平台 · 留存率分析" / "知乎排名 · 品牌占有率分析" / "百度 SEO
      · 关键词排名分析"）随 pivot 一起迁走，sub-page 内容直接顶到卡顶。
    -->
    <div class="flex flex-shrink-0 items-center justify-between gap-4">
      <div class="min-w-0">
        <!--
          标题按用户要求改为小字 eyebrow 样式（11px / tracking 1.5px /
          ink-3）—— 大 H1 已经被 pivot 视觉抢走，留小标签足够定位。
          items-center 让小标签和 pivot 中线对齐，避免大标题去掉后的
          垂直空隙。
        -->
        <div
          class="text-[11px] uppercase"
          :style="{ letterSpacing: '1.5px', color: 'var(--ink-3)' }"
        >
          数据中心
        </div>
      </div>

      <div
        class="flex flex-shrink-0 items-center"
        :style="{
          background: 'var(--card)',
          borderRadius: '999px',
          padding: '4px',
          border: '1px solid var(--line)',
        }"
      >
        <button
          v-for="t in HISTORY_TABS"
          :key="t.k"
          type="button"
          class="inline-flex items-center"
          :style="{
            height: '32px',
            padding: '0 16px',
            borderRadius: '999px',
            background: historySubtab === t.k ? 'var(--dark)' : 'transparent',
            color: historySubtab === t.k ? '#fbf7ec' : 'var(--ink-3)',
            fontSize: '12.5px',
            fontWeight: 500,
            transition: 'background .15s, color .15s',
          }"
          @click="historySubtab = t.k"
        >
          {{ t.l }}
        </button>
      </div>
    </div>

    <!-- ── 主体卡片 ───────────────────────────────────── -->
    <section
      class="flex min-h-0 flex-1 flex-col"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '22px',
      }"
    >
      <!--
        history sub-page wrapper —— overflow-hidden 让 sub-page 自己管
        滚动。每个 sub-page 的根 div 用 h-full + flex 列布局，把滚动锁
        在「问题列表 / 关键词列表」区块里，KPI + 图表保持固定。
        section header 已移到外层标题行 pivot，sub-page 内容直接顶到卡顶。
      -->
      <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <RetentionPage
          v-if="historySubtab === 'retention'"
          @navigate="goToCommentTask"
        />
        <ZhihuRankingPage
          v-else-if="historySubtab === 'zhihu'"
          @navigate="goToZhihuTask"
        />
        <BaiduSEOAnalytics
          v-else-if="historySubtab === 'baidu'"
          @navigate="goToBaiduTask"
        />
        <GeoAnalyticsPage
          v-else-if="historySubtab === 'geo'"
          @navigate="goToGeoTask"
        />
      </div>
    </section>
  </div>
</template>
