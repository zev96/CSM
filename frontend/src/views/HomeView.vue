<script setup lang="ts">
/**
 * 工作台 — 3 行布局，撑满父容器、整页不滚。
 *
 *   Row 1   ─ 280px 固定，3 列（左 2/3 CreateArticleHero + 右 1/3 ShortcutColumn）
 *   Row 2   ─ flex-1 min-h-0，4 列（百度 / 知乎 / 评论留存 / 视频抓取）
 *   Row 3   ─ flex-1 min-h-0（最近文档，横排 4 卡）
 *
 * Row 2 与 Row 3 都用 flex-1：hero 280px 之外的剩余空间被两行**等分**。
 * 之前 Row 2 写死 280px 在 Tauri ~900px 窗口里挤压 Row 3 让最近文档卡只剩
 * 200px 不到的 body，视觉上 Row 2 显得过重 —— 改成等分后高度更平衡，符合
 * 用户提的红框比例。卡片本身用 min-h-0 容忍较矮窗口的压缩。
 *
 * 关键 min-h-0：默认 flex 子项 min-height: auto 会按内容把 Row 撑高，
 * 父级 overflow-hidden 拦不住。显式置 0 让两行真正按"剩余可用空间"收缩。
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

    <!-- Row 2：4 张监测卡（与 Row 3 等高，flex-1 平分 hero 之外的剩余空间） -->
    <div
      class="grid min-h-0 flex-1 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
      :style="{ gap: '22px' }"
    >
      <BaiduSeoCard />
      <ZhihuCard />
      <CommentRetentionCard />
      <VideoMiningCard />
    </div>

    <!-- Row 3：最近文档（与 Row 2 等高） -->
    <div class="min-h-0 flex-1">
      <RecentDocsCard />
    </div>
  </div>
</template>
