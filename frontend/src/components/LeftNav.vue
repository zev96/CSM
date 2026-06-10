<script setup lang="ts">
/**
 * Floating 72px-wide icon nav — port of CSM-RE1（V1）/src/nav.jsx.
 * Uses vue-router for activation; the React prototype's ``onSelect``
 * prop is replaced by ``router.push``.
 *
 * 通知 bell 也住在这里（设置按钮上方），dropdown 从 nav 右侧弹出。
 */
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import Icon from "./ui/Icon.vue";
import NotificationDropdown from "./ui/NotificationDropdown.vue";
import TaskTrayPanel from "./ui/TaskTrayPanel.vue";
import logoUrl from "@/assets/logo.png";
import { useConfig } from "@/stores/config";
import { useNotifications } from "@/composables/useNotifications";
import { useTaskTray } from "@/stores/taskTray";

const route = useRoute();
const router = useRouter();
const cfg = useConfig();

const userName = computed<string>(() => (cfg.data?.user_name as string) || "");
const avatarLetter = computed<string>(
  () => (userName.value || "U").slice(0, 1).toUpperCase(),
);

function gotoAccount() {
  // 复用 SettingsView 的 hash → section 映射（onMounted + watch route.hash），
  // 所以这里 push 一次就够，从其他页或本页内点都能落到「账号」tab。
  router.push({ name: "settings", hash: "#account" }).catch(() => {});
}

// 通知铃铛 + 任务托盘：两个浮层互斥（同时只开一个）。
// 任务托盘挂在 LeftNav（常驻组件）上，让 useTaskTray() 的 watcher
// （最近完成登记、元数据懒加载）从 app 启动起就活着，而不是等浮层首开。
const notify = useNotifications();
const tray = useTaskTray();
const notifOpen = ref(false);
const trayOpen = ref(false);

// 通知铃铛：点击 toggle 下拉面板。打开瞬间标全部已读 ——
// "打开 = 看过" 比强迫逐条点合理。
function toggleNotif() {
  notifOpen.value = !notifOpen.value;
  if (notifOpen.value) {
    trayOpen.value = false;
    notify.markAllRead();
  }
}

function toggleTray() {
  trayOpen.value = !trayOpen.value;
  if (trayOpen.value) {
    notifOpen.value = false;
    void tray.ensureMonitorMeta(true); // 打开时强刷一次任务名缓存
  }
}

const trayBadge = computed(() =>
  tray.runningCount > 9 ? "9+" : String(tray.runningCount),
);

const NAV_TOP = [
  { key: "home", icon: "home", label: "工作台" },
  { key: "article", icon: "edit", label: "创作区" },
  { key: "monitor", icon: "radar", label: "监测中心" },
  { key: "data-center", icon: "fileText", label: "数据中心" },
  { key: "mining", icon: "search", label: "引流" },
  { key: "templates", icon: "library", label: "模板库" },
] as const;

const NAV_BOT = [{ key: "settings", icon: "settings", label: "设置" }] as const;

const active = computed(() => route.name);
function go(key: string) {
  router.push({ name: key });
}
</script>

<template>
  <nav
    class="relative flex flex-col items-center justify-between"
    :style="{
      width: '72px',
      padding: '17px 0 18px 0',
      background: 'rgba(255, 255, 255, 0.35)',
      backdropFilter: 'blur(20px) saturate(150%)',
      WebkitBackdropFilter: 'blur(20px) saturate(150%)',
      borderRight: '1px solid rgba(255, 255, 255, 0.5)',
      zIndex: 30,
    }"
  >
    <div class="flex flex-col items-center gap-2">
      <!--
        应用 Logo —— 单张 PNG，CSM 文字标签同步移除。
        图源放在 frontend/src/assets/logo.png；图片自身保留白底/透明就行，
        外层不再加深色卡片背景了，给品牌色完整展示空间。
      -->
      <div class="mb-2 flex items-center justify-center">
        <img
          :src="logoUrl"
          alt="Content SEO Maker"
          title="Content SEO Maker"
          :style="{
            width: '44px',
            height: '44px',
            borderRadius: '12px',
            objectFit: 'contain',
            display: 'block',
          }"
        />
      </div>

      <div class="mt-3 flex flex-col items-center gap-2">
        <button
          v-for="item in NAV_TOP"
          :key="item.key"
          :title="item.label"
          class="relative inline-flex items-center justify-center transition"
          :style="{
            width: '44px',
            height: '44px',
            borderRadius: '14px',
            background: active === item.key ? 'rgba(255, 255, 255, 0.85)' : 'transparent',
            color: active === item.key ? 'var(--ink)' : 'var(--ink-2)',
            backdropFilter: active === item.key ? 'blur(10px) saturate(140%)' : 'none',
            WebkitBackdropFilter: active === item.key ? 'blur(10px) saturate(140%)' : 'none',
            border: active === item.key ? '1px solid rgba(255, 255, 255, 0.7)' : '1px solid transparent',
            boxShadow: active === item.key
              ? '0 6px 16px -2px rgba(28,26,23,0.12), 0 2px 6px rgba(28,26,23,0.06)'
              : 'none',
          }"
          @mouseenter="(e) => { if (active !== item.key) (e.currentTarget as HTMLElement).style.background = 'rgba(28,26,23,0.05)' }"
          @mouseleave="(e) => { if (active !== item.key) (e.currentTarget as HTMLElement).style.background = 'transparent' }"
          @click="go(item.key)"
        >
          <Icon :name="item.icon" :size="18" />
          <span
            v-if="active === item.key"
            :style="{
              position: 'absolute',
              left: '-12px',
              top: '50%',
              transform: 'translateY(-50%)',
              width: '3px',
              height: '18px',
              borderRadius: '3px',
              background: 'var(--primary)',
            }"
          />
        </button>
      </div>
    </div>

    <div class="flex flex-col items-center gap-2">
      <!--
        任务托盘按钮 —— 铃铛正上方。有任务时数字角标 + 呼吸光圈；
        浮层从 nav 右侧弹出（同 NotificationDropdown 范式）。
      -->
      <div class="relative">
        <button
          title="后台任务"
          type="button"
          class="relative inline-flex items-center justify-center transition"
          :class="{ 'tray-btn-active': tray.runningCount > 0 }"
          :style="{
            width: '44px',
            height: '44px',
            borderRadius: '14px',
            color: tray.runningCount > 0 ? 'var(--primary)' : 'var(--ink-2)',
            background: trayOpen ? 'rgba(28,26,23,0.05)' : 'transparent',
          }"
          @mouseenter="(e) => { if (!trayOpen) (e.currentTarget as HTMLElement).style.background = 'rgba(28,26,23,0.05)' }"
          @mouseleave="(e) => { if (!trayOpen) (e.currentTarget as HTMLElement).style.background = 'transparent' }"
          @click="toggleTray"
        >
          <Icon name="zap" :size="18" />
          <span v-if="tray.runningCount > 0" class="tray-badge absolute">{{ trayBadge }}</span>
        </button>
        <TaskTrayPanel :open="trayOpen" @close="trayOpen = false" />
      </div>
      <!--
        通知 bell —— 放在「设置」按钮正上方。badge 在有未读时显示。
        wrapper relative 给 NotificationDropdown absolute 定位用，
        dropdown 自身往 nav 右侧弹出（覆盖到主内容区上层）。
      -->
      <div class="relative">
        <button
          title="通知"
          type="button"
          class="relative inline-flex items-center justify-center transition"
          :style="{
            width: '44px',
            height: '44px',
            borderRadius: '14px',
            color: 'var(--ink-2)',
            background: notifOpen ? 'rgba(28,26,23,0.05)' : 'transparent',
          }"
          @mouseenter="(e) => { if (!notifOpen) (e.currentTarget as HTMLElement).style.background = 'rgba(28,26,23,0.05)' }"
          @mouseleave="(e) => { if (!notifOpen) (e.currentTarget as HTMLElement).style.background = 'transparent' }"
          @click="toggleNotif"
        >
          <Icon name="bell" :size="18" />
          <span
            v-if="notify.unreadCount.value > 0"
            class="absolute"
            :style="{
              top: '10px',
              right: '10px',
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
      <button
        v-for="item in NAV_BOT"
        :key="item.key"
        :title="item.label"
        class="inline-flex items-center justify-center transition"
        :style="{
          width: '44px',
          height: '44px',
          borderRadius: '14px',
          background: active === item.key ? 'rgba(255, 255, 255, 0.85)' : 'transparent',
          color: active === item.key ? 'var(--ink)' : 'var(--ink-2)',
          backdropFilter: active === item.key ? 'blur(10px) saturate(140%)' : 'none',
          WebkitBackdropFilter: active === item.key ? 'blur(10px) saturate(140%)' : 'none',
          border: active === item.key ? '1px solid rgba(255, 255, 255, 0.7)' : '1px solid transparent',
          boxShadow: active === item.key
            ? '0 6px 16px -2px rgba(28,26,23,0.12), 0 2px 6px rgba(28,26,23,0.06)'
            : 'none',
        }"
        @mouseenter="(e) => { if (active !== item.key) (e.currentTarget as HTMLElement).style.background = 'rgba(28,26,23,0.05)' }"
        @mouseleave="(e) => { if (active !== item.key) (e.currentTarget as HTMLElement).style.background = 'transparent' }"
        @click="go(item.key)"
      >
        <Icon :name="item.icon" :size="18" />
      </button>
      <div class="mt-1" :style="{ width: '40px', height: '1px', background: 'var(--line-2)' }" />
      <!--
        头像按钮 → /settings#account。首字母从 cfg.user_name 取，没设
        过用户名时退回 "U"。鼠标悬停加 cursor + 轻微亮一下，提示是
        可点击的；右下角小绿点保留，纯装饰说明在线。
      -->
      <button
        type="button"
        class="relative inline-flex flex-col items-center justify-center transition"
        :style="{
          width: '40px',
          height: '40px',
          borderRadius: '999px',
          background: 'var(--dark)',
          color: 'var(--primary)',
          fontWeight: 700,
          fontSize: '13px',
          marginTop: '6px',
          cursor: 'pointer',
        }"
        :title="`${userName || '本地用户'} · 打开账号设置`"
        @click="gotoAccount"
        @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.filter = 'brightness(1.15)')"
        @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.filter = 'none')"
      >
        <span>{{ avatarLetter }}</span>
        <span
          :style="{
            position: 'absolute',
            bottom: '-1px',
            right: '-1px',
            width: '10px',
            height: '10px',
            borderRadius: '50%',
            background: '#7a9b5e',
            border: '2px solid var(--bg-inner)',
          }"
        />
      </button>
    </div>
  </nav>
</template>

<style scoped>
.tray-badge {
  top: 5px;
  right: 5px;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 9.5px;
  font-weight: 700;
  line-height: 15px;
  text-align: center;
  box-shadow: 0 0 0 2px var(--bg-inner);
}
@keyframes trayPulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(238, 106, 42, 0.35);
  }
  50% {
    box-shadow: 0 0 0 7px rgba(238, 106, 42, 0);
  }
}
.tray-btn-active {
  animation: trayPulse 2.2s ease-in-out infinite;
}
</style>
