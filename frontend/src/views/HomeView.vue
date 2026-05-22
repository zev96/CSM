<script setup lang="ts">
/**
 * 工作台 — 3 段布局，撑满父容器、整页不滚。
 *
 *   Row 1   ─ hero 紧凑（auto 高，自适应内容），平铺无外框
 *   Row 2   ─ flex-1 min-h-0，4 张监测卡（百度 / 知乎 / 评论留存 / 视频抓取）
 *   Row 3   ─ 140px 固定，最近文档（横排 4 卡，单行高）
 *
 * 之前是 hero 280px + Row2/Row3 flex-1 平分。参考设计把"最近文档"压成
 * 一行卡片高度，把剩余空间几乎都留给 4 张监测卡 —— 监测信息是工作台
 * 主信息，文档列表是次要入口（看完整列表走「全部 →」进 RecentHistoryView）。
 *
 * 关键 min-h-0：默认 flex 子项 min-height: auto 会按内容把 Row 撑高，
 * 父级 overflow-hidden 拦不住。显式置 0 让 Row 2 真正按"剩余可用空间"收缩。
 *
 * ShortcutColumn 被移除 —— 那 3 个入口（数据中心 / 引流中心 / 模板库）
 * 在 LeftNav 里已有，hero 旁边的复制只是重复噪音。
 */
import { onMounted } from "vue";

import CreateArticleHero from "@/components/home/CreateArticleHero.vue";
import BaiduSeoCard from "@/components/home/BaiduSeoCard.vue";
import ZhihuCard from "@/components/home/ZhihuCard.vue";
import CommentRetentionCard from "@/components/home/CommentRetentionCard.vue";
import VideoMiningCard from "@/components/home/VideoMiningCard.vue";
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
  <div class="flex h-full flex-col" :style="{ gap: '20px' }">
    <!-- Row 1：hero 紧凑平铺 -->
    <div class="flex-shrink-0">
      <CreateArticleHero />
    </div>

    <!-- Row 2：4 张监测卡，flex-1 抢占剩余空间 -->
    <div
      class="grid min-h-0 flex-1 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
      :style="{ gap: '20px' }"
    >
      <BaiduSeoCard />
      <ZhihuCard />
      <CommentRetentionCard />
      <VideoMiningCard />
    </div>

    <!-- Row 3：最近文档（单行卡片高） -->
    <div class="flex-shrink-0" :style="{ height: '140px' }">
      <RecentDocsCard />
    </div>
  </div>
</template>
