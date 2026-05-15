<script setup lang="ts">
/**
 * 工作台 — 撑满父容器、卡片自适应高度，整页不滚动。
 *
 * 高度分配：
 *   greeting       自适应（约 80px）
 *   hero+calendar  flex-shrink-0，固定 320px（V1 同款）
 *   monitor 双卡   flex-shrink-0，固定 200px
 *   recent 文档    flex-1 min-h-0（吃剩余高度，内部滚）
 *
 * 关键 min-h-0：默认 flex 子项 min-height: auto 会按内容把行撑高，
 * 父级 overflow-hidden 拦不住。显式置 0 才能让 recent 行真正按
 * "剩余可用空间"收缩，长列表的滚动条只在它内部出现。
 */
import { onMounted } from "vue";

import GreetingCard from "@/components/home/GreetingCard.vue";
import KeywordHero from "@/components/home/KeywordHero.vue";
import CalendarCard from "@/components/home/CalendarCard.vue";
import BaiduSeoCard from "@/components/home/BaiduSeoCard.vue";
import RankAlertsCard from "@/components/home/RankAlertsCard.vue";
import CommentRetentionCard from "@/components/home/CommentRetentionCard.vue";
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
    高度分配策略：
      · greeting        自适应（约 80px）
      · hero+calendar   固定 320（V1 同款）
      · monitor 双卡    flex-1 min 260 —— 窗口变高时这一行吃掉多余空间，
                        卡片 h-full + 列表 overflow-y-auto，多余空间会
                        变成更多可见告警/平台行
      · recent 文档     flex-shrink-0 固定 280 —— 不参与抢空间，所以
                        最大化窗口时不会主导整页；多于 4-5 篇时卡片
                        内部自己滚

    根用 h-full（不是 min-h-full）：HomeView 严格等于 wrapper 高度，
    flex-1 的 recent 只能吃"剩下的"空间，不会反过来把 HomeView 撑出
    wrapper 触发外层滚动条。整页因此从来不滚 —— recent 卡片自己内部
    overflow-y-auto 处理超出 10 篇的情况。

    （早期版本曾用 min-h-full 兜底卡片错乱，但现在三段都设了 flex-shrink-0
    + 显式高度，h-full 是最干净的方案。）
  -->
  <div class="flex h-full flex-col" :style="{ gap: '28px' }">
    <GreetingCard />

    <div
      class="grid flex-shrink-0 grid-cols-1 lg:grid-cols-3"
      :style="{ height: '340px', gap: '28px' }"
    >
      <div class="lg:col-span-2"><KeywordHero /></div>
      <CalendarCard />
    </div>

    <div
      class="grid flex-shrink-0 grid-cols-1 lg:grid-cols-3"
      :style="{ height: '220px', gap: '28px' }"
    >
      <BaiduSeoCard />
      <RankAlertsCard />
      <CommentRetentionCard />
    </div>

    <!--
      recent 不设 minHeight —— flex-1 + min-h-0 让它纯吃剩余空间。
      最小窗口下兜底也得至少 ~180（卡片 header 70 + 一行 doc 50 + padding 60），
      但即使更小卡片内部 overflow 会自己处理，不会撑破整页。
    -->
    <div class="min-h-0 flex-1">
      <RecentDocsCard />
    </div>
  </div>
</template>
