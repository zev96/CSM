<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import Spinner from "@/components/ui/Spinner.vue";
import { getWordsStats } from "@/api/client";
import { useConfig } from "@/stores/config";

const cfg = useConfig();
const loading = ref(true);
const stats = ref<Awaited<ReturnType<typeof getWordsStats>> | null>(null);
const yesterdayWords = ref(0);

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 6) return "深夜好";
  if (h < 11) return "早安";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
});
const userName = computed(() => cfg.data?.user_name || "你");

// 上方 caption 改为「N 月 N 日 · 周X」—— 原 Workspace · 下午好 跟下方
// 大标题里的「下午好」重复，没承载新信息；换成今天的日期 + 星期，让
// 用户一眼知道"今天是几号"，比固定字符串信息密度高。
const todayLabel = computed(() => {
  const d = new Date();
  const WD = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 · ${WD[d.getDay()]}`;
});

// 本周字数柱状图（Bars）整段删除 —— 零数据日柱子是 0 高度但 label 仍
// 在底下显示，结果右侧只剩一个孤零零的字母（之前是 M，本地化后是
// 「一」），用户体感是"那是啥？"。文本「昨天 N 字 · 本周 N 字」已经
// 传达了同样的信息，柱状图属于 V1 设计稿的视觉装饰，零数据时反而碍
// 眼，直接拿掉。

onMounted(async () => {
  try {
    const [week, y] = await Promise.all([
      getWordsStats("this-week"),
      getWordsStats("yesterday"),
    ]);
    stats.value = week;
    yesterdayWords.value = y.total_words;
  } catch {
    /* ignore — empty card stays */
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <!--
    Greeting sits directly on the paper-card surface — no card chrome,
    matches the V2 design where WORKSPACE / 下午好 / 字数 stats float
    above the workspace without a container.
  -->
  <div class="px-1">
    <div class="min-w-0 flex-1">
      <div class="text-[11px] tracking-wider text-ink-3">
        {{ todayLabel }}
      </div>
      <div class="font-display mt-1 text-[26px] font-bold leading-tight">
        {{ greeting }}，<span>{{ userName }}</span>，继续创作
      </div>
      <div class="mt-1.5 text-[12px] text-ink-3">
        <template v-if="loading">
          <Spinner :size="14" />
        </template>
        <template v-else>
          昨天 <span class="text-ink-2 font-semibold">{{ yesterdayWords }}</span> 字
          · 本周 <span class="text-ink-2 font-semibold">{{ stats?.total_words ?? 0 }}</span> 字
        </template>
      </div>
    </div>
  </div>
</template>
