<script setup lang="ts">
/**
 * Outer paper-card layout — port of CSM-RE1（V1）/src/app.jsx.
 * Hosts the LeftNav + router-view + global Toast. 通知 dropdown 现在
 * 挂在 LeftNav 的设置按钮上方，搜索框已下线。
 *
 * The "Tweaks" floating panel was removed — the only useful affordance
 * it offered (information density / primary colour) now lives in
 * Settings → 通用 and Settings → 强调色, so a second knob was
 * redundant. radius/density/primary are still loaded from localStorage
 * via `useTweaks()` so existing user preferences survive.
 */
import { computed, onMounted, ref } from "vue";

import LeftNav from "./components/LeftNav.vue";
import ToastContainer from "./components/ui/ToastContainer.vue";
import ConfirmModal from "./components/ui/ConfirmModal.vue";
import FailureAlertModal from "./components/ui/FailureAlertModal.vue";
import UpdateAvailableModal from "./components/ui/UpdateAvailableModal.vue";
import Spinner from "./components/ui/Spinner.vue";
import OnboardingFlow from "./components/OnboardingFlow.vue";
import WindowControls from "./components/WindowControls.vue";
import { useTweaks } from "./composables/useTweaks";
import { useConfig } from "./stores/config";
import { useMonitorStatus } from "./stores/monitorStatus";
import { useSidecarReady } from "./composables/useSidecarReady";

// Boot tweaks (loads radius/density/primary from localStorage and
// applies CSS). Still needed even though the Tweaks panel is gone —
// SettingsView writes to the same state.
useTweaks();

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
// 是否真的成功读到过 config。onboarding 的判断只能建立在"确认拿到了
// 配置"之上 —— 拿不到时绝不弹欢迎页（见下方 onMounted 里的冷启动竞态
// 注释）。
const configLoadOk = ref(false);

function loadDismissed(): boolean {
  try {
    return localStorage.getItem(ONBOARDED_KEY) === "1";
  } catch {
    return false;
  }
}

const showOnboarding = computed(
  () => configReady.value && configLoadOk.value && !onboardingDismissed.value,
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
  // ⚠ sidecar 的 handshake 早于 HTTP 就绪：main.py 在 uvicorn.run() *之前*
  // 就 emit_handshake（否则 get_sidecar 会等到超时），所以 sidecar.ready=true
  // 时 /api/config 往往还没开始 accept —— uvicorn 还在跑 lifespan 里的
  // legacy-config / keyring 迁移。冷启动（尤其重装后第一次）这个窗口有好
  // 几秒，第一发 cfg.load 经常 connection refused。
  //
  // 必须轮询重试到真的拿到 config 再判断 onboarding：否则会拿着空数据走
  // 下面的 case A —— user_name 其实在磁盘上，但这一刻没读到，于是没能把
  // 被卸载器清掉的 localStorage flag 补回去，欢迎页就会在每次重装后重复
  // 弹出（"每次重装都要重新输名字" 的根因）。
  for (let attempt = 0; attempt < 30 && !cfg.data; attempt++) {
    try {
      await cfg.load();
    } catch {
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  configLoadOk.value = !!cfg.data;
  // 双向同步 dismissed flag 与 cfg.data.user_name —— 解决两个边角：
  //
  //   A) 老安装升级：user_name 已经在 settings.json 但 localStorage 没
  //      flag → 帮他写 flag，避免再弹 onboarding 烦他。
  //   B) WebView2 localStorage 残留：用户卸载 + 重装后磁盘 settings.json
  //      被清，但 Tauri 的 EBWebView 数据目录不动，老 flag 还在 → 必须
  //      清掉，否则新装的 app 不弹 onboarding。
  //
  // 只在 boot 时检查一次，不挂 watcher（避免第 1 步 submit 完 user_name
  // 一变就把整个 OnboardingFlow unmount，第 2 步永远进不去）。
  const userName = (cfg.data?.user_name as string | undefined)?.trim();
  if (cfg.data && userName && !onboardingDismissed.value) {
    // 情况 A：补 flag
    try { localStorage.setItem(ONBOARDED_KEY, "1"); } catch { /* private-mode */ }
    onboardingDismissed.value = true;
  } else if (cfg.data && !userName && onboardingDismissed.value) {
    // 情况 B：清掉 stale flag
    try { localStorage.removeItem(ONBOARDED_KEY); } catch { /* private-mode */ }
    onboardingDismissed.value = false;
  }
  // Boot the monitor-status store ONCE at app start. It owns the SSE
  // subscription + periodic /running hydration, so monitor pages can
  // navigate in/out without losing track of in-flight scrapes.
  try {
    useMonitorStatus().start();
  } catch (e) {
    /* sidecar 没起来时 store.start() 内部会静默 —— 走 ready 之后 hydrate 兜底 */
  }
  configReady.value = true;
  // 启动后静默检查更新：有新版本自动弹 UpdateAvailableModal；已「跳过」的版本不弹。
  // fire-and-forget —— 不阻塞 UI；检查失败静默（仅设置页手动检查才提示）。
  import("./composables/useUpdateFlow")
    .then(({ runUpdateCheck }) => runUpdateCheck({ silent: true }))
    .catch(() => {});
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
      borderRadius: '24px',
      boxSizing: 'border-box',
      // 不再在 root 加 paddingTop —— LeftNav 用 paddingTop:62 给 logo
      // 留位置（44 drag strip + 18 原来的），main 用 paddingTop:66 给
      // drag-strip 让出空间；这样 LeftNav 背景从 y=0 开始，毛玻璃覆盖
      // 整个左侧高度（用户要求）。
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

    <!--
      在 cfg.load 完成（configReady=true）之前，**不渲染** LeftNav + main。
      之前的做法是先把空主界面闪一下、cfg 加载完再让 OnboardingFlow 盖
      上去 —— 视觉上是"主页 2 秒 → 切换到登录"，用户觉得不对。
      改成: configReady 之前显示一个居中的 spinner（splash），configReady
      之后再渲染主壳；如果 user_name 是空则 OnboardingFlow 直接覆盖。
      用户看到的就只剩"splash → 登录页"或"splash → 主页"两种情况之一。
    -->
    <div
      v-if="!configReady"
      class="absolute inset-0 z-20 flex items-center justify-center"
      :style="{ background: 'var(--bg-inner)', paddingTop: '44px' }"
    >
      <Spinner :size="22" />
    </div>

    <template v-else>
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
        :style="{ padding: '66px 30px 30px 30px' }"
      >
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
    </template>

    <!-- Global toast layer — Teleports to body, sits above everything. -->
    <ToastContainer />
    <!-- Global confirm dialog — singleton, driven by useConfirm.ts. -->
    <ConfirmModal />
    <!-- Global failure alert — singleton, driven by useFailureAlert.ts. -->
    <FailureAlertModal />
    <!-- 发现新版本弹窗 — singleton, driven by useUpdateAlert.ts. -->
    <UpdateAvailableModal />
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
</style>
