<script setup lang="ts">
/**
 * 工作台 — 3 行布局，撑满父容器、整页不滚。
 *
 *   Row 1   ─ 280px 固定，3 列（左 2/3 CreateArticleHero + 右 1/3 ShortcutColumn）
 *   Row 2   ─ 280px 固定，4 列（百度 / 知乎 / 评论留存 / 视频抓取）
 *   Row 3   ─ flex-1 min-h-0 自适应（最近文档，横排 4 卡）
 *
 * 关键 min-h-0：默认 flex 子项 min-height: auto 会按内容把 Row3 撑高，
 * 父级 overflow-hidden 拦不住。显式置 0 让 Row3 真正按"剩余可用空间"
 * 收缩，多于 4 篇时点 "全部 →" 跳完整历史。
 *
 * 设计契约参考 docs/Design.md §6。
 */
import { onMounted } from "vue";

import CreateArticleHero from "@/components/home/CreateArticleHero.vue";
import ShortcutColumn from "@/components/home/ShortcutColumn.vue";
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
  <div class="flex h-full flex-col" :style="{ gap: '22px' }">
    <!-- Row 1：hero + 3 shortcut 卡 -->
    <div
      class="grid flex-shrink-0 grid-cols-1 lg:grid-cols-3"
      :style="{ height: '280px', gap: '22px' }"
    >
      <div class="lg:col-span-2"><CreateArticleHero /></div>
      <ShortcutColumn />
    </div>

    <!-- Row 2：4 张监测卡 -->
    <div
      class="grid flex-shrink-0 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
      :style="{ height: '280px', gap: '22px' }"
    >
      <BaiduSeoCard />
      <ZhihuCard />
      <CommentRetentionCard />
      <VideoMiningCard />
    </div>

    <!-- Row 3：最近文档（自适应吃剩余高度） -->
    <div class="min-h-0 flex-1">
      <RecentDocsCard />
    </div>
  </div>
</template>
