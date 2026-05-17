<script setup lang="ts">
/**
 * One video tile in the Outreach grid.
 *
 * Phase 2/3:
 *   - Real comment list (`<CommentItem>` 列表 + `<CommentComposer>`)
 *   - Real AI 速览 (3 态：空 / 加载 / 已生成 + 重新生成)
 *   - 顶部 ⋯ 下拉菜单：复制全部评论 / 删除视频
 *
 * The comment list is sourced from `store.commentsByVideo[id]` which the
 * composer already updates on create/delete — no need to re-fetch after
 * a save (the store does an optimistic insert). We do call
 * `loadComments` once on mount and on `v.id` change so cards that were
 * never opened still show their persisted drafts.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import PlatformChip from "./PlatformChip.vue";
import CommentItem from "./CommentItem.vue";
import CommentComposer from "./CommentComposer.vue";
import { useMiningStore, LLMNotConfiguredError, type Video, type Platform } from "@/stores/mining";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const props = defineProps<{
  v: Video;
  selected: boolean;
}>();

defineEmits<{
  (e: "toggle-select", id: number): void;
  (e: "open", url: string): void;
}>();

const store = useMiningStore();
const toast = useToast();
const router = useRouter();

// Phase 1 surrogate for "done": already_commented from monitor reverse-lookup.
const isDone = computed(() => props.v.already_commented);

// Truncate title to 15 chars to keep cards compact. Full title goes into
// the anchor's `title=` attr so hover still shows the whole thing.
const TITLE_MAX = 15;
const titleShort = computed(() => {
  const t = props.v.title || "(无标题)";
  return t.length > TITLE_MAX ? t.slice(0, TITLE_MAX) + "…" : t;
});

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

// ── 评论楼 ─────────────────────────────────────────────────────────────
const comments = computed(() => store.commentsByVideo[props.v.id] ?? []);
const nextTier = computed(
  () => Math.max(0, ...comments.value.map(c => c.tier)) + 1,
);
const previousTiers = computed(() => comments.value.map(c => c.text));

// Track which video ids we've already hit `loadComments` for so re-renders
// of the same card don't re-fetch needlessly. The store cache itself does
// not distinguish "never loaded" from "loaded empty", so we keep a local
// sentinel.
const loadedIds = ref(new Set<number>());

async function ensureLoaded(id: number) {
  if (loadedIds.value.has(id)) return;
  loadedIds.value.add(id);
  try {
    await store.loadComments(id);
  } catch {
    // Silent: the card just shows the empty-state for now. Caller can
    // retry by writing a comment, which surfaces a real error toast.
    loadedIds.value.delete(id);
  }
}

onMounted(() => { ensureLoaded(props.v.id); });
watch(() => props.v.id, (id) => { ensureLoaded(id); });

async function onDeleteComment(id: number) {
  if (!window.confirm("删除这条评论吗?")) return;
  try {
    await store.deleteComment(id);
    toast.success("已删除");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("删除失败" + (detail ? "：" + detail : ""));
  }
}

function onCopyComment() {
  toast.success("已复制到剪贴板");
}

function onCommentSaved() {
  // store.createComment already pushed the new comment into
  // commentsByVideo; no work to do here. We keep this handler hooked up
  // so future flows (e.g. scroll-into-view of the new row) have a slot.
}

// ── AI 速览 ────────────────────────────────────────────────────────────
const summaryLoading = computed(() => Boolean(store.aiSummaryLoading[props.v.id]));

async function triggerSummarize(force = false) {
  try {
    await store.summarize(props.v.id, force);
  } catch (err) {
    if (err instanceof LLMNotConfiguredError) {
      toast.error("请先在设置中配置 AI 服务", {
        actionLabel: "去设置",
        onAction: () => { router.push("/settings"); },
      });
    } else {
      const detail = (err as any)?.response?.data?.detail as string | undefined;
      toast.error("AI 速览生成失败" + (detail ? "：" + detail : ""));
    }
  }
}

// ── 顶部 ⋯ 下拉菜单 ─────────────────────────────────────────────────
// Simple inline dropdown:
//   - `menuOpen` toggles visibility, anchored to the ⋯ button
//   - A window-level click listener closes it on outside-click; clicks
//     inside the menu stopPropagation so they don't immediately close
//   - We register the listener only while open so we don't pay the
//     cost on every card on every page-wide click.
const menuOpen = ref(false);

function openMenu(ev: MouseEvent) {
  ev.stopPropagation();
  menuOpen.value = !menuOpen.value;
}

function onWindowClick() {
  menuOpen.value = false;
}

watch(menuOpen, (open) => {
  if (open) {
    // Delay one tick so the same click that opened the menu doesn't
    // close it via the window handler.
    setTimeout(() => window.addEventListener("click", onWindowClick), 0);
  } else {
    window.removeEventListener("click", onWindowClick);
  }
});

onUnmounted(() => {
  window.removeEventListener("click", onWindowClick);
});

async function onCopyAllComments() {
  menuOpen.value = false;
  const list = comments.value;
  if (list.length === 0) {
    toast.info?.("还没有评论可复制");
    return;
  }
  const lines = list.map(c => `[第 ${c.tier} 层] ${c.text || ""}`);
  const text = lines.join("\n");
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`已复制 ${list.length} 层评论`);
  } catch {
    toast.error("复制失败，请重试");
  }
}

async function onDeleteVideo() {
  menuOpen.value = false;
  const ok = await confirmDialog(
    `确定删除「${props.v.title || "(无标题)"}」? 评论草稿也会一并丢失.`,
    { title: "删除视频" },
  );
  if (!ok) return;
  try {
    await store.deleteVideo(props.v.id);
    toast.success("已删除视频");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("删除失败" + (detail ? "：" + detail : ""));
  }
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

      <!--
        Phase 1: 作者 + 抓取时间这一段先省掉 —— B 站 SSR parser
        把标题塞进了 author_name，渲染出来反而是冗余。Phase 2 改
        adapter 解析后再恢复。
      -->

      <div class="ml-auto flex items-center gap-2" style="position: relative;">
        <Pill v-if="isDone" tone="ok"><Icon name="check" :size="10"/> 已评论</Pill>
        <Pill v-else tone="warn">待评论</Pill>
        <button
          class="inline-flex items-center justify-center"
          style="width: 24px; height: 24px; border-radius: 999px; color: var(--ink-3); cursor: pointer;"
          title="更多"
          @click="openMenu"
        ><Icon name="more" :size="13"/></button>

        <!-- 下拉菜单 -->
        <div
          v-if="menuOpen"
          class="absolute z-30"
          :style="{
            top: '30px',
            right: '0',
            minWidth: '160px',
            background: 'var(--card-white)',
            border: '1px solid var(--line-2)',
            borderRadius: '10px',
            boxShadow: '0 10px 30px -8px rgba(28,26,23,0.25)',
            padding: '4px',
          }"
          @click.stop
        >
          <button
            type="button"
            class="flex w-full items-center gap-2 text-left"
            :style="{
              height: '30px',
              padding: '0 10px',
              borderRadius: '7px',
              fontSize: '12px',
              color: 'var(--ink)',
              background: 'transparent',
              cursor: 'pointer',
            }"
            @mouseenter="($event.currentTarget as HTMLElement).style.background = 'var(--card-2)'"
            @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
            @click="onCopyAllComments"
          >
            <Icon name="copy" :size="12"/>
            <span>复制全部评论</span>
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-2 text-left"
            :style="{
              height: '30px',
              padding: '0 10px',
              borderRadius: '7px',
              fontSize: '12px',
              color: 'var(--red, #c0392b)',
              background: 'transparent',
              cursor: 'pointer',
            }"
            @mouseenter="($event.currentTarget as HTMLElement).style.background = 'rgba(192,57,43,0.08)'"
            @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
            @click="onDeleteVideo"
          >
            <Icon name="trash" :size="12"/>
            <span>删除视频</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 标题 + 视频数据 -->
    <div class="flex items-baseline gap-3 mt-3">
      <a
        :href="v.url"
        target="_blank"
        rel="noopener"
        class="font-display font-semibold hover:underline flex-1 min-w-0 truncate"
        :style="{
          fontSize: '15.5px', lineHeight: 1.4, color: 'var(--ink)',
        }"
        :title="v.title || '(无标题)'"
      >{{ titleShort }}</a>
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

    <!--
      AI 速览 — 3 态：
        - 未生成（空 + 非 loading）→ 点击生成按钮
        - loading → spinner + 文案
        - 已生成 → 文本 + ⟳ 重新生成
    -->
    <div
      class="mt-3"
      style="background: rgba(245,192,66,0.10); border: 1px solid rgba(245,192,66,0.32); border-radius: 12px; padding: 11px 12px;"
    >
      <div class="flex items-center gap-1.5 mb-1.5">
        <span style="width: 16px; height: 16px; border-radius: 5px; background: var(--dark); color: var(--yellow); display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="spark" :size="10"/>
        </span>
        <span class="text-[10.5px] font-semibold tracking-wide" style="color: #7a5400">AI 速览</span>
        <button
          v-if="v.ai_summary && !summaryLoading"
          type="button"
          class="ml-auto inline-flex items-center justify-center transition hover:bg-[rgba(122,84,0,0.12)]"
          :style="{
            width: '22px', height: '22px',
            borderRadius: '999px',
            color: '#7a5400',
            cursor: 'pointer',
          }"
          title="重新生成"
          @click="triggerSummarize(true)"
        ><Icon name="refresh" :size="11"/></button>
      </div>

      <!-- 加载中 -->
      <div
        v-if="summaryLoading"
        class="flex items-center gap-2 text-[12px]"
        style="color: var(--ink-2);"
      >
        <Spinner :size="12"/>
        <span>生成中…</span>
      </div>

      <!-- 已生成 -->
      <div
        v-else-if="v.ai_summary"
        class="text-[12px] leading-relaxed"
        style="color: var(--ink); white-space: pre-wrap;"
      >{{ v.ai_summary }}</div>

      <!-- 未生成 -->
      <button
        v-else
        type="button"
        class="inline-flex items-center gap-1.5 transition"
        :style="{
          height: '26px',
          padding: '0 10px',
          borderRadius: '999px',
          fontSize: '11.5px',
          fontWeight: 500,
          background: 'var(--dark)',
          color: 'var(--yellow)',
          border: '1px solid var(--dark)',
          cursor: 'pointer',
        }"
        @click="triggerSummarize(false)"
      >
        <Icon name="spark" :size="11"/>
        <span>点击生成 AI 速览</span>
      </button>
    </div>

    <!-- 评论楼 -->
    <div
      class="mt-3 flex flex-col"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: '12px',
        padding: '12px',
        gap: '8px',
      }"
    >
      <div class="flex items-center gap-1.5">
        <span style="width: 16px; height: 16px; border-radius: 5px; background: var(--ink-4); color: #fff; display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="stack" :size="10"/>
        </span>
        <span class="text-[10.5px] font-semibold tracking-wide" style="color: var(--ink-3)">
          评论楼 · {{ comments.length }} 层
        </span>
      </div>

      <!-- 评论列表 -->
      <div v-if="comments.length > 0" class="flex flex-col" style="gap: 6px;">
        <CommentItem
          v-for="c in comments"
          :key="c.id"
          :comment="c"
          :video-id="v.id"
          @delete="onDeleteComment"
          @copy="onCopyComment"
        />
      </div>
      <div
        v-else
        class="text-[11px]"
        style="color: var(--ink-3); padding: 4px 2px 0;"
      >
        还没写过评论, 用下面的输入框写一条
      </div>
    </div>

    <!-- composer -->
    <div class="mt-3">
      <CommentComposer
        :video-id="v.id"
        :next-tier="nextTier"
        :previous-tiers="previousTiers"
        @saved="onCommentSaved"
      />
    </div>
  </div>
</template>
