<script setup lang="ts">
/**
 * 工作台 — bento 版式（按「图一」）。整页不滚，撑满父容器。
 *
 *   Row 1（auto，矮）  百度SEO │ 知乎问题 │ 知乎搜索 │ ┐
 *   Row 2（1fr）       评论留存率(跨2列) │ GEO    │ 高权重信源(跨 r1-2)
 *   Row 3（1fr）       (评论留存续)      │(GEO续) │ 最近文档
 *
 * 三张大数字卡（异动数）在第 1 行矮卡；评论留存 + GEO 仪表盘是高卡跨 2 行；
 * 高权重信源在右列跨上两行；最近文档在右下。视频抓取卡已从首页移除。
 * 精确 span/gap 可继续微调；卡片各自 overflow 处理高度。
 */
import { onMounted } from "vue";

import CreateArticleHero from "@/components/home/CreateArticleHero.vue";
import StatCardLoader from "@/components/home/StatCardLoader.vue";
import SourceLeaderboardCard from "@/components/home/SourceLeaderboardCard.vue";
import CommentRetentionCard from "@/components/home/CommentRetentionCard.vue";
import GaugeCard from "@/components/home/GaugeCard.vue";
import RecentDocsCard from "@/components/home/RecentDocsCard.vue";

import { useConfig } from "@/stores/config";
import { useSidecarReady } from "@/composables/useSidecarReady";

const cfg = useConfig();
const { whenReady } = useSidecarReady();

onMounted(async () => {
  try {
    await whenReady();
    if (!cfg.data) await cfg.load();
  } catch {
    /* sidecar bootstrap error already toasted */
  }
});
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Row 1：hero 紧凑平铺 -->
    <div class="flex-shrink-0">
      <CreateArticleHero />
    </div>

    <div class="flex-shrink-0" :style="{ height: '20px' }"></div>

    <!-- bento 网格：4 列 × 3 行（行1 auto 矮，行2/3 平分剩余） -->
    <div
      class="grid min-h-0 flex-1"
      :style="{
        gap: '16px',
        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gridTemplateRows: 'auto minmax(0, 1fr) minmax(0, 1fr)',
      }"
    >
      <div class="min-h-0" :style="{ gridColumn: '1', gridRow: '1' }">
        <StatCardLoader
          category="百度 SEO"
          endpoint="/api/monitor/history/baidu-keyword"
          value-key="changed_keywords"
          tab="baidu"
        />
      </div>
      <div class="min-h-0" :style="{ gridColumn: '2', gridRow: '1' }">
        <StatCardLoader
          category="知乎问题"
          endpoint="/api/monitor/history/zhihu-ranking"
          value-key="changed_questions"
          tab="zhihu"
        />
      </div>
      <div class="min-h-0" :style="{ gridColumn: '3', gridRow: '1' }">
        <StatCardLoader
          category="知乎搜索"
          endpoint="/api/monitor/history/zhihu-search"
          value-key="changed_keywords"
          tab="zhihu_search"
        />
      </div>
      <div class="min-h-0" :style="{ gridColumn: '4', gridRow: '1 / span 2' }">
        <SourceLeaderboardCard />
      </div>
      <div class="min-h-0" :style="{ gridColumn: '1 / span 2', gridRow: '2 / span 2' }">
        <CommentRetentionCard />
      </div>
      <div class="min-h-0" :style="{ gridColumn: '3', gridRow: '2 / span 2' }">
        <GaugeCard />
      </div>
      <div class="min-h-0" :style="{ gridColumn: '4', gridRow: '3' }">
        <RecentDocsCard />
      </div>
    </div>
  </div>
</template>
