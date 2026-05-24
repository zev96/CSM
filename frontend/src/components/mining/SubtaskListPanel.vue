<script setup lang="ts">
/**
 * 中栏：子任务列表面板。
 *
 * 显示当前选中 job 下的所有视频，每行：
 *   - checkbox（多选）
 *   - 视频标题（截 18 字 + 省略号）
 *   - 状态 pill（待评论 / 盖楼中 N 层 / 已完成 N 层）
 *
 * 顶部 header 含：
 *   - 标题「视频列表」+ 总数
 *   - 状态 pivot（待评论 / 已评论 / 全部）
 *   - 平台 pivot（全部 / B站 / 抖音 / 快手）
 *
 * 点行 → emit 'select-video'，右栏 VideoDetailPanel 接住显示详情。
 * 选中 checkbox → emit 'toggle-select'，父组件 MiningView 维护 selected Set。
 *
 * 浮动 toolbar 不在这里渲染 —— 由父组件 MiningView 用绝对定位放在
 * 中栏区域底部居中（user 要求"中下位置"），见 MiningView.vue。
 */
import { computed } from "vue";

import Icon from "@/components/ui/Icon.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import type { Video, Platform } from "@/stores/mining";

// ── 平台 icon 元数据 ──────────────────────────────────────────────────
// 中栏每行只显示 14×14 色块 + 字母，不渲染「B 站 / 抖音 / 快手」全名 ——
// 列表行很窄、需要给标题最多空间。Hover 时浏览器 native tooltip 会显示
// title 属性给的全名做无障碍兜底。
const PLATFORM_META: Record<Platform, { letter: string; color: string; name: string }> = {
  bilibili: { letter: "B", color: "#fb7299", name: "B 站" },
  douyin: { letter: "D", color: "#1c1a17", name: "抖音" },
  kuaishou: { letter: "K", color: "#ff6633", name: "快手" },
};

const props = defineProps<{
  videos: Video[];
  selectedVideoId: number | null;
  selected: Set<number>;
  tab: "unread" | "done" | "all";
  platform: "all" | Platform;
}>();

const emit = defineEmits<{
  (e: "select-video", id: number): void;
  (e: "toggle-select", id: number): void;
  (e: "update:tab", v: "unread" | "done" | "all"): void;
  (e: "update:platform", v: "all" | Platform): void;
}>();

// 标题截断 —— 用户要求前 10 字，超出加 …。Array.from 走 grapheme
// 切分避免 emoji 被劈成 �。完整标题仍挂 title 属性 hover tooltip 兜底。
const TITLE_MAX = 10;
function titleShort(title: string): string {
  const t = title || "(无标题)";
  const chars = Array.from(t);
  return chars.length > TITLE_MAX ? chars.slice(0, TITLE_MAX).join("") + "…" : t;
}

// 二态 pill —— 用户要求中栏只显示「待评论 / 已完成」两个状态。
//
// 不在这里玩"盖楼中 · N 层"的中间态：那个需要 commentsByVideo 全表预加载
// 才准（VideoDetailPanel 仅在选中时挂载并 ensureLoaded 自己那条），否则
// 99% 的视频会误显示「待评论」。中栏只看 already_commented 这个 video
// record 上的字段，永远准确；细节（共 N 层）放到右栏面板里看。
function pillFor(v: Video): { label: string; bg: string; fg: string } {
  if (v.already_commented) {
    return { label: "已完成", bg: "rgba(122,155,94,0.18)", fg: "#3a7d44" };
  }
  return { label: "待评论", bg: "var(--yellow-soft)", fg: "#a07a18" };
}

// 下拉选项 —— 按用户要求把状态 + 平台都从胶囊 pivot 改成 FormSelect。
// 状态选项不再带数字徽章（counts 仍传进来用于 header 总数显示，但 pivot
// 本身只显示文字）。
const TAB_OPTIONS = [
  { label: "待评论", value: "unread" },
  { label: "已评论", value: "done" },
  { label: "全部", value: "all" },
] as const;
const PLATFORM_OPTIONS = [
  { label: "全部平台", value: "all" },
  { label: "B 站", value: "bilibili" },
  { label: "抖音", value: "douyin" },
  { label: "快手", value: "kuaishou" },
] as const;

const totalCount = computed(() => props.videos.length);
</script>

<template>
  <!--
    aside 必须用 flex: 1 + h-full 吃满父级（MiningView 的中栏 wrapper 是
    flex-col + position:relative，没给本组件下达高度，否则 aside 会按
    内容自然高度撑开 → body 的 flex-1 + overflow-y-auto 永远没机会触发
    滚动条（用户看到的"29 条只显示一部分、不能下滑"就是这个 bug）。
    width 用 100% 吃父 wrapper 已经设的 320px，避免双层 320 重复。
  -->
  <aside
    :style="{
      width: '100%',
      flex: 1,
      minHeight: 0,
      background: 'var(--card)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-card)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }"
  >
    <!--
      Header：title + 两个 FormSelect 同行（状态 + 平台）。
      按用户要求把 pivot 改成下拉框；状态选项去掉数字徽章；两个 select
      并排同一行，各占一半宽度。FormSelect 的弹层 Teleport 到 body，
      不会被 aside 的 overflow-hidden 裁掉。
    -->
    <header
      class="flex flex-col gap-2"
      :style="{
        padding: '14px 14px 12px',
        borderBottom: '1px solid var(--line)',
        flexShrink: 0,
      }"
    >
      <div class="flex items-center justify-between">
        <div class="font-display font-bold text-[14px]" style="letter-spacing: -0.3px;">
          视频列表
        </div>
        <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
          共 {{ totalCount }} 条
        </span>
      </div>
      <div class="flex items-center gap-2">
        <div style="flex: 1; min-width: 0;">
          <FormSelect
            :model-value="tab"
            :options="[...TAB_OPTIONS]"
            width="100%"
            @update:model-value="(v) => emit('update:tab', v as 'unread' | 'done' | 'all')"
          />
        </div>
        <div style="flex: 1; min-width: 0;">
          <FormSelect
            :model-value="platform"
            :options="[...PLATFORM_OPTIONS]"
            width="100%"
            @update:model-value="(v) => emit('update:platform', v as 'all' | Platform)"
          />
        </div>
      </div>
    </header>

    <!-- Body：视频行列表，内部独立滚 -->
    <div
      :style="{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        padding: '8px',
      }"
    >
      <div
        v-if="videos.length === 0"
        class="flex flex-col items-center justify-center text-center"
        :style="{
          padding: '40px 16px',
          gap: '8px',
          color: 'var(--ink-3)',
          fontSize: '11.5px',
        }"
      >
        <Icon name="video" :size="20" />
        <span>没有匹配的视频</span>
      </div>
      <template v-else>
        <div
          v-for="v in videos"
          :key="v.id"
          class="flex items-center gap-2 transition cursor-pointer"
          :style="{
            padding: '10px 10px',
            borderRadius: '10px',
            background: selectedVideoId === v.id ? 'var(--card-2)' : 'transparent',
            border: selectedVideoId === v.id ? '1px solid var(--line-2)' : '1px solid transparent',
            marginBottom: '4px',
          }"
          @click="emit('select-video', v.id)"
          @mouseenter="(e) => { if (selectedVideoId !== v.id) (e.currentTarget as HTMLElement).style.background = 'rgba(28,26,23,0.04)' }"
          @mouseleave="(e) => { if (selectedVideoId !== v.id) (e.currentTarget as HTMLElement).style.background = 'transparent' }"
        >
          <!-- checkbox -->
          <button
            @click.stop="emit('toggle-select', v.id)"
            :style="{
              width: '16px', height: '16px', borderRadius: '4px', flexShrink: 0,
              background: selected.has(v.id) ? 'var(--primary)' : 'transparent',
              color: selected.has(v.id) ? '#fff' : 'var(--ink-3)',
              border: '1.5px solid ' + (selected.has(v.id) ? 'var(--primary)' : 'var(--line-2)'),
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer',
            }"
            title="选中"
          >
            <Icon v-if="selected.has(v.id)" name="check" :size="9" />
          </button>
          <!--
            平台 icon —— 14×14 色块 + 字母（B/D/K），不渲染全名。
            title 给屏阅 + hover tooltip 兜底。
          -->
          <span
            class="flex-shrink-0"
            :title="PLATFORM_META[v.platform as Platform].name"
            :style="{
              width: '18px', height: '18px', borderRadius: '5px',
              background: PLATFORM_META[v.platform as Platform].color,
              color: '#fff',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '10px', fontWeight: 800,
            }"
          >{{ PLATFORM_META[v.platform as Platform].letter }}</span>
          <!-- 标题 -->
          <div
            class="flex-1 min-w-0 truncate text-[12px]"
            :style="{
              color: selectedVideoId === v.id ? 'var(--ink)' : 'var(--ink-2)',
              fontWeight: selectedVideoId === v.id ? 600 : 500,
            }"
            :title="v.title || '(无标题)'"
          >
            {{ titleShort(v.title) }}
          </div>
          <!-- 状态 pill -->
          <span
            class="inline-flex items-center flex-shrink-0"
            :style="{
              height: '20px',
              padding: '0 7px',
              borderRadius: '999px',
              background: pillFor(v).bg,
              color: pillFor(v).fg,
              fontSize: '10px',
              fontWeight: 600,
              whiteSpace: 'nowrap',
            }"
          >{{ pillFor(v).label }}</span>
        </div>
      </template>
    </div>
  </aside>
</template>
