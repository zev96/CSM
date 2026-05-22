<script setup lang="ts">
/**
 * 首页 Row 1 右栏 —— 3 张竖排 shortcut 卡。
 *
 * 入口与 LeftNav 主导航对应（左栏图标 = 全局导航，这里 = 工作台快速跳转）。
 * "数据中心 / 引流中心 / 模板库" 名称仅在首页使用，LeftNav 保持原文案。
 *
 * 模板库副标显示动态计数（templates + skills），失败回退静态文案。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

const router = useRouter();
const sidecar = useSidecar();
const { whenReady } = useSidecarReady();

const tplCount = ref<number | null>(null);
const skillCount = ref<number | null>(null);

onMounted(async () => {
  try {
    await whenReady();
    const [t, s] = await Promise.all([
      sidecar.client.get("/api/templates"),
      sidecar.client.get("/api/skills"),
    ]);
    tplCount.value = (t.data?.templates ?? []).length;
    skillCount.value = (s.data?.skills ?? []).length;
  } catch {
    /* 静默：副标 fall back 到静态文案 */
  }
});

const libraryDesc = computed(() => {
  if (tplCount.value === null || skillCount.value === null) {
    return "模板与风格集合";
  }
  return `${tplCount.value} 套模板 · ${skillCount.value} 个 Skill`;
});

interface Shortcut {
  key: string;
  to: string;
  query?: Record<string, string>;
  icon: string;
  title: string;
  /** 静态文案；模板库走 computed libraryDesc。 */
  desc?: string;
  /** Icon 方框背景色，对应三种语义气质。 */
  iconBg: string;
  /** Icon 颜色。 */
  iconColor: string;
}

const SHORTCUTS = computed<Shortcut[]>(() => [
  {
    key: "monitor",
    to: "monitor",
    icon: "barChart",
    title: "数据中心",
    desc: "排名监控 · 评论留存",
    iconBg: "rgba(122,155,94,0.16)",
    iconColor: "var(--green)",
  },
  {
    key: "mining",
    to: "mining",
    icon: "megaphone",
    title: "引流中心",
    desc: "视频抓取 · 评论盖楼",
    iconBg: "rgba(238,106,42,0.16)",
    iconColor: "var(--primary)",
  },
  {
    key: "templates",
    to: "templates",
    icon: "library",
    title: "模板库",
    desc: libraryDesc.value,
    iconBg: "rgba(28,26,23,0.08)",
    iconColor: "var(--ink)",
  },
]);

function go(s: Shortcut) {
  router.push({ name: s.to, query: s.query ?? {} });
}
</script>

<template>
  <div class="flex h-full flex-col gap-3">
    <button
      v-for="s in SHORTCUTS"
      :key="s.key"
      type="button"
      class="group flex flex-1 items-center gap-3 text-left transition"
      :style="{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-card)',
        padding: '16px',
        minHeight: '0',
      }"
      @click="go(s)"
      @mouseenter="
        (e: MouseEvent) =>
          ((e.currentTarget as HTMLElement).style.background =
            'var(--card-white)')
      "
      @mouseleave="
        (e: MouseEvent) =>
          ((e.currentTarget as HTMLElement).style.background = 'var(--card)')
      "
    >
      <span
        class="inline-flex flex-shrink-0 items-center justify-center"
        :style="{
          width: '40px',
          height: '40px',
          borderRadius: '12px',
          background: s.iconBg,
          color: s.iconColor,
        }"
      >
        <Icon :name="s.icon" :size="18" />
      </span>
      <div class="min-w-0 flex-1">
        <div
          class="font-display font-semibold"
          :style="{ fontSize: '14px', letterSpacing: '-0.2px' }"
        >
          {{ s.title }}
        </div>
        <div
          class="mt-0.5 truncate text-[11px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          {{ s.desc }}
        </div>
      </div>
      <Icon
        name="arrowRight"
        :size="14"
        class="flex-shrink-0 transition"
        :style="{ color: 'var(--ink-3)' }"
      />
    </button>
  </div>
</template>
