<script setup lang="ts">
/**
 * 工作台 — 3 段布局，撑满父容器、整页不滚。
 *
 *   Row 1   ─ hero 紧凑（auto 高，自适应内容），平铺无外框
 *   Row 2   ─ flex-1 min-h-0，6 张监测卡 3×2（百度 / 知乎 / 评论留存 / 视频抓取 / 知乎搜索 / GEO）
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
import ZhihuSearchCard from "@/components/home/ZhihuSearchCard.vue";
import GeoCard from "@/components/home/GeoCard.vue";
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
  <!--
    布局节奏（间距固定 / 卡片按视觉比例拉伸）：
      - Hero      自然高度 (flex-shrink-0)     ← 不变
      - 上 spacer 固定 45px (flex-shrink-0)    ← 所有尺寸都不变
      - Row 2     flex 320 1 320px  min 280   ← 拉伸时按 320 分余量
      - 下 spacer 固定 20px (flex-shrink-0)    ← 所有尺寸都不变
      - Row 3     flex 140 1 140px  min 120   ← 拉伸时按 140 分余量
    grow 比例 320:140 ≈ 2.3:1 等于当前 Row 2 / Row 3 的视觉高度比，
    所以窗口拉大时两张卡同比例长高，hero 区 + 间距纹丝不动。卡片本身
    overflow-y-auto，多出的高度自然让内部列表露出更多关键词 / 文档。
    1280×800 容器 ~704：basis 总和 ~710 → 缺 ~6 → Row 2 / Row 3 微缩。
    大窗口 1000 容器 904：余 ~194 → Row 2 +135 ≈ 455，Row 3 +59 ≈ 199。
  -->
  <div class="flex h-full flex-col">
    <!-- Row 1：hero 紧凑平铺 -->
    <div class="flex-shrink-0">
      <CreateArticleHero />
    </div>

    <!-- hero ↔ Row 2 固定 25px（比之前 45 缩 20px，让 Row 2 整体上移） -->
    <div class="flex-shrink-0" :style="{ height: '25px' }"></div>

    <!-- Row 2：6 张监测卡（3×2），basis 340 -->
    <div
      class="grid min-h-0 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
      :style="{ gap: '20px', flex: '340 1 340px', minHeight: '300px' }"
    >
      <BaiduSeoCard />
      <ZhihuCard />
      <CommentRetentionCard />
      <VideoMiningCard />
      <ZhihuSearchCard />
      <GeoCard />
    </div>

    <!-- Row 2 ↔ Row 3 固定 20px，所有窗口尺寸都不变 -->
    <div class="flex-shrink-0" :style="{ height: '20px' }"></div>

    <!-- Row 3：最近文档，grow 140（跟 Row 2 320 按比例分） -->
    <div :style="{ flex: '140 1 140px', minHeight: '120px' }">
      <RecentDocsCard />
    </div>
  </div>
</template>
