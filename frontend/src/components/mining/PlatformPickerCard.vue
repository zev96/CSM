<script setup lang="ts">
import Icon from "@/components/ui/Icon.vue";
import type { Platform } from "@/stores/mining";

const props = defineProps<{
  platform: Platform;
  picked: boolean;
  loggedIn: boolean;
}>();

defineEmits<{
  (e: "toggle"): void;
  (e: "login"): void;
}>();

const META: Record<Platform, { l: string; letter: string; color: string }> = {
  bilibili: { l: "B 站", letter: "B", color: "#fb7299" },
  douyin: { l: "抖音", letter: "D", color: "#1c1a17" },
  kuaishou: { l: "快手", letter: "K", color: "#ff6633" },
};

const meta = () => META[props.platform];
</script>

<template>
  <button
    @click="loggedIn ? $emit('toggle') : $emit('login')"
    :style="{
      position: 'relative',
      textAlign: 'left',
      borderRadius: '14px',
      padding: '12px 12px 11px',
      background: picked ? 'var(--card-white)' : 'var(--card-2)',
      // 选中状态只靠卡片背景 + 右上角 check chip 表示；不再画彩色描边，
      // 视觉更干净，跟列表里的多卡选择气质一致。
      border: '1.5px solid transparent',
      opacity: loggedIn ? 1 : 0.62,
      transition: 'all .15s',
      cursor: 'pointer',
    }"
  >
    <div class="flex items-center gap-2">
      <span
        :style="{
          width: '26px', height: '26px', borderRadius: '8px',
          background: meta().color, color: '#fff',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '12px', fontWeight: 800,
        }"
      >{{ meta().letter }}</span>
      <span class="font-display font-semibold text-[13.5px]">{{ meta().l }}</span>
      <span
        v-if="picked"
        :style="{
          marginLeft: 'auto',
          width: '16px', height: '16px', borderRadius: '999px',
          background: meta().color, color: '#fff',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }"
      ><Icon name="check" :size="10"/></span>
    </div>
    <div
      class="text-[10.5px] mt-2 flex items-center gap-1"
      :style="{ color: loggedIn ? 'var(--green-deep)' : 'var(--red)' }"
    >
      <template v-if="loggedIn">
        <Icon name="check" :size="10"/> 已登录
      </template>
      <template v-else>
        <Icon name="lock" :size="10"/> 未登录
      </template>
    </div>
  </button>
</template>
