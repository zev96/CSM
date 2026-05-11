<script setup lang="ts">
/**
 * Outer paper-card layout — port of CSM-RE1（V1）/src/app.jsx.
 * Hosts the LeftNav + top utility row + router-view + global Toast +
 * 通知 dropdown (bell icon top-right).
 *
 * The "Tweaks" floating panel was removed — the only useful affordance
 * it offered (information density / primary colour) now lives in
 * Settings → 通用 and Settings → 强调色, so a second knob was
 * redundant. radius/density/primary are still loaded from localStorage
 * via `useTweaks()` so existing user preferences survive.
 */
import { computed, onMounted, ref } from "vue";

import Icon from "./components/ui/Icon.vue";
import LeftNav from "./components/LeftNav.vue";
import ToastContainer from "./components/ui/ToastContainer.vue";
import ConfirmModal from "./components/ui/ConfirmModal.vue";
import FailureAlertModal from "./components/ui/FailureAlertModal.vue";
import NotificationDropdown from "./components/ui/NotificationDropdown.vue";
import OnboardingFlow from "./components/OnboardingFlow.vue";
import WindowControls from "./components/WindowControls.vue";
import { useTweaks } from "./composables/useTweaks";
import { useNotifications } from "./composables/useNotifications";
import { useConfig } from "./stores/config";
import { useSidecarReady } from "./composables/useSidecarReady";

const search = ref("");
// Boot tweaks (loads radius/density/primary from localStorage and
// applies CSS). Still needed even though the Tweaks panel is gone —
// SettingsView writes to the same state.
useTweaks();

const notify = useNotifications();
const notifOpen = ref(false);

function toggleNotif() {
  notifOpen.value = !notifOpen.value;
  if (notifOpen.value) notify.markAllRead();
}

// ── 首次启动 onboarding ─────────────────────────────────────
// 显示条件只看一个状态：localStorage 的「已完成」标记。
//
// 之前 bug：还顺带检查 user_name 是否为空，结果欢迎页第 1 步保存姓名
// 后 user_name 立刻非空，整个 onboarding 直接被 unmount —— 用户根本
// 进不到后面 3 步。修法是 dismissed flag 才是唯一开关，user_name 只
// 用来做"已存在用户的静默迁移"（首次启动时如果他已经有名字，自动设
// 标记，下次不再弹）。
const cfg = useConfig();
const { whenReady } = useSidecarReady();
const ONBOARDED_KEY = "csm.onboarded.v1";
const onboardingDismissed = ref(loadDismissed());
const configReady = ref(false);

function loadDismissed(): boolean {
  try {
    return localStorage.getItem(ONBOARDED_KEY) === "1";
  } catch {
    return false;
  }
}

const showOnboarding = computed(
  () => configReady.value && !onboardingDismissed.value,
);

function onOnboardingDone() {
  onboardingDismissed.value = true;
}

onMounted(async () => {
  // ⚠ 必须先 await sidecar bootstrap，再 cfg.load
  //
  // main.ts 里 sidecar.bootstrap() 没 await 就 mount 了 —— 它是
  // async 函数（即便 browser-dev 路径全是同步赋值，也要等一个微任务
  // 才能落地 baseURL/token）。如果 App.vue 直接 cfg.load()，axios 拿
  // 到的 baseURL 还是空字符串，请求打到 localhost:5173/api/config →
  // 404 → cfg.data 留在 null → 整个 UI 显示空白（"账号变回默认 / 模
  // 型空白" 的根因）。
  // whenReady() 会等 sidecar ready 信号；ready 后立刻返回。
  try {
    await whenReady();
  } catch {
    /* sidecar 起不来 —— 让下面的 cfg.load 自己再 throw 一次到 catch */
  }
  if (!cfg.data) {
    try {
      await cfg.load();
    } catch {
      /* 真起不来时静默 —— view 各自的 whenReady + cfg.load 会再试 */
    }
  }
  // 静默迁移：老安装（v0.4 之前已经用过的本地账号）user_name 已经有
  // 值但 localStorage flag 没设过 —— 帮他写一次 flag，下次启动不会
  // 弹 onboarding。只在 boot 时检查一次，不挂 watcher（不然第 1 步
  // submit 完会被自动 dismiss）。
  if (
    !onboardingDismissed.value &&
    cfg.data &&
    (cfg.data.user_name as string | undefined)?.trim()
  ) {
    try {
      localStorage.setItem(ONBOARDED_KEY, "1");
    } catch {
      /* private-mode — fall back to in-memory only */
    }
    onboardingDismissed.value = true;
  }
  configReady.value = true;
});
</script>

<template>
  <!--
    The window IS the card. transparent:true in tauri.conf lets the
    rounded corners show the desktop behind, so we don't render a
    separate "outer canvas" anymore.
  -->
  <div
    class="relative flex overflow-hidden"
    :style="{
      width: '100vw',
      height: '100vh',
      background: 'var(--bg-inner)',
      borderRadius: '14px',
      boxSizing: 'border-box',
      // Top padding gives breathing room below the drag strip / traffic
      // lights so the LeftNav logo and search bar aren't crammed against
      // the window controls.
      paddingTop: '44px',
    }"
  >
    <!--
      Drag strip across the top of the card. Empty space here moves the
      window; double-click toggles maximize. Window controls sit on top
      (z-30 inside WindowControls) and don't drag because their own
      click handlers absorb events.
    -->
    <div
      data-tauri-drag-region
      class="absolute top-0 left-0 right-0 z-20"
      :style="{ height: '44px' }"
    />
    <WindowControls />
    <LeftNav />

      <!--
        main 自身不滚 —— overflow-hidden + flex column。把 utility row
        和 router-view wrapper 当作两段 flex 子项，剩余高度全部交给
        wrapper。HomeView 用 min-h-full 吃满 wrapper、recent 卡内部滚动；
        ArticleView 这种内容自然很长的页面，由 wrapper 自己 overflow-y-auto
        兜底滚动。这样工作台不会出整页外层滚动条，其他视图也照常工作。
      -->
      <main
        class="flex min-w-0 flex-1 flex-col overflow-hidden"
        :style="{ padding: '22px 30px 30px 6px' }"
      >
        <!-- Top utility row -->
        <div class="mb-3 flex items-center justify-end gap-2">
          <div
            class="flex items-center pr-3 pl-3"
            :style="{
              height: '36px',
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: '999px',
              minWidth: '280px',
              color: 'var(--ink-3)',
            }"
          >
            <Icon name="search" :size="14" />
            <input
              v-model="search"
              placeholder="搜索关键词、文档、模板…"
              class="topbar-search flex-1 bg-transparent px-2 text-[12.5px] outline-none"
            />
          </div>
          <!--
            通知铃铛：点击 toggle 下拉面板。badge 只在有未读时显示。
            打开面板的瞬间把所有未读标记为已读 (markAllRead in
            toggleNotif) —— 用户的"打开 = 看过"假设比强迫他们逐条点
            合理。空面板会显示空状态，不会有空白。
          -->
          <div class="relative">
            <button
              title="通知"
              type="button"
              class="relative inline-flex items-center justify-center transition hover:bg-[rgba(28,26,23,0.05)]"
              :style="{
                width: '36px',
                height: '36px',
                borderRadius: 'var(--radius-pill)',
                color: 'var(--ink-2)',
                background: notifOpen ? 'rgba(28,26,23,0.05)' : 'transparent',
              }"
              @click="toggleNotif"
            >
              <Icon name="bell" :size="16" />
              <span
                v-if="notify.unreadCount.value > 0"
                class="absolute"
                :style="{
                  top: '8px',
                  right: '8px',
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: 'var(--red)',
                  boxShadow: '0 0 0 2px var(--bg-inner)',
                }"
              />
            </button>
            <NotificationDropdown :open="notifOpen" @close="notifOpen = false" />
          </div>
        </div>

    <!--
      router-view wrapper（min-h-0 flex-1 overflow-y-auto 给 ArticleView
      这种内容长的页面兜底滚动；HomeView 自己 min-h-full 不溢出）。
      暂时不挂 <transition> —— 实测 Tauri 的 WebView2 在某些时机会卡
      在 fade-enter-active 状态没还原成 opacity:1，元素在 DOM 里但视觉
      不可见，导致"切路由空白但 console 无报错"。
      诊断结论：去掉 transition 后能稳定切换 = 确认 transition 是元凶。
      后续如果想要过渡效果，会用 transform 或 v-if 重做，不用 CSS
      opacity transition。
    -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <router-view />
    </div>
      </main>

    <!-- Global toast layer — Teleports to body, sits above everything. -->
    <ToastContainer />
    <!-- Global confirm dialog — singleton, driven by useConfirm.ts. -->
    <ConfirmModal />
    <!-- Global failure alert — singleton, driven by useFailureAlert.ts. -->
    <FailureAlertModal />
    <!--
      首次启动引导（4 步：欢迎 / Vault / 模型 / Skill）。Teleport 到
      body，z-index 100，覆盖所有 view。完成或跳过后 dismissed=true，
      下次启动 localStorage 命中也不会再弹。
    -->
    <OnboardingFlow v-if="showOnboarding" @done="onOnboardingDone" />
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/*
  顶栏搜索框：禁掉全局的 2px 橙色 :focus-visible 描边。外层胶囊已有
  border + 卡片底色作为视觉聚焦反馈，再叠橙圈会变成"双重描边"。
  这个跟 KeywordHero 那个 hero-input 是同一思路。
*/
.topbar-search:focus,
.topbar-search:focus-visible {
  outline: none !important;
  box-shadow: none;
}
</style>
