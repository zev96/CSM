<script setup lang="ts">
/**
 * Floating 72px-wide icon nav — port of CSM-RE1（V1）/src/nav.jsx.
 * Uses vue-router for activation; the React prototype's ``onSelect``
 * prop is replaced by ``router.push``.
 */
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import Icon from "./ui/Icon.vue";
import logoUrl from "@/assets/logo.png";
import { useConfig } from "@/stores/config";

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

// 监测中心原本有个红点 (badge: true + alertCount prop)，现在监测告警
// 走右上角铃铛，左侧不再重复出状态指示，badge 字段整个移除。
const NAV_TOP = [
  { key: "home", icon: "home", label: "工作台" },
  { key: "article", icon: "edit", label: "创作区" },
  { key: "monitor", icon: "radar", label: "监测中心" },
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
    class="flex flex-col items-center justify-between"
    :style="{ width: '72px', padding: '18px 0', background: 'transparent' }"
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

      <div class="mt-3 flex flex-col items-center gap-1.5">
        <button
          v-for="item in NAV_TOP"
          :key="item.key"
          :title="item.label"
          class="relative inline-flex items-center justify-center transition"
          :style="{
            width: '44px',
            height: '44px',
            borderRadius: '14px',
            background: active === item.key ? 'var(--primary)' : 'transparent',
            color: active === item.key ? '#fff' : 'var(--ink-2)',
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
      <button
        v-for="item in NAV_BOT"
        :key="item.key"
        :title="item.label"
        class="inline-flex items-center justify-center transition"
        :style="{
          width: '44px',
          height: '44px',
          borderRadius: '14px',
          background: active === item.key ? 'var(--primary)' : 'transparent',
          color: active === item.key ? '#fff' : 'var(--ink-2)',
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
