<script setup lang="ts">
/**
 * 左栏任务列表里的一项。
 *
 * 视觉：
 *   - 选中态：浅色背景 + 左侧 3px 橙色竖条
 *   - 「抓取中」状态额外在底部展示进度条
 *   - 状态 pill 跟 job.status 映射到颜色 + 文案
 *
 * 数据来源：
 *   - keyword / status / progress / platforms / started_at 都来自 MiningJob
 *   - 累计抓取数取 progress 里所有平台 got 之和(实际持久化的 video 数会被
 *     dedup 影响略低,这里展示用够准)
 */
import { computed, onUnmounted, ref, watch } from "vue";
import Icon from "@/components/ui/Icon.vue";
import type { MiningJob, Platform } from "@/stores/mining";

const props = defineProps<{
  job: MiningJob;
  selected: boolean;
  /** True if this job is the one currently in flight (SSE-driven). */
  running: boolean;
}>();

const emit = defineEmits<{
  (e: "select"): void;
  /** 任务的 ⋯ 菜单 → 导出 CSV：让父组件用 store.exportUrl() 触发下载 */
  (e: "export", id: number): void;
  /** 任务的 ⋯ 菜单 → 删除任务：让父组件 confirm + store.deleteJob 处理 */
  (e: "delete", id: number): void;
  /** 运行中的任务点「停止」按钮 → 父组件 store.cancelActive() */
  (e: "cancel", id: number): void;
  /** 任务的 ⋯ 菜单 → 同步到监控：让父组件打开 SyncToMonitorModal */
  (e: "sync", id: number): void;
}>();

// ⋯ 下拉菜单：点击 ⋯ 切换；点 outside 自动关；滚动 / 窗口尺寸变也自动关。
//
// 原本菜单 `class="absolute z-30"` 锚在 ⋯ 按钮父 span 上，但左栏 aside
// 有 `overflow: hidden`、列表 body 又 `overflowY: auto` —— 菜单一旦
// 伸出行就被裁掉，用户看到的就是"弹窗在区块里、被遮挡"那张截图。
//
// 修法：把菜单 Teleport 到 body，position: fixed + 从触发按钮的
// getBoundingClientRect 算坐标。这样不再受任何祖先 overflow 影响，
// 菜单永远完整可见。
const menuOpen = ref(false);
const triggerRef = ref<HTMLButtonElement | null>(null);
const menuPos = ref({ top: 0, right: 0 });

function recomputeMenuPos() {
  const el = triggerRef.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  menuPos.value = {
    top: rect.bottom + 4,                   // 4px gap below the ⋯ button
    right: window.innerWidth - rect.right,  // right-align menu to button's right edge
  };
}

function toggleMenu(ev: MouseEvent) {
  ev.stopPropagation();
  if (!menuOpen.value) recomputeMenuPos();
  menuOpen.value = !menuOpen.value;
}
function closeMenu() { menuOpen.value = false; }
function onWindowChange() {
  // 任何滚动 / resize 都直接关 —— recompute 在不同 transformed ancestor
  // 之间容易飘位，关掉让用户再点一次比"菜单跟错位置"友好。
  if (menuOpen.value) menuOpen.value = false;
}
watch(menuOpen, (open) => {
  if (open) {
    setTimeout(() => window.addEventListener("click", closeMenu), 0);
    window.addEventListener("scroll", onWindowChange, true);
    window.addEventListener("resize", onWindowChange);
  } else {
    window.removeEventListener("click", closeMenu);
    window.removeEventListener("scroll", onWindowChange, true);
    window.removeEventListener("resize", onWindowChange);
  }
});
onUnmounted(() => {
  window.removeEventListener("click", closeMenu);
  window.removeEventListener("scroll", onWindowChange, true);
  window.removeEventListener("resize", onWindowChange);
});

function onExportClick(ev: MouseEvent) {
  ev.stopPropagation();
  menuOpen.value = false;
  emit("export", props.job.id);
}
function onDeleteClick(ev: MouseEvent) {
  ev.stopPropagation();
  menuOpen.value = false;
  emit("delete", props.job.id);
}

function onSyncClick(ev: MouseEvent) {
  ev.stopPropagation();
  menuOpen.value = false;
  emit("sync", props.job.id);
}

function onCancelClick(ev: MouseEvent) {
  ev.stopPropagation();
  emit("cancel", props.job.id);
}

const PLATFORM_META: Record<Platform, { letter: string; color: string }> = {
  bilibili: { letter: "B", color: "#fb7299" },
  douyin: { letter: "D", color: "#1c1a17" },
  kuaishou: { letter: "K", color: "#ff6633" },
};

// ── 状态语义（用户重构 2026-05）────────────────────────────────
// 旧逻辑：直接映射后端 job.status → 等待/抓取中/完成/失败/取消/中断
// 新逻辑（按用户要求）：
//   失败    —— 抓取层面失败（job.status ∈ failed/cancelled/interrupted）
//   抓取中  —— job 正在跑（running，UI 已有 spinner + 进度条）
//   等待    —— pending（很少见到，dispatch 立刻就 running）
//   进行中  —— 抓取成功（done/partial_done），但还有视频用户没评论
//             （commented_count < video_count）
//   已完成  —— 抓取成功 + 该 job 关联的全部视频都 already_commented=1
// video_count == 0 时（抓取成功但 0 视频）fallback 到「完成」原色，
// 避免"已完成 0 条"的歧义。
type DerivedStatus = "pending" | "running" | "captcha_waiting" | "failed" | "in_progress" | "fully_completed" | "done_empty";

const STATUS_LABEL: Record<DerivedStatus, string> = {
  pending: "等待",
  running: "抓取中",
  // v0.5.6: 抖音/快手撞 captcha 时浏览器留开等用户手解。这个 state 期间
  // backend job.status 仍是 "running"，但某个 platform progress.phase
  // 报 "captcha_waiting"，前端据此换 chip 文案/颜色。
  captcha_waiting: "需验证",
  failed: "失败",
  in_progress: "进行中",
  fully_completed: "已完成",
  done_empty: "完成",
};

const STATUS_TONE: Record<DerivedStatus, { bg: string; fg: string }> = {
  pending: { bg: "rgba(var(--ink-rgb),0.08)", fg: "var(--ink-3)" },
  running: { bg: "rgba(238,106,42,0.16)", fg: "#b34d12" },
  // 需验证：紫色 — 跟 抓取中 / 失败 / 进行中 都拉开（用户一眼能区分"轮到我操作了"）
  captcha_waiting: { bg: "rgba(124,77,180,0.18)", fg: "#5a3e8c" },
  failed: { bg: "rgba(196,68,57,0.16)", fg: "var(--red)" },
  // 进行中：黄色（暖告知"等用户操作"，跟 抓取中 的橙红区分开）
  in_progress: { bg: "rgba(245,192,66,0.20)", fg: "#7a5400" },
  // 已完成：绿色，跟旧 done 同色
  fully_completed: { bg: "rgba(96,138,72,0.18)", fg: "#4d6b2f" },
  done_empty: { bg: "rgba(96,138,72,0.18)", fg: "#4d6b2f" },
};

const derivedStatus = computed<DerivedStatus>(() => {
  const raw = props.job.status;
  // 抓取层失败 / 用户取消 / 进程意外中断 → 一律「失败」
  if (raw === "failed" || raw === "cancelled" || raw === "interrupted") {
    return "failed";
  }
  if (raw === "running") {
    // 任一平台 phase = captcha_waiting → 整个任务卡片切到「需验证」
    // chip。backend 在 douyin_search 等了用户在浏览器里手解 captcha 期间
    // 一直发 captcha_waiting progress，解掉后自动回 scrolling。
    const phases = Object.values(props.job.progress ?? {});
    if (phases.some(p => p?.phase === "captcha_waiting")) {
      return "captcha_waiting";
    }
    return "running";
  }
  if (raw === "pending") return "pending";
  // done / partial_done —— 抓取层 OK，看用户评论进度
  const total = props.job.video_count ?? 0;
  const commented = props.job.commented_count ?? 0;
  if (total === 0) return "done_empty";      // 抓到 0 视频的边角，显示「完成」
  if (commented >= total) return "fully_completed";
  return "in_progress";
});

// 任务行有 captcha 等待时，给 status pill 加 native :title tooltip 显示
// 「请在浏览器手解」提示，避免用户以为程序卡死。
const statusTitle = computed(() => {
  if (derivedStatus.value !== "captcha_waiting") return undefined;
  const phases = Object.values(props.job.progress ?? {});
  const waiting = phases.find(p => p?.phase === "captcha_waiting");
  return waiting?.note || "请在弹出的浏览器中手动完成验证";
});

const status = derivedStatus; // 兼容下面 isRunning 引用
const isRunning = computed(() => props.running || props.job.status === "running");

const totalGot = computed(() => {
  // Sum got across all platforms in the progress map.
  let n = 0;
  for (const plat of props.job.platforms) {
    const pp = props.job.progress?.[plat];
    if (pp?.got) n += pp.got;
  }
  return n;
});

// 任务卡徽章「· N 条」的数字：
//   抓取中 —— 实时抓取进度 totalGot（视频还在陆续入库，video_count 会滞后）
//   已完成 —— video_count（当前实际剩余视频数，后端已过滤用户删除的 excluded）
// 用户抓取后删掉一批视频时，徽章按实际剩余数显示，不再停留在抓取时的总数。
const displayCount = computed(() =>
  isRunning.value ? totalGot.value : (props.job.video_count ?? totalGot.value),
);

const totalTarget = computed(() => {
  let n = 0;
  for (const plat of props.job.platforms) {
    const pp = props.job.progress?.[plat];
    if (pp?.target) n += pp.target;
  }
  // Fallback to target_per_platform × platforms.length if progress missing.
  return n || props.job.target_per_platform * props.job.platforms.length;
});

const progressPct = computed(() => {
  if (totalTarget.value === 0) return 0;
  return Math.min(100, (totalGot.value / totalTarget.value) * 100);
});

const dateLabel = computed(() => {
  const src = props.job.started_at || props.job.created_at;
  if (!src) return "";
  const d = new Date(src);
  if (isNaN(d.getTime())) return "";
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${m}月${day}日 ${hh}:${mm}`;
});

const statusLabel = computed(() => STATUS_LABEL[status.value] || status.value);
const statusTone = computed(() => STATUS_TONE[status.value] || STATUS_TONE.pending);

// keyword 截前 6 字 —— Array.from 走 grapheme 切分（emoji/ZWJ 安全）。
// 完整文本通过 :title 给 native tooltip（hover 1-2s 弹出）兜底。
const KEYWORD_MAX = 6;
const keywordShort = computed(() => {
  const k = props.job.keyword || "";
  const chars = Array.from(k);
  return chars.length > KEYWORD_MAX ? chars.slice(0, KEYWORD_MAX).join("") + "…" : k;
});
</script>

<template>
  <button
    type="button"
    @click="$emit('select')"
    :style="{
      position: 'relative',
      display: 'block',
      width: '100%',
      textAlign: 'left',
      padding: '13px 14px 14px 17px',
      background: selected ? 'var(--card-2)' : 'transparent',
      border: 'none',
      borderRadius: '12px',
      cursor: 'pointer',
      overflow: 'hidden',
    }"
  >
    <!--
      原选中态橙色竖条按用户要求移除 —— 选中态已经靠
      `background: var(--card-2)`（见外层 button style）显示了，竖条
      重复又抢眼。
    -->

    <!-- Row 1: keyword + status pill + ⋯ menu -->
    <div class="flex items-center justify-between gap-2">
      <!--
        keyword 显示前 6 字，超过省略 …。`title` 属性给浏览器 native
        tooltip（约 1-2s 悬停延迟，符合用户要"鼠标停留 2 秒浮动显示完整
        标题"的需求）。Array.from grapheme 切分，emoji/中文混排都安全。
      -->
      <span
        class="font-display font-semibold text-[13.5px] flex-shrink"
        style="color: var(--ink); flex: 1; min-width: 0;"
        :title="job.keyword"
      >
        {{ keywordShort }}
      </span>
      <span
        class="inline-flex items-center gap-1 flex-shrink-0"
        :style="{
          fontSize: '10.5px',
          fontWeight: 600,
          padding: '2px 8px',
          borderRadius: '999px',
          background: statusTone.bg,
          color: statusTone.fg,
        }"
        :title="statusTitle"
      >
        <span
          v-if="isRunning"
          :style="{
            width: '5px', height: '5px', borderRadius: '999px',
            background: 'currentColor',
            animation: 'tlpulse 1.4s ease-in-out infinite',
          }"
        />
        {{ statusLabel }}
      </span>
      <!--
        运行中显示「停止」按钮 —— 红色 chip，点击 emit 'cancel' 给父组件
        调 store.cancelActive()。修复用户反馈"评论视频抓取任务无法取消"
        （之前 UI 根本没有停止按钮，cancelActive 函数 export 但没人调用）。
        点击不触发外层 select（stopPropagation）。
      -->
      <button
        v-if="isRunning"
        type="button"
        class="inline-flex items-center gap-1 flex-shrink-0 transition"
        :style="{
          fontSize: '10.5px',
          fontWeight: 600,
          padding: '2px 8px',
          borderRadius: '999px',
          background: 'rgba(216,90,72,0.12)',
          color: 'var(--red, #c44)',
          border: '1px solid rgba(216,90,72,0.3)',
          cursor: 'pointer',
        }"
        title="停止本次抓取（已抓的数据保留）"
        @click="onCancelClick"
        @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'rgba(216,90,72,0.2)')"
        @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'rgba(216,90,72,0.12)')"
      >
        <Icon name="x" :size="10" />
        停止
      </button>
      <!--
        ⋯ 按钮按用户要求每行都显示（不再限定 selected 才出）。未选中态
        颜色压浅一档（透明背景 + ink-4），跟标题/状态 pill 拉开层级；
        选中态保留 card 背景 + ink-3。stopPropagation 阻止点击触发外层 select。
      -->
      <span style="flex-shrink: 0;">
        <button
          ref="triggerRef"
          type="button"
          class="inline-flex items-center justify-center transition"
          :style="{
            width: '22px', height: '22px', borderRadius: '999px',
            background: selected ? 'var(--card)' : 'transparent',
            color: selected ? 'var(--ink-3)' : 'var(--ink-4)',
            border: selected ? '1px solid var(--line)' : '1px solid transparent',
            cursor: 'pointer',
          }"
          title="更多"
          @click="toggleMenu"
          @mouseenter="(e) => { if (!selected) { (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; (e.currentTarget as HTMLElement).style.color = 'var(--ink-3)'; } }"
          @mouseleave="(e) => { if (!selected) { (e.currentTarget as HTMLElement).style.background = 'transparent'; (e.currentTarget as HTMLElement).style.color = 'var(--ink-4)'; } }"
        ><Icon name="more" :size="12" /></button>
      </span>
      <!--
        菜单 Teleport 到 body —— 跳出左栏 aside 的 overflow:hidden 和
        body 列表的 overflow-y:auto，position:fixed 用 trigger 的
        getBoundingClientRect 算坐标，永远完整可见、不会被裁。
        click.stop 阻止本菜单内的点击冒泡到 window 关掉菜单本身。
      -->
      <Teleport to="body">
        <div
          v-if="menuOpen"
          :style="{
            position: 'fixed',
            top: menuPos.top + 'px',
            right: menuPos.right + 'px',
            minWidth: '140px',
            background: 'var(--card-white)',
            border: '1px solid var(--line-2)',
            borderRadius: '10px',
            boxShadow: '0 10px 30px -8px rgba(var(--ink-rgb),0.25)',
            padding: '4px',
            zIndex: 9999,
          }"
          @click.stop
        >
          <button
            type="button"
            class="flex w-full items-center gap-2 text-left"
            :style="{
              height: '30px', padding: '0 10px', borderRadius: '7px',
              fontSize: '12px', color: 'var(--ink)', background: 'transparent', cursor: 'pointer',
            }"
            @mouseenter="($event.currentTarget as HTMLElement).style.background = 'var(--card-2)'"
            @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
            @click="onExportClick"
          >
            <Icon name="download" :size="12" />
            <span>导出 CSV</span>
          </button>
          <button
            type="button"
            :disabled="job.status !== 'done' && job.status !== 'partial_done'"
            class="flex w-full items-center gap-2 text-left"
            :style="{
              height: '30px', padding: '0 10px', borderRadius: '7px',
              fontSize: '12px',
              color: (job.status === 'done' || job.status === 'partial_done') ? 'var(--ink)' : 'var(--ink-4)',
              background: 'transparent',
              cursor: (job.status === 'done' || job.status === 'partial_done') ? 'pointer' : 'not-allowed',
              opacity: (job.status === 'done' || job.status === 'partial_done') ? 1 : 0.45,
            }"
            @mouseenter="($event.currentTarget as HTMLElement).style.background = (job.status === 'done' || job.status === 'partial_done') ? 'var(--card-2)' : 'transparent'"
            @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
            @click="onSyncClick"
          >
            <Icon name="upload" :size="12" />
            <span>同步到监控</span>
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-2 text-left"
            :style="{
              height: '30px', padding: '0 10px', borderRadius: '7px',
              fontSize: '12px', color: 'var(--red, #c0392b)', background: 'transparent', cursor: 'pointer',
            }"
            @mouseenter="($event.currentTarget as HTMLElement).style.background = 'rgba(192,57,43,0.08)'"
            @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
            @click="onDeleteClick"
          >
            <Icon name="trash" :size="12" />
            <span>删除任务</span>
          </button>
        </div>
      </Teleport>
    </div>

    <!-- Row 2: platform letter badges + count -->
    <div class="flex items-center gap-1.5 mt-2.5">
      <span
        v-for="p in job.platforms"
        :key="p"
        :style="{
          width: '17px', height: '17px', borderRadius: '5px',
          background: PLATFORM_META[p].color, color: '#fff',
          fontSize: '9.5px', fontWeight: 800,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }"
      >{{ PLATFORM_META[p].letter }}</span>
      <span class="text-[11px]" style="color: var(--ink-3); margin-left: 4px;">
        · {{ displayCount }} 条
      </span>
    </div>

    <!-- Row 3: date -->
    <div class="text-[10.5px] mt-1.5" style="color: var(--ink-4); font-feature-settings: 'tnum';">
      {{ dateLabel }}
    </div>

    <!-- Progress bar (running only) -->
    <div
      v-if="isRunning"
      :style="{
        marginTop: '10px',
        height: '3px',
        background: 'rgba(var(--ink-rgb),0.08)',
        borderRadius: '999px',
        overflow: 'hidden',
      }"
    >
      <div
        :style="{
          height: '100%',
          width: progressPct + '%',
          background: 'linear-gradient(90deg, var(--yellow), var(--primary))',
          borderRadius: '999px',
          transition: 'width .3s ease',
        }"
      />
    </div>
  </button>
</template>

<style scoped>
@keyframes tlpulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
</style>
