<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import StartJobModal from "@/components/mining/StartJobModal.vue";
import OutreachHero from "@/components/mining/OutreachHero.vue";
import VideoCard from "@/components/mining/VideoCard.vue";
import { useMiningStore, type Platform } from "@/stores/mining";

const store = useMiningStore();
const showNewTask = ref(false);
const tab = ref<"unread" | "done" | "all">("unread");
const platform = ref<"all" | Platform>("all");
const sortBy = ref("最新");
const selected = ref(new Set<number>());

const counts = computed(() => ({
  unread: store.videos.filter(v => !v.already_commented).length,
  done: store.videos.filter(v => v.already_commented).length,
  all: store.videos.length,
}));

const filtered = computed(() => {
  return store.videos.filter(v => {
    if (tab.value === "unread" && v.already_commented) return false;
    if (tab.value === "done" && !v.already_commented) return false;
    if (platform.value !== "all" && v.platform !== platform.value) return false;
    if (store.filters.q && !v.title.includes(store.filters.q) && !v.author_name.includes(store.filters.q)) return false;
    return true;
  });
});

function toggleSelect(id: number) {
  const s = new Set(selected.value);
  s.has(id) ? s.delete(id) : s.add(id);
  selected.value = s;
}

async function onStartSubmit(payload: { keyword: string; platforms: Platform[]; target: number }) {
  showNewTask.value = false;
  await store.startJob(payload.keyword, payload.platforms, payload.target);
}

onMounted(async () => {
  await store.refreshLoginStatus();
  await store.refreshVideos();
});
</script>

<template>
  <div class="anim-up flex flex-col" style="gap: var(--density-gap); padding-bottom: 60px; position: relative;">
    <!-- 页头 -->
    <div class="flex items-end justify-between">
      <div>
        <div class="text-[11px] tracking-[1.5px] uppercase" style="color: var(--ink-3)">
          Outreach · 引流
        </div>
        <div class="font-display font-bold mt-2" style="font-size: 30px; letter-spacing: -0.5px;">
          视频抓取
        </div>
        <div class="text-[12.5px] mt-1" style="color: var(--ink-3)">
          抓取抖音 / B 站 / 快手 关键词相关视频，把要去种草的评论区集中到一处。
        </div>
      </div>
      <div class="flex items-center gap-2">
        <a
          :href="store.exportUrl()"
          download="mining_videos.csv"
          class="inline-flex items-center gap-1.5 font-medium px-4 py-2 text-[13px] bg-transparent hover:bg-[rgba(28,26,23,0.05)]"
          style="border-radius: var(--radius-pill); color: var(--ink-2);"
        >
          <Icon name="download" :size="12"/> 导出 CSV
        </a>
        <Btn variant="solid" :disabled="store.hasRunningJob" @click="showNewTask = true">
          <Icon name="plus" :size="12"/> 新建抓取任务
        </Btn>
      </div>
    </div>

    <!-- Hero -->
    <OutreachHero
      :job="store.activeJob"
      :counts="counts"
      @cancel="store.cancelActive"
    />

    <!-- Filter 条 -->
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <div class="flex items-center gap-2">
        <!-- 状态 pivot -->
        <div class="flex items-center" style="background: var(--card); border-radius: 999px; padding: 4px; border: 1px solid var(--line);">
          <button
            v-for="t in [
              { k: 'unread', l: '待评论', n: counts.unread },
              { k: 'done', l: '已评论', n: counts.done },
              { k: 'all', l: '全部', n: counts.all },
            ]"
            :key="t.k"
            @click="tab = t.k as any"
            :style="{
              height: '32px', padding: '0 14px', borderRadius: '999px',
              background: tab === t.k ? 'var(--dark)' : 'transparent',
              color: tab === t.k ? '#fbf7ec' : 'var(--ink-3)',
              fontSize: '12.5px', fontWeight: 500,
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              border: 'none', cursor: 'pointer',
            }"
          >
            {{ t.l }}
            <span
              class="text-[10.5px]"
              :style="{
                color: tab === t.k ? 'rgba(255,255,255,0.55)' : 'var(--ink-4)',
                background: tab === t.k ? 'rgba(255,255,255,0.08)' : 'var(--card-2)',
                borderRadius: '999px', padding: '1px 7px',
              }"
            >{{ t.n }}</span>
          </button>
        </div>

        <!-- 平台筛选 -->
        <div class="flex items-center" style="background: var(--card); border-radius: 999px; padding: 4px; border: 1px solid var(--line);">
          <button
            v-for="p in [
              { k: 'all', l: '全部', dot: null },
              { k: 'bilibili', l: 'B 站', dot: '#fb7299' },
              { k: 'douyin', l: '抖音', dot: '#1c1a17' },
              { k: 'kuaishou', l: '快手', dot: '#ff6633' },
            ]"
            :key="p.k"
            @click="platform = p.k as any"
            :style="{
              height: '32px', padding: '0 12px', borderRadius: '999px',
              background: platform === p.k ? 'var(--card-2)' : 'transparent',
              color: platform === p.k ? 'var(--ink)' : 'var(--ink-3)',
              fontSize: '12px', fontWeight: 500,
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              border: platform === p.k ? '1px solid var(--line-2)' : '1px solid transparent',
              cursor: 'pointer',
            }"
          >
            <span v-if="p.dot" :style="{ width: '6px', height: '6px', borderRadius: '999px', background: p.dot }"/>
            {{ p.l }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <!-- sort -->
        <button
          class="inline-flex items-center gap-1.5 text-[11.5px]"
          style="height: 34px; padding: 0 12px; background: var(--card); border: 1px solid var(--line); border-radius: 999px; color: var(--ink-2); cursor: pointer;"
        >
          <Icon name="sort" :size="12"/> {{ sortBy }}
          <Icon name="arrowDown" :size="10" style="opacity: 0.5"/>
        </button>

        <!-- search -->
        <div class="flex items-center" style="height: 34px; background: var(--card); border: 1px solid var(--line); border-radius: 999px; padding: 0 12px; width: 240px;">
          <Icon name="search" :size="13" style="opacity: 0.6"/>
          <input
            v-model="store.filters.q"
            @input="store.refreshVideos()"
            placeholder="搜索标题或作者…"
            class="flex-1 bg-transparent outline-none px-2 text-[12px]"
          />
          <button v-if="store.filters.q" @click="store.filters.q = ''; store.refreshVideos();" style="color: var(--ink-3)">
            <Icon name="x" :size="12"/>
          </button>
        </div>
      </div>
    </div>

    <!-- 视频网格 -->
    <div v-if="filtered.length > 0" class="grid" style="grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px;">
      <VideoCard
        v-for="v in filtered"
        :key="v.id"
        :v="v"
        :selected="selected.has(v.id)"
        @toggle-select="toggleSelect"
      />
    </div>
    <div v-else class="pad-d flex flex-col items-center text-center" style="padding: 60px 30px; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius-card);">
      <span style="width: 54px; height: 54px; border-radius: 16px; background: var(--card-2); color: var(--ink-3); display: inline-flex; align-items: center; justify-content: center;">
        <Icon name="video" :size="22"/>
      </span>
      <div class="font-display font-bold mt-4" style="font-size: 18px;">没有匹配的视频</div>
      <div class="text-[12.5px] mt-1.5" style="color: var(--ink-3); max-width: 420px;">
        换个筛选，或者起一个新任务再抓一批。
      </div>
      <div class="flex items-center gap-2 mt-5">
        <Btn variant="ghost" @click="tab = 'all'; platform = 'all'; store.filters.q = ''; store.refreshVideos();">清除筛选</Btn>
        <Btn variant="solid" @click="showNewTask = true"><Icon name="plus" :size="12"/> 新建任务</Btn>
      </div>
    </div>

    <!-- 浮动批量栏 -->
    <div
      v-if="selected.size > 0"
      class="anim-up"
      style="position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%); background: var(--dark); color: #fbf7ec; border-radius: 999px; padding: 8px 8px 8px 18px; display: inline-flex; align-items: center; gap: 14px; box-shadow: 0 14px 30px -10px rgba(28,26,23,0.5); z-index: 25;"
    >
      <span class="text-[12.5px]">
        已选 <b class="font-display" style="color: var(--primary)">{{ selected.size }}</b> 条
      </span>
      <span style="width: 1px; height: 18px; background: rgba(255,255,255,0.14);"/>
      <button
        disabled
        class="inline-flex items-center gap-1.5 text-[12px] font-medium"
        style="height: 30px; padding: 0 12px; border-radius: 999px; background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.45); cursor: not-allowed;"
        title="第二期上线"
      >
        <Icon name="check" :size="12"/> 标记已评论
      </button>
      <button
        class="inline-flex items-center gap-1.5 text-[12px] font-medium"
        style="height: 30px; padding: 0 12px; border-radius: 999px; background: rgba(255,255,255,0.08); color: #fbf7ec; cursor: pointer;"
      >
        <Icon name="external" :size="12"/> 全部打开
      </button>
      <button
        disabled
        class="inline-flex items-center gap-1.5 text-[12px] font-medium"
        style="height: 30px; padding: 0 12px; border-radius: 999px; background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.45); cursor: not-allowed;"
        title="第二期上线"
      >
        <Icon name="download" :size="12"/> 导出选中
      </button>
      <button
        @click="selected = new Set()"
        class="inline-flex items-center justify-center"
        style="width: 30px; height: 30px; border-radius: 999px; background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.55); cursor: pointer;"
      >
        <Icon name="x" :size="12"/>
      </button>
    </div>

    <StartJobModal
      v-if="showNewTask"
      :login-status="store.loginStatus"
      @close="showNewTask = false"
      @submit="onStartSubmit"
    />
  </div>
</template>
