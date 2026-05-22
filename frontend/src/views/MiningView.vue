<script setup lang="ts">
/**
 * 视频抓取页 — 双栏布局。
 *
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │ 视频抓取 「当前任务关键词」                          [导出 CSV] │
 *   ├──────────────┬───────────────────────────────────────────────────┤
 *   │              │ filter row (status / platform / sort / search)    │
 *   │ 抓取任务      ├───────────────────────────────────────────────────┤
 *   │ 列表          │ [bulk toolbar — visible only when 有选中卡片]      │
 *   │  - keyword    ├───────────────────────────────────────────────────┤
 *   │  - status     │                                                   │
 *   │  - platforms  │  <VideoCard grid 2 列, 内部滚动>                  │
 *   │  - 进度条      │                                                   │
 *   │              │                                                   │
 *   └──────────────┴───────────────────────────────────────────────────┘
 *
 * 全屏高度由 router parent (calc(100vh - 116px) 类似) 决定;本视图把
 * height: 100% + overflow: hidden 撑满,两栏各自 overflow: auto 独立滚。
 *
 * 切换任务 (点左栏其他项) -> store.selectJob(id) 设 filters.job_id 重抓
 * 视频列表;右栏全量替换为该 job 的视频。currentJobId === null 表示
 * "全部任务"(也就是当前没任何 job 被选中,这种状态主要是空 DB / 刚清掉
 * 历史 之后)。
 */
import { ref, computed, onMounted } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import StartJobModal from "@/components/mining/StartJobModal.vue";
import VideoCard from "@/components/mining/VideoCard.vue";
import TaskListPanel from "@/components/mining/TaskListPanel.vue";
import { useMiningStore, type Platform } from "@/stores/mining";
import { useToast } from "@/composables/useToast";

const store = useMiningStore();
const toast = useToast();

const showNewTask = ref(false);
// 平台 cookie 池统一从 设置 → Cookie 池 入口管理,这里不再重复一个入口。

const tab = ref<"unread" | "done" | "all">("unread");
const platform = ref<"all" | Platform>("all");
const selected = ref(new Set<number>());
const bulkMarkBusy = ref(false);
const bulkDeleteBusy = ref(false);

const counts = computed(() => ({
  unread: store.videos.filter(v => !v.already_commented).length,
  done: store.videos.filter(v => v.already_commented).length,
  all: store.total ?? store.videos.length,
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

const isAllSelected = computed(() =>
  filtered.value.length > 0 && selected.value.size >= filtered.value.length
);

const currentJobKeyword = computed(() => {
  if (store.currentJobId == null) return "";
  const j = store.jobs.find(x => x.id === store.currentJobId);
  return j?.keyword || "";
});

function toggleSelect(id: number) {
  const s = new Set(selected.value);
  s.has(id) ? s.delete(id) : s.add(id);
  selected.value = s;
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    selected.value = new Set();
  } else {
    selected.value = new Set(filtered.value.map(v => v.id));
  }
}

async function onSelectJob(id: number) {
  if (store.currentJobId === id) return;
  selected.value = new Set();
  await store.selectJob(id);
}

async function onStartSubmit(payload: { keyword: string; platforms: Platform[]; target: number }) {
  showNewTask.value = false;
  try {
    const newJobId = await store.startJob(payload.keyword, payload.platforms, payload.target);
    // Auto-switch the right column to the freshly-created task so the user
    // sees its progress + videos immediately.
    await store.selectJob(newJobId);
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("新建任务失败" + (detail ? "：" + detail : ""));
  }
}

async function onBulkMarkCommented() {
  if (selected.value.size === 0 || bulkMarkBusy.value) return;
  bulkMarkBusy.value = true;
  try {
    const ids = Array.from(selected.value);
    const updated = await store.bulkMarkCommented(ids, true);
    toast.success(`已标记 ${updated} 条`);
    selected.value = new Set();
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("批量标记失败" + (detail ? "：" + detail : ""));
  } finally {
    bulkMarkBusy.value = false;
  }
}

async function onBulkDelete() {
  if (selected.value.size === 0 || bulkDeleteBusy.value) return;
  const n = selected.value.size;
  // window.confirm 兜底 — 复杂的 ConfirmModal 后续可以替换;这里要求
  // 显式确认是因为删除不可恢复(后端 hard delete + cascade)。
  if (!window.confirm(`确定删除选中的 ${n} 条视频?此操作不可恢复。`)) return;
  bulkDeleteBusy.value = true;
  try {
    const ids = Array.from(selected.value);
    const deleted = await store.bulkDeleteVideos(ids);
    toast.success(`已删除 ${deleted} 条`);
    selected.value = new Set();
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("批量删除失败" + (detail ? "：" + detail : ""));
  } finally {
    bulkDeleteBusy.value = false;
  }
}

onMounted(async () => {
  await Promise.all([
    store.refreshLoginStatus(),
    store.loadJobs(),
  ]);
  // Auto-select the most recent task so the right column has data on entry.
  // 后端 list_jobs 已按 id DESC 排,jobs[0] 是最新一条。
  if (store.jobs.length > 0) {
    await store.selectJob(store.jobs[0].id);
  } else {
    await store.refreshVideos();
  }
});
</script>

<template>
  <div
    class="anim-up flex flex-col"
    :style="{
      gap: 'var(--density-gap)',
      height: '100%',
      minHeight: 0,
      overflow: 'hidden',
    }"
  >
    <!-- Simplified header — only title + 当前任务关键词。导出 CSV 移到下面
         filter 行的搜索框左侧,跟筛选控件并排,更顺手。 -->
    <header style="flex-shrink: 0;">
      <div class="text-[11px] tracking-[1.5px] uppercase" style="color: var(--ink-3)">
        Outreach · 引流
      </div>
      <div class="flex items-baseline gap-2.5 mt-2 flex-wrap">
        <div class="font-display font-bold" style="font-size: 30px; letter-spacing: -0.5px;">
          视频抓取
        </div>
        <span
          v-if="currentJobKeyword"
          class="text-[15px]"
          style="color: var(--ink-3); font-weight: 500;"
        >
          「{{ currentJobKeyword }}」
        </span>
      </div>
    </header>

    <!-- Two-column body (fills remaining space; each column scrolls independently) -->
    <div
      :style="{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        gap: 'var(--density-gap)',
      }"
    >
      <!-- Left: task list panel -->
      <TaskListPanel
        :jobs="store.jobs"
        :current-job-id="store.currentJobId"
        :running-job-id="store.activeJob?.id ?? null"
        :has-running-job="store.hasRunningJob"
        @select="onSelectJob"
        @new="showNewTask = true"
      />

      <!-- Right column: filter row + grid (bulk toolbar floats absolute,
           anchored at bottom-center via position: relative on this wrapper) -->
      <div
        :style="{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
          position: 'relative',
        }"
      >
        <!-- Filter row -->
        <div class="flex items-center justify-between gap-3 flex-wrap" style="flex-shrink: 0;">
          <div class="flex items-center gap-2 flex-wrap">
            <!-- Status pivot (待评论/已评论/全部) -->
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

            <!-- Platform pivot -->
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
            <!-- Export CSV (left of search,跟筛选控件同行) -->
            <a
              :href="store.exportUrl()"
              download="mining_videos.csv"
              class="inline-flex items-center gap-1.5 text-[11.5px] font-medium"
              style="height: 34px; padding: 0 14px; background: var(--card); border: 1px solid var(--line); border-radius: 999px; color: var(--ink-2); text-decoration: none;"
            >
              <Icon name="download" :size="12"/> 导出 CSV
            </a>

            <!-- Search -->
            <div class="flex items-center" style="height: 34px; background: var(--card); border: 1px solid var(--line); border-radius: 999px; padding: 0 12px; width: 220px;">
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

        <!-- Bulk-selection toolbar — floats at bottom-center of the right
             column (absolute against the column wrapper above). z-index 高于
             卡片网格,scroll 时不动。
             ⚠ 用 anim-in 不是 anim-up:anim-up 的 keyframe 收尾 transform:
             translateY(0) 会覆盖这里 inline 的 translateX(-50%),导致水平
             居中失效。anim-in 只动 opacity,无副作用。 -->
        <div
          v-if="selected.size > 0"
          class="anim-in"
          :style="{
            position: 'absolute',
            bottom: '14px',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 25,
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            background: 'var(--dark)',
            color: '#fbf7ec',
            borderRadius: '999px',
            padding: '6px 6px 6px 16px',
            boxShadow: '0 14px 30px -10px rgba(28,26,23,0.5)',
          }"
        >
          <span class="text-[12.5px]" style="white-space: nowrap;">
            已选 <b class="font-display" style="color: var(--primary)">{{ selected.size }}</b> 条
          </span>
          <span style="width: 1px; height: 16px; background: rgba(255,255,255,0.14);"/>
          <button
            @click="toggleSelectAll"
            class="inline-flex items-center gap-1.5 text-[12px] font-medium"
            :style="{
              height: '30px',
              padding: '0 12px',
              borderRadius: '999px',
              background: 'rgba(255,255,255,0.08)',
              color: '#fbf7ec',
              border: 'none',
              cursor: 'pointer',
            }"
          >
            <Icon name="check" :size="12"/>
            {{ isAllSelected ? '取消全选' : `全选 (${filtered.length})` }}
          </button>
          <button
            :disabled="bulkDeleteBusy"
            @click="onBulkDelete"
            class="inline-flex items-center gap-1.5 text-[12px] font-medium"
            :style="{
              height: '30px',
              padding: '0 14px',
              borderRadius: '999px',
              background: bulkDeleteBusy ? 'rgba(196,68,57,0.55)' : 'var(--red)',
              color: '#fff',
              border: 'none',
              cursor: bulkDeleteBusy ? 'wait' : 'pointer',
            }"
          >
            <Icon name="trash" :size="12"/>
            {{ bulkDeleteBusy ? '删除中…' : '删除' }}
          </button>
          <button
            :disabled="bulkMarkBusy"
            @click="onBulkMarkCommented"
            class="inline-flex items-center gap-1.5 text-[12px] font-medium"
            :style="{
              height: '30px',
              padding: '0 14px',
              borderRadius: '999px',
              background: bulkMarkBusy ? 'rgba(238,106,42,0.55)' : 'var(--primary)',
              color: '#fbf7ec',
              border: 'none',
              cursor: bulkMarkBusy ? 'wait' : 'pointer',
            }"
          >
            <Icon name="check" :size="12"/>
            {{ bulkMarkBusy ? '标记中…' : '标记为已评论' }}
          </button>
          <button
            @click="selected = new Set()"
            class="inline-flex items-center justify-center"
            :style="{
              width: '30px', height: '30px', borderRadius: '999px',
              background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.55)',
              border: 'none', cursor: 'pointer', marginLeft: 'auto',
            }"
          >
            <Icon name="x" :size="12"/>
          </button>
        </div>

        <!-- Video grid (internal scroll region) -->
        <div
          :style="{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            paddingRight: '6px',
            marginRight: '-6px',
            paddingBottom: '40px',
          }"
        >
          <div
            v-if="filtered.length > 0"
            class="grid"
            style="grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px;"
          >
            <VideoCard
              v-for="v in filtered"
              :key="v.id"
              :v="v"
              :selected="selected.has(v.id)"
              @toggle-select="toggleSelect"
            />
          </div>
          <div
            v-else
            class="flex flex-col items-center text-center"
            :style="{
              padding: '60px 30px',
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-card)',
            }"
          >
            <span style="width: 54px; height: 54px; border-radius: 16px; background: var(--card-2); color: var(--ink-3); display: inline-flex; align-items: center; justify-content: center;">
              <Icon name="video" :size="22"/>
            </span>
            <div class="font-display font-bold mt-4" style="font-size: 18px;">没有匹配的视频</div>
            <div class="text-[12.5px] mt-1.5" style="color: var(--ink-3); max-width: 420px;">
              换个筛选,或者起一个新任务再抓一批。
            </div>
            <div class="flex items-center gap-2 mt-5">
              <Btn
                variant="ghost"
                @click="tab = 'all'; platform = 'all'; store.filters.q = ''; store.refreshVideos();"
              >清除筛选</Btn>
              <Btn variant="solid" :disabled="store.hasRunningJob" @click="showNewTask = true">
                <Icon name="plus" :size="12"/> 新建任务
              </Btn>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal -->
    <StartJobModal
      v-model:open="showNewTask"
      :login-status="store.loginStatus"
      @submit="onStartSubmit"
    />
  </div>
</template>
