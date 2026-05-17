<script setup lang="ts">
import { computed } from "vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Avatar from "@/components/ui/Avatar.vue";
import PlatformChip from "./PlatformChip.vue";
import type { Video, Platform } from "@/stores/mining";

const props = defineProps<{
  v: Video;
  selected: boolean;
}>();

defineEmits<{
  (e: "toggle-select", id: number): void;
  (e: "open", url: string): void;
}>();

// Phase 1 surrogate for "done": already_commented from monitor reverse-lookup.
const isDone = computed(() => props.v.already_commented);

function fmt(n: number | null): string {
  if (n == null) return "—";
  if (n >= 10000) return (n / 10000).toFixed(n >= 100000 ? 0 : 1) + "w";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function fmtDuration(s: number | null): string {
  if (s == null || s <= 0) return "—";
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${String(ss).padStart(2, "0")}`;
}

function relativeTime(iso: string): string {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
  if (diff < 604800) return Math.floor(diff / 86400) + " 天前";
  return d.toLocaleDateString();
}
</script>

<template>
  <div
    class="flex flex-col transition"
    :style="{
      background: 'var(--card)',
      borderRadius: 'var(--radius-card)',
      border: selected ? '1.5px solid var(--primary)' : '1px solid var(--line)',
      padding: '16px',
      position: 'relative',
    }"
  >
    <!-- 顶部 meta 行 -->
    <div class="flex items-center gap-2">
      <button
        @click="$emit('toggle-select', v.id)"
        :style="{
          width: '18px', height: '18px', borderRadius: '5px', flexShrink: 0,
          background: selected ? 'var(--primary)' : 'transparent',
          color: selected ? '#fff' : 'var(--ink-3)',
          border: '1.5px solid ' + (selected ? 'var(--primary)' : 'var(--line-2)'),
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer',
        }"
        title="选中"
      >
        <Icon v-if="selected" name="check" :size="10"/>
      </button>

      <PlatformChip :k="v.platform as Platform"/>

      <div class="flex items-center gap-1 min-w-0">
        <Avatar :name="v.author_name" :size="18"/>
        <span class="text-[11.5px] font-medium truncate" style="color: var(--ink-2); max-width: 110px;">
          @{{ v.author_name || "(无作者)" }}
        </span>
      </div>

      <span class="text-[10.5px]" style="color: var(--ink-4)">· {{ relativeTime(v.first_seen_at) }}</span>

      <div class="ml-auto flex items-center gap-2">
        <Pill v-if="isDone" tone="ok"><Icon name="check" :size="10"/> 已评论</Pill>
        <Pill v-else tone="warn">待评论</Pill>
        <button
          class="inline-flex items-center justify-center"
          style="width: 24px; height: 24px; border-radius: 999px; color: var(--ink-3);"
          title="更多"
        ><Icon name="more" :size="13"/></button>
      </div>
    </div>

    <!-- 标题 + 视频数据 -->
    <div class="flex items-baseline gap-3 mt-3">
      <a
        :href="v.url"
        target="_blank"
        rel="noopener"
        class="font-display font-semibold hover:underline flex-1 min-w-0"
        :style="{
          fontSize: '15.5px', lineHeight: 1.4, color: 'var(--ink)',
          textWrap: 'pretty',
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }"
        title="在浏览器中打开原视频"
      >{{ v.title || "(无标题)" }}</a>
      <div class="flex items-center gap-2.5 flex-shrink-0" style="color: var(--ink-3); font-size: 10.5px;">
        <span v-if="v.duration_sec" class="inline-flex items-center gap-1">
          <Icon name="clock" :size="11"/><span class="font-mono">{{ fmtDuration(v.duration_sec) }}</span>
        </span>
        <span v-if="v.play_count" class="inline-flex items-center gap-1">
          <Icon name="eye" :size="11"/><span class="font-mono">{{ fmt(v.play_count) }}</span>
        </span>
        <span v-if="v.like_count" class="inline-flex items-center gap-1">
          <Icon name="heart" :size="11"/><span class="font-mono">{{ fmt(v.like_count) }}</span>
        </span>
      </div>
    </div>

    <!-- AI 速览 (Phase 1 placeholder) -->
    <div
      class="mt-3"
      style="background: rgba(245,192,66,0.10); border: 1px solid rgba(245,192,66,0.32); border-radius: 12px; padding: 11px 12px;"
    >
      <div class="flex items-center gap-1.5 mb-1.5">
        <span style="width: 16px; height: 16px; border-radius: 5px; background: var(--dark); color: var(--yellow); display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="spark" :size="10"/>
        </span>
        <span class="text-[10.5px] font-semibold tracking-wide" style="color: #7a5400">AI 速览</span>
      </div>
      <div class="text-[12px] leading-relaxed" style="color: var(--ink-2); font-style: italic; opacity: 0.7;">
        待生成 — AI 速览会在第三期上线
      </div>
    </div>

    <!-- 评论楼占位 -->
    <div
      class="mt-3"
      style="background: var(--card-2); border: 1px solid var(--line); border-radius: 12px; padding: 12px 12px 6px;"
    >
      <div class="flex items-center gap-1.5 mb-2.5">
        <span style="width: 16px; height: 16px; border-radius: 5px; background: var(--ink-4); color: #fff; display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="stack" :size="10"/>
        </span>
        <span class="text-[10.5px] font-semibold tracking-wide" style="color: var(--ink-3)">评论楼 · 0 层</span>
        <span class="ml-auto text-[10px]" style="color: var(--ink-4)">第二期上线</span>
      </div>
      <div class="flex flex-col items-center justify-center text-center" style="padding: 16px 12px;">
        <span style="width: 28px; height: 28px; border-radius: 8px; background: var(--card); color: var(--ink-4); border: 1px dashed var(--line-2); display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="comment" :size="13"/>
        </span>
        <div class="text-[11px] mt-1.5" style="color: var(--ink-3)">评论楼工作流 · 第二期上线</div>
      </div>
    </div>

    <!-- composer 占位 (disabled) -->
    <div
      class="mt-3 flex flex-col relative"
      style="background: var(--card-white); border: 1.5px solid var(--line-2); border-radius: 12px; padding: 2px; opacity: 0.55;"
    >
      <textarea
        disabled
        placeholder="评论楼工作流将在第二期上线…"
        rows="2"
        class="w-full bg-transparent outline-none resize-none"
        style="padding: 9px 11px 4px; font-size: 12.5px; line-height: 1.55; color: var(--ink); font-family: inherit; min-height: 56px;"
      ></textarea>
      <div class="flex items-center gap-1.5" style="padding: 5px 6px 5px 8px;">
        <button
          disabled
          class="inline-flex items-center gap-1"
          style="height: 26px; padding: 0 9px; border-radius: 999px; font-size: 11px; background: var(--card-2); color: var(--ink-4); border: 1px solid var(--line); cursor: not-allowed;"
        >
          <Icon name="copy" :size="11"/> 图片
        </button>
        <button
          disabled
          class="inline-flex items-center gap-1"
          style="height: 26px; padding: 0 9px; border-radius: 999px; font-size: 11px; background: var(--card-2); color: var(--ink-4); border: 1px solid var(--line); cursor: not-allowed;"
        >
          <Icon name="wand" :size="11"/> AI 建议
        </button>
        <div class="flex-1"/>
        <button
          disabled
          class="inline-flex items-center gap-1.5"
          style="height: 28px; padding: 0 14px; border-radius: 999px; font-size: 11.5px; font-weight: 600; background: var(--card-2); color: var(--ink-4); border: 1px solid var(--line); cursor: not-allowed;"
          title="第二期上线"
        >
          <Icon name="play" :size="11"/> 发布第 1 层
        </button>
      </div>
    </div>
  </div>
</template>
