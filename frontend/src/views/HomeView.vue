<script setup lang="ts">
/**
 * 工作台 — bento 版式（按「图一」）。**全比例布局**：bento 填满 hero 以下的
 * 全部高度，内部行高/列宽都用 flex 权重（比例），所以窗口放大缩小时所有卡片
 * 等比缩放、任何尺寸都填满，不会出现「放到最大中间一大片空白」（图二）。
 *
 *   ┌ 左主区 (flex 3) ───────────────────────────┐ ┌ 右列 (flex 1) ──┐
 *   │ 百度SEO │ 知乎问题 │ 知乎搜索   (行比例 17)  │ │ 高权重信源 (1)  │
 *   │ 评论留存率(1.3) │ GEO(1)      (行比例 25)    │ │ 最近文档   (1)  │  ← 右列 1:1
 *   └────────────────────────────────────────────┘ └────────────────┘
 *
 * 比例：主区:右列宽=3:1；数字卡行:留存行高=17:25；右列两卡=1:1；留存:GEO=1.3:1。
 * 全部 min-h-0 让其随窗口收缩；外层 overflow-hidden 兜底不滚。视频抓取卡已移除。
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
  <div class="flex h-full flex-col overflow-hidden">
    <!-- 创作区 hero -->
    <div class="flex-shrink-0">
      <CreateArticleHero />
    </div>

    <!-- 创作区 ↔ 卡片间距 -->
    <div class="flex-shrink-0" :style="{ height: '36px' }"></div>

    <!-- bento：flex-1 填满剩余高度，内部全用比例 → 等比缩放、不留空白 -->
    <div class="flex min-h-0 flex-1" :style="{ gap: '16px' }">
      <!-- 左主区 (宽比例 3) -->
      <div class="flex min-h-0 flex-col" :style="{ flex: '3 1 0', gap: '16px' }">
        <!-- 数字卡行 (高比例 17) -->
        <div class="flex min-h-0" :style="{ gap: '16px', flex: '17 1 0' }">
          <div class="min-h-0 flex-1">
            <StatCardLoader
              category="百度 SEO"
              endpoint="/api/monitor/history/baidu-keyword"
              value-key="changed_keywords"
              tab="baidu"
            />
          </div>
          <div class="min-h-0 flex-1">
            <StatCardLoader
              category="知乎问题"
              endpoint="/api/monitor/history/zhihu-ranking"
              value-key="changed_questions"
              tab="zhihu"
            />
          </div>
          <div class="min-h-0 flex-1">
            <StatCardLoader
              category="知乎搜索"
              endpoint="/api/monitor/history/zhihu-search"
              value-key="changed_keywords"
              tab="zhihu_search"
            />
          </div>
        </div>

        <!-- 评论留存 + GEO 行 (高比例 25)，内部 1.3:1 -->
        <div class="flex min-h-0" :style="{ gap: '16px', flex: '25 1 0' }">
          <div class="min-h-0" :style="{ flex: '1.3 1 0' }">
            <CommentRetentionCard />
          </div>
          <div class="min-h-0" :style="{ flex: '1 1 0' }">
            <GaugeCard />
          </div>
        </div>
      </div>

      <!-- 右列 (宽比例 1)：高权重信源 + 最近文档 1:1 -->
      <div class="flex min-h-0 flex-col" :style="{ flex: '1 1 0', gap: '16px' }">
        <div class="min-h-0 flex-1">
          <SourceLeaderboardCard />
        </div>
        <div class="min-h-0 flex-1">
          <RecentDocsCard />
        </div>
      </div>
    </div>

    <!-- 底部留白 -->
    <div class="flex-shrink-0" :style="{ height: '20px' }"></div>
  </div>
</template>
