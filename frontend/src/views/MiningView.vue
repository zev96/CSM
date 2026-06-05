<script setup lang="ts">
/**
 * 视频抓取页 — 三栏布局（refactor from 双栏）。
 *
 *   ┌────────────────────────────────────────────────────────────────────────┐
 *   │ OUTREACH · 引流                                                        │
 *   │ 视频抓取  「当前任务关键词」                                            │
 *   ├──────────────┬────────────────────────┬───────────────────────────────┤
 *   │ 抓取任务      │ 视频列表 · N 条        │ <平台 chip> <pill> <⋯ menu>   │
 *   │ (260)        │ 待评论/已评论/全部     │ 大标题                         │
 *   │  - keyword   │ 全部/B站/抖音/快手     │ 时长/播放/点赞                 │
 *   │  - 选中     │ ─────────────────────  │ ──────────────────────────────│
 *   │     ⋯ menu  │ □ 平台 视频标题 状态pill│ AI 速览                       │
 *   │   导出 CSV  │ □ ... ... ...           │ ──────────────────────────────│
 *   │   删除任务  │ □ ... ... ...           │ 评论楼 (flex-1 自动撑高)      │
 *   │  - status    │                        │   FloorList                   │
 *   │  - progress  │ ── 浮动 toolbar:       │ ──────────────────────────────│
 *   │ (260)        │ 全选 | 删除 | 标记已  │ CommentComposer (sticky bottom)│
 *   │              │ 评论 | x  (中下浮)    │                                │
 *   └──────────────┴────────────────────────┴───────────────────────────────┘
 *
 * 状态：
 *   - tab / platform / filters → 中栏 SubtaskListPanel 用
 *   - selectedVideoId → 右栏 VideoDetailPanel 用；切 job 自动选第一条
 *   - selected (Set) → 浮动 toolbar 用，bulk delete / mark commented 共享
 *
 * 关键交互：
 *   - 选 job → store.selectJob(id) → videos refresh → auto-pick 首条视频
 *   - 选 video（中栏行点击）→ 仅切 selectedVideoId，右栏面板换内容
 *   - checkbox（中栏行）→ selected.add/remove，浮动 toolbar 可见
 *   - 左栏 ⋯ → 导出 CSV（exportUrl 用 filters.job_id，必为当前 job）
 *           → 删除任务（store.deleteJob，后端未支持时 toast 提示）
 */
import { ref, computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import Icon from "@/components/ui/Icon.vue";
import StartJobModal from "@/components/mining/StartJobModal.vue";
import SyncToMonitorModal from "@/components/mining/SyncToMonitorModal.vue";
import TaskListPanel from "@/components/mining/TaskListPanel.vue";
import SubtaskListPanel from "@/components/mining/SubtaskListPanel.vue";
import VideoDetailPanel from "@/components/mining/VideoDetailPanel.vue";
import { useMiningStore, type Platform } from "@/stores/mining";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const store = useMiningStore();
const toast = useToast();
const route = useRoute();

const showNewTask = ref(false);
const prefillKeyword = ref("");
const prefillSource = ref("");

const syncModalVisible = ref(false);
const syncModalJobId = ref<number | null>(null);
const syncModalKeyword = ref('');

// 默认显示「全部」+「全部平台」—— 用户进页面第一眼想看完整的视频清单，
// 而不是被 unread 过滤掉一半。要看待评论时手动切下拉。
const tab = ref<"unread" | "done" | "all">("all");
const platform = ref<"all" | Platform>("all");
const selected = ref(new Set<number>());
const bulkMarkBusy = ref(false);
const bulkDeleteBusy = ref(false);

// 右栏：当前查看的视频 id。`selectVideo` 切换；切 job 时 watch 重置为
// 第一条视频；视频列表变化（删除/筛选）时如果当前选中已不在列表，
// 自动 fallback 到列表首条。
const selectedVideoId = ref<number | null>(null);

// counts 已下线 —— 状态 pivot 改成 FormSelect 后不再带数字徽章；中栏
// header "共 N 条" 直接取 videos.length。

const filtered = computed(() => {
  return store.videos.filter((v) => {
    if (tab.value === "unread" && v.already_commented) return false;
    if (tab.value === "done" && !v.already_commented) return false;
    if (platform.value !== "all" && v.platform !== platform.value) return false;
    return true;
  });
});

const isAllSelected = computed(() =>
  filtered.value.length > 0 && selected.value.size >= filtered.value.length,
);

const selectedVideo = computed(() =>
  selectedVideoId.value != null
    ? store.videos.find((v) => v.id === selectedVideoId.value) ?? null
    : null,
);

// currentJobKeyword 已下线 —— 顶部 header 不再显示「关键词」chip，
// 当前任务关键词在左栏「抓取任务」列表里已经粗体高亮。

// 视频列表变化时维持 selectedVideoId 有效：
//   - 列表为空 → 清空
//   - 当前选中不在列表中 → 选首条
//   - 否则保持不动
watch(
  filtered,
  (list) => {
    if (list.length === 0) {
      selectedVideoId.value = null;
      return;
    }
    if (
      selectedVideoId.value == null
      || !list.some((v) => v.id === selectedVideoId.value)
    ) {
      selectedVideoId.value = list[0].id;
    }
  },
  { immediate: true },
);

function toggleSelect(id: number) {
  const s = new Set(selected.value);
  s.has(id) ? s.delete(id) : s.add(id);
  selected.value = s;
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    selected.value = new Set();
  } else {
    selected.value = new Set(filtered.value.map((v) => v.id));
  }
}

function selectVideo(id: number) {
  selectedVideoId.value = id;
}

async function onSelectJob(id: number) {
  if (store.currentJobId === id) return;
  selected.value = new Set();
  selectedVideoId.value = null; // 让 watch(filtered) 重选首条
  await store.selectJob(id);
}

async function onStartSubmit(payload: { keyword: string; platforms: Platform[]; target: number; brandKeywords: string[] }) {
  showNewTask.value = false;
  try {
    const newJobId = await store.startJob(payload.keyword, payload.platforms, payload.target, payload.brandKeywords);
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
  const ok = await confirmDialog(
    `确定删除选中的 ${n} 条视频?此操作不可恢复。`,
    { title: "批量删除", okLabel: "删除" },
  );
  if (!ok) return;
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

// 左栏 ⋯ 菜单 —— 导出 CSV
//
// 旧路径：隐藏 a 标签 + download 属性触发浏览器下载 —— WebView2 里直接
// 静默落到 Edge 默认 Downloads 目录，用户根本不知道保存到哪。
//
// 新路径：Tauri dialog.save() 弹原生「另存为」让用户选位置 → fetch
// CSV bytes → fs.writeFile 写到指定路径。文件名带任务关键词 + 日期方便
// 一眼分辨。
async function onTaskExport(jobId: number) {
  await store.selectJob(jobId);
  const url = store.exportUrl();
  const job = store.jobs.find((x) => x.id === jobId);
  const keyword = (job?.keyword || "mining").replace(/[\\/:*?"<>|]/g, "_");
  const dateStr = new Date().toISOString().slice(0, 10);
  const defaultName = `${keyword}-${dateStr}.csv`;

  try {
    const isTauri =
      typeof window !== "undefined" &&
      // @ts-expect-error — ambient Tauri global
      Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
    if (!isTauri) {
      // 浏览器 dev 模式 fallback —— 走原 <a download> 路径
      const a = document.createElement("a");
      a.href = url;
      a.download = defaultName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return;
    }
    const { save } = await import("@tauri-apps/plugin-dialog");
    const path = await save({
      defaultPath: defaultName,
      filters: [{ name: "CSV", extensions: ["csv"] }],
    });
    if (!path) return; // 用户取消
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const bytes = new Uint8Array(await resp.arrayBuffer());
    const { writeFile } = await import("@tauri-apps/plugin-fs");
    await writeFile(path, bytes);
    toast.success(`已导出到：${path}`);
  } catch (e: any) {
    toast.error(`导出失败：${e?.message ?? e}`);
  }
}

// 运行中任务的「停止」按钮 —— 调 store.cancelActive() POST
// /api/mining/jobs/{id}/cancel。后端给当前 job 的 cancel_event 置位，
// adapter 在下一个可中断检查点退出。已抓的视频保留。
async function onTaskCancel(jobId: number) {
  // 只能取消当前 active job（mining 单 executor，同时间只跑一个）
  if (store.activeJob?.id !== jobId) {
    toast.warn("该任务不在运行中");
    return;
  }
  const ok = await confirmDialog(
    "停止当前抓取任务？已抓的视频会保留；适配器会在最近的检查点退出（一般 5-15 秒）。",
    { title: "停止抓取", okLabel: "停止" },
  );
  if (!ok) return;
  try {
    await store.cancelActive();
    toast.info("已发送停止信号，正在等待 adapter 退出…");
  } catch (e: any) {
    toast.error(`停止失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

// 左栏 ⋯ 菜单 —— 删除任务
//
// 后端 DELETE /api/mining/jobs/{id} 若未实现会回 404/405，catch 后弹
// 提示让用户知道：UI 已经接好，等后端补路由。
async function onTaskDelete(jobId: number) {
  const j = store.jobs.find((x) => x.id === jobId);
  const label = j?.keyword ? `任务「${j.keyword}」` : `任务 #${jobId}`;
  const ok = await confirmDialog(
    `确定删除${label}？该任务下的视频与评论草稿会一并删除。此操作不可恢复。`,
    { title: "删除任务", okLabel: "删除" },
  );
  if (!ok) return;
  try {
    await store.deleteJob(jobId);
    toast.success("已删除任务");
    // 列表更新由 store.deleteJob 内部处理。若当前选中被删，jobs[0] 还在
    // 时手动切到第一个，给用户一个不空的状态。
    if (store.currentJobId == null && store.jobs.length > 0) {
      await store.selectJob(store.jobs[0].id);
    }
  } catch (e: any) {
    const status = e?.response?.status;
    if (status === 404 || status === 405) {
      toast.error("删除任务接口暂未上线，请等待后端 DELETE /api/mining/jobs/{id} 路由");
    } else {
      const detail = e?.response?.data?.detail as string | undefined;
      toast.error("删除失败" + (detail ? "：" + detail : ""));
    }
  }
}

function openSyncModal(job: { id: number; keyword: string }) {
  syncModalJobId.value = job.id;
  syncModalKeyword.value = job.keyword;
  syncModalVisible.value = true;
}

onMounted(async () => {
  await Promise.all([
    store.refreshLoginStatus(),
    store.loadJobs(),
  ]);
  // route.query.job 由"首页视频抓取卡 → 该任务"链接写入。命中现有 job 时
  // 优先选它；不命中（已删/陈旧链接）静默 fallback 到 jobs[0]。
  const jQ = route.query.job;
  const jobRaw = typeof jQ === "string" ? jQ : Array.isArray(jQ) ? jQ[0] : null;
  const jobId = jobRaw ? Number(jobRaw) : NaN;
  const targetJob =
    Number.isFinite(jobId) && jobId > 0
      ? store.jobs.find((x) => x.id === jobId)
      : null;
  if (targetJob) {
    await store.selectJob(targetJob.id);
  } else if (store.jobs.length > 0) {
    await store.selectJob(store.jobs[0].id);
  } else {
    await store.refreshVideos();
  }

  // GEO 信源榜闭环跳转：若 route 带 geo_keyword，预填关键词并打开新建弹窗。
  // 同时读 geo_source，作为弹窗内的提示（展示用，不过滤）。
  const kw = route.query.geo_keyword;
  if (typeof kw === "string" && kw) {
    prefillKeyword.value = kw;
    const src = route.query.geo_source;
    if (typeof src === "string" && src) {
      prefillSource.value = src;
    }
    showNewTask.value = true;
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
    <!--
      Header —— 按用户要求只保留小字 eyebrow（跟 MonitorView / DataCenterView
      同款）：原 "Outreach · 引流" 文案换成「评论视频」；下方的「视频抓取
      + 当前任务关键词」整段删除（任务关键词在左栏抓取任务列表已经显示）。
    -->
    <header style="flex-shrink: 0;">
      <div
        class="text-[11px] uppercase"
        :style="{ letterSpacing: '1.5px', color: 'var(--ink-3)' }"
      >
        评论视频
      </div>
    </header>

    <!-- Three-column body —— flex-1 撑满；每栏自己管滚动。 -->
    <div
      :style="{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        gap: 'var(--density-gap)',
        position: 'relative',
      }"
    >
      <!-- 左栏：任务列表面板 -->
      <TaskListPanel
        :jobs="store.jobs"
        :current-job-id="store.currentJobId"
        :running-job-id="store.activeJob?.id ?? null"
        :has-running-job="store.hasRunningJob"
        @select="onSelectJob"
        @new="showNewTask = true"
        @export="onTaskExport"
        @delete="onTaskDelete"
        @cancel="onTaskCancel"
        @sync="(id) => { const j = store.jobs.find(x => x.id === id); if (j) openSyncModal(j); }"
      />

      <!--
        中栏：子任务列表 + 浮动 toolbar
        position: relative 给浮动 toolbar 做 absolute 锚点 —— toolbar 浮在
        本栏 bottom-center（用户要求"中下位置"）。toolbar 落在本栏内而不是
        整页底，避免遮挡右栏 composer。
      -->
      <div
        :style="{
          width: '320px',
          flexShrink: 0,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          position: 'relative',
        }"
      >
        <SubtaskListPanel
          :videos="filtered"
          :selected-video-id="selectedVideoId"
          :selected="selected"
          :tab="tab"
          :platform="platform"
          @select-video="selectVideo"
          @toggle-select="toggleSelect"
          @update:tab="(v) => (tab = v)"
          @update:platform="(v) => (platform = v)"
        />

        <!--
          Bulk-selection toolbar — 浮动于中栏 bottom-center。
          只在 selected.size > 0 时显示；不挡列表底部太多，padding 留够
          滚动尾部能看到内容。
        -->
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
            gap: '8px',
            background: 'var(--dark)',
            color: '#fbf7ec',
            borderRadius: '999px',
            padding: '5px 5px 5px 14px',
            boxShadow: '0 14px 30px -10px rgba(28,26,23,0.5)',
            maxWidth: '95%',
          }"
        >
          <span class="text-[11.5px]" style="white-space: nowrap;">
            已选 <b class="font-display" style="color: var(--primary)">{{ selected.size }}</b> 条
          </span>
          <span style="width: 1px; height: 14px; background: rgba(255,255,255,0.14);"/>
          <button
            @click="toggleSelectAll"
            class="inline-flex items-center gap-1 text-[11.5px] font-medium"
            :style="{
              height: '26px', padding: '0 10px', borderRadius: '999px',
              background: 'rgba(255,255,255,0.08)', color: '#fbf7ec',
              border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
            }"
          >
            <Icon name="check" :size="11"/>
            {{ isAllSelected ? '取消全选' : `全选` }}
          </button>
          <button
            :disabled="bulkDeleteBusy"
            @click="onBulkDelete"
            class="inline-flex items-center gap-1 text-[11.5px] font-medium"
            :style="{
              height: '26px', padding: '0 12px', borderRadius: '999px',
              background: bulkDeleteBusy ? 'rgba(196,68,57,0.55)' : 'var(--red)',
              color: '#fff', border: 'none',
              cursor: bulkDeleteBusy ? 'wait' : 'pointer', whiteSpace: 'nowrap',
            }"
          >
            <Icon name="trash" :size="11"/>
            {{ bulkDeleteBusy ? '删除中…' : '删除' }}
          </button>
          <button
            :disabled="bulkMarkBusy"
            @click="onBulkMarkCommented"
            class="inline-flex items-center gap-1 text-[11.5px] font-medium"
            :style="{
              height: '26px', padding: '0 12px', borderRadius: '999px',
              background: bulkMarkBusy ? 'rgba(238,106,42,0.55)' : 'var(--primary)',
              color: '#fbf7ec', border: 'none',
              cursor: bulkMarkBusy ? 'wait' : 'pointer', whiteSpace: 'nowrap',
            }"
          >
            <Icon name="check" :size="11"/>
            {{ bulkMarkBusy ? '标记中…' : '标记已评论' }}
          </button>
          <button
            @click="selected = new Set()"
            class="inline-flex items-center justify-center"
            :style="{
              width: '26px', height: '26px', borderRadius: '999px',
              background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.55)',
              border: 'none', cursor: 'pointer',
            }"
          >
            <Icon name="x" :size="11"/>
          </button>
        </div>
      </div>

      <!-- 右栏：单条视频工作面板 -->
      <VideoDetailPanel
        v-if="selectedVideo"
        :v="selectedVideo"
        :key="selectedVideo.id"
      />
      <section
        v-else
        :style="{
          flex: 1, minWidth: 0, minHeight: 0,
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          padding: '60px 30px',
          color: 'var(--ink-3)',
          fontSize: '12.5px',
          gap: '12px',
          textAlign: 'center',
        }"
      >
        <span
          :style="{
            width: '54px', height: '54px', borderRadius: '16px',
            background: 'var(--card-2)', color: 'var(--ink-3)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }"
        >
          <Icon name="video" :size="22" />
        </span>
        <div class="font-display font-bold" style="font-size: 16px; color: var(--ink-2);">
          没有可显示的视频
        </div>
        <div style="max-width: 360px;">
          左侧任务为空或当前筛选没有匹配视频。换个筛选或起一个新任务再抓一批。
        </div>
      </section>
    </div>

    <!-- Modal -->
    <!--
      不用 v-model:open，改用显式 @update:open：关闭时(v=false)清空
      prefillKeyword/prefillSource，防止手动点「新建任务」时再次预填陈旧值。
    -->
    <StartJobModal
      :open="showNewTask"
      :login-status="store.loginStatus"
      :prefill-keyword="prefillKeyword"
      :prefill-source="prefillSource"
      @update:open="(v: boolean) => { showNewTask = v; if (!v) { prefillKeyword = ''; prefillSource = ''; } }"
      @submit="onStartSubmit"
    />
    <SyncToMonitorModal
      v-model:visible="syncModalVisible"
      :job-id="syncModalJobId"
      :job-keyword="syncModalKeyword"
    />
  </div>
</template>
