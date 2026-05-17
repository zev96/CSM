<script setup lang="ts">
import { computed } from "vue";
import Card from "@/components/ui/Card.vue";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Blob from "@/components/ui/Blob.vue";
import PlatformChip from "./PlatformChip.vue";
import type { MiningJob, Platform } from "@/stores/mining";

const props = defineProps<{
  job: MiningJob | null;
  counts: { unread: number; done: number; all: number };
}>();

defineEmits<{
  (e: "cancel"): void;
}>();

const totalProgress = computed(() => {
  if (!props.job) return { got: 0, target: 0 };
  let got = 0, target = 0;
  for (const p of props.job.platforms) {
    const pp = props.job.progress[p as Platform];
    if (pp) { got += pp.got; target += pp.target; }
  }
  return { got, target };
});

const isRunning = computed(() =>
  props.job && ["pending", "running"].includes(props.job.status)
);

const startedLabel = computed(() => {
  if (!props.job?.started_at) return "";
  const d = new Date(props.job.started_at);
  return `今天 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
});
</script>

<template>
  <Card dark padless style="position: relative; overflow: hidden;">
    <Blob color="#ee6a2a" :size="260" :top="-60" :left="50" :opacity="0.42"/>
    <Blob color="#fb7299" :size="220" :top="40" :left="460" :opacity="0.32"/>
    <div
      class="relative grid items-center"
      style="grid-template-columns: 1.4fr 1fr; gap: 24px; padding: var(--density-pad);"
    >
      <!-- 左半 -->
      <div v-if="job && isRunning">
        <div class="flex items-center gap-2">
          <span :style="{ width: '6px', height: '6px', borderRadius: '999px', background: 'var(--primary)', boxShadow: '0 0 0 4px rgba(238,106,42,0.22)' }"/>
          <span class="text-[10.5px] uppercase tracking-[1.5px]" style="color: rgba(255,255,255,0.55)">
            正在抓取 · {{ startedLabel }}
          </span>
        </div>
        <div class="font-display font-bold mt-2.5" style="font-size: 28px; color: #fbf7ec; letter-spacing: -0.5px;">
          「{{ job.keyword }}」
        </div>
        <div class="flex items-center gap-1.5 mt-3 flex-wrap">
          <PlatformChip v-for="p in job.platforms" :key="p" :k="p as Platform"/>
          <span class="text-[11px] ml-1" style="color: rgba(255,255,255,0.45)">
            · 每平台 {{ job.target_per_platform }} 条
          </span>
        </div>
        <!-- progress bar -->
        <div class="mt-5">
          <div class="flex items-baseline justify-between mb-1.5">
            <span class="text-[11px]" style="color: rgba(255,255,255,0.55)">进度</span>
            <span class="font-mono text-[11.5px]" style="color: #fbf7ec">
              {{ totalProgress.got }} / {{ totalProgress.target }}
            </span>
          </div>
          <div :style="{ height: '6px', background: 'rgba(255,255,255,0.10)', borderRadius: '999px', overflow: 'hidden' }">
            <div :style="{ height: '100%', width: totalProgress.target > 0 ? (totalProgress.got / totalProgress.target * 100) + '%' : '0%', background: 'linear-gradient(90deg, var(--yellow), var(--primary))', borderRadius: '999px' }"/>
          </div>
        </div>
        <div class="flex items-center gap-2 mt-4">
          <Btn variant="soft" small @click="$emit('cancel')">
            <Icon name="pause" :size="11"/> 暂停
          </Btn>
          <Btn variant="ghost" small disabled style="color: rgba(255,255,255,0.65)">
            查看历史任务
          </Btn>
        </div>
      </div>

      <!-- 左半: idle -->
      <div v-else>
        <div class="text-[10.5px] uppercase tracking-[1.5px]" style="color: rgba(255,255,255,0.45)">
          Outreach · 闲置
        </div>
        <div class="font-display font-bold mt-2.5" style="font-size: 24px; color: #fbf7ec; letter-spacing: -0.5px;">
          没有进行中的任务
        </div>
        <div class="text-[12px] mt-2" style="color: rgba(255,255,255,0.6)">
          点右上「新建抓取任务」起一个吧。
        </div>
      </div>

      <!-- 右半: 4 KPI 卡片 -->
      <div class="grid grid-cols-2 gap-2.5">
        <div
          v-for="s in [
            { l: '累计抓取', v: totalProgress.got || counts.all, sub: '本任务', tone: 'primary' },
            { l: '待评论', v: counts.unread, sub: '未处理', tone: 'yellow' },
            { l: '已评论', v: counts.done, sub: '已留言', tone: 'green' },
            { l: '留存率', v: '—', sub: '近 24h', tone: 'neutral' },
          ]"
          :key="s.l"
          :style="{
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '14px',
            padding: '12px 14px',
          }"
        >
          <div class="text-[10.5px] uppercase tracking-[1.2px]" style="color: rgba(255,255,255,0.5)">{{ s.l }}</div>
          <div
            class="font-display font-bold mt-1.5"
            :style="{
              fontSize: '26px', letterSpacing: '-0.6px',
              color: s.tone === 'primary' ? 'var(--primary)' :
                     s.tone === 'yellow' ? 'var(--yellow)' :
                     s.tone === 'green' ? '#aec890' : '#fbf7ec',
            }"
          >{{ s.v }}</div>
          <div class="text-[10.5px] mt-0.5" style="color: rgba(255,255,255,0.45)">{{ s.sub }}</div>
        </div>
      </div>
    </div>
  </Card>
</template>
