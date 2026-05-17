<script setup lang="ts">
/**
 * One video tile in the Outreach grid.
 *
 * Tower-style 评论楼 redesign:
 *
 *   - Three card states driven entirely by ``v.already_commented`` +
 *     ``comments.length``:
 *
 *       待评论   comments.length === 0 && !already_commented
 *                yellow pill, no floor area, composer in empty mode,
 *                完成 button disabled.
 *
 *       盖楼中   comments.length > 0 && !already_commented
 *                orange pill "盖楼中 · N 层", orange-tinted floor tower
 *                with numbered circles, composer in continue mode,
 *                完成 button active.
 *
 *       已完成   already_commented === true
 *                green pill "已完成 · N 层", floor tower COLLAPSES to a
 *                single "这条已经搞定. [继续盖楼]" line. Composer hidden.
 *
 *   - Clicking "继续盖楼" in the 已完成 state calls
 *     ``store.bulkMarkCommented([v.id], false)`` which flips the flag
 *     and re-expands the tower + composer.
 *
 *   - Clicking 完成 in the toolbar (only enabled when ≥1 comment)
 *     flips the flag the other way after a confirm.
 *
 *   - Edit flow: click "编辑" on a floor → composer enters edit mode
 *     for that comment (orange banner, "保存修改" button). Cancel or
 *     save returns to normal mode.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import PlatformChip from "./PlatformChip.vue";
import FloorList from "./FloorList.vue";
import CommentComposer from "./CommentComposer.vue";
import {
  useMiningStore, LLMNotConfiguredError,
  type Video, type Platform, type Comment,
} from "@/stores/mining";
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

/** Tri-state for pill + tower coloring. */
type CardState = "todo" | "drafting" | "done";
const cardState = computed<CardState>(() => {
  if (props.v.already_commented) return "done";
  if (comments.value.length > 0) return "drafting";
  return "todo";
});

const editingComment = ref<Comment | null>(null);

const loadedIds = ref(new Set<number>());

async function ensureLoaded(id: number) {
  if (loadedIds.value.has(id)) return;
  loadedIds.value.add(id);
  try {
    await store.loadComments(id);
  } catch {
    loadedIds.value.delete(id);
  }
}

onMounted(() => { ensureLoaded(props.v.id); });
watch(() => props.v.id, (id) => {
  ensureLoaded(id);
  // Cancel any in-progress edit if the underlying card swaps (paranoia
  // — in practice ``v.id`` is stable per card instance).
  editingComment.value = null;
});

// If the edited comment gets deleted out from under us (e.g. via a
// race), bail out of edit mode rather than leaving a dangling banner.
watch(comments, (list) => {
  if (editingComment.value && !list.some(c => c.id === editingComment.value!.id)) {
    editingComment.value = null;
  }
});

function onEditFloor(id: number) {
  const c = comments.value.find(x => x.id === id);
  if (!c) return;
  editingComment.value = c;
}

function onCancelEdit() {
  editingComment.value = null;
}

async function onDeleteComment(id: number) {
  const ok = await confirmDialog("删除这层评论吗?", {
    title: "删除评论",
    okLabel: "删除",
  });
  if (!ok) return;
  try {
    await store.deleteComment(id);
    if (editingComment.value?.id === id) editingComment.value = null;
    toast.success("已删除");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("删除失败" + (detail ? "：" + detail : ""));
  }
}

function onCommentSaved() {
  // store.createComment / updateComment already updated commentsByVideo;
  // this hook is here for any future "scroll new floor into view".
}

// ── 完成 / 继续盖楼 ────────────────────────────────────────────────────
const bulkBusy = ref(false);

async function onMarkDone() {
  if (comments.value.length === 0 || bulkBusy.value) return;
  const ok = await confirmDialog("确认这条已搞定？", {
    title: "标记完成",
    okLabel: "确认",
    kind: "info",
  });
  if (!ok) return;
  bulkBusy.value = true;
  try {
    await store.bulkMarkCommented([props.v.id], true);
    toast.success("已标记完成");
    editingComment.value = null;
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("标记失败" + (detail ? "：" + detail : ""));
  } finally {
    bulkBusy.value = false;
  }
}

async function onResumeDrafting() {
  if (bulkBusy.value) return;
  bulkBusy.value = true;
  try {
    await store.bulkMarkCommented([props.v.id], false);
    // bulkMarkCommented does a refreshVideos() which can drop the
    // current video from the "已评论" tab; if the parent view filters
    // it out, the card unmounts cleanly. Otherwise it re-renders here
    // with the floors + composer expanded.
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("操作失败" + (detail ? "：" + detail : ""));
  } finally {
    bulkBusy.value = false;
  }
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

// ── Pill props per state ────────────────────────────────────────────
const pillStyle = computed(() => {
  if (cardState.value === "todo") {
    return {
      bg: "var(--yellow-soft)",
      fg: "#a07a18",
      border: "transparent",
    };
  }
  if (cardState.value === "drafting") {
    return {
      bg: "var(--primary-soft)",
      fg: "var(--primary-deep)",
      border: "transparent",
    };
  }
  return {
    bg: "rgba(122,155,94,0.18)",
    fg: "#3a7d44",
    border: "transparent",
  };
});

const pillLabel = computed(() => {
  if (cardState.value === "todo") return "待评论";
  if (cardState.value === "drafting") return `盖楼中 · ${comments.value.length} 层`;
  return `已完成 · ${comments.value.length} 层`;
});

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

      <div class="ml-auto flex items-center gap-2" style="position: relative;">
        <!-- 三态 pill -->
        <span
          class="inline-flex items-center gap-1"
          :style="{
            height: '22px',
            padding: '0 9px',
            borderRadius: '999px',
            background: pillStyle.bg,
            color: pillStyle.fg,
            border: '1px solid ' + pillStyle.border,
            fontSize: '11px',
            fontWeight: 600,
            letterSpacing: '0.2px',
          }"
        >
          <Icon v-if="cardState === 'done'" name="check" :size="10"/>
          <span>{{ pillLabel }}</span>
        </span>
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

    <!-- AI 速览 -->
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

      <div
        v-if="summaryLoading"
        class="flex items-center gap-2 text-[12px]"
        style="color: var(--ink-2);"
      >
        <Spinner :size="12"/>
        <span>生成中…</span>
      </div>
      <div
        v-else-if="v.ai_summary"
        class="text-[12px] leading-relaxed"
        style="color: var(--ink); white-space: pre-wrap;"
      >{{ v.ai_summary }}</div>
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

    <!-- 评论楼 — 三态渲染 -->
    <div
      v-if="cardState === 'done'"
      class="mt-3 flex items-center"
      :style="{
        background: 'rgba(122,155,94,0.10)',
        border: '1px solid rgba(122,155,94,0.32)',
        borderRadius: '12px',
        padding: '10px 12px',
        gap: '8px',
      }"
    >
      <span style="width: 18px; height: 18px; border-radius: 999px; background: var(--green); color: #fff; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;">
        <Icon name="check" :size="11"/>
      </span>
      <span style="font-size: 12px; color: #3a7d44;">
        这条已经搞定 · 共 {{ comments.length }} 层. 需要补盖楼或编辑？
      </span>
      <button
        type="button"
        class="ml-auto inline-flex items-center gap-1 transition"
        :disabled="bulkBusy"
        :style="{
          height: '26px',
          padding: '0 11px',
          borderRadius: '999px',
          fontSize: '11px',
          fontWeight: 600,
          background: '#3a7d44',
          color: '#fff',
          border: '1px solid #3a7d44',
          cursor: bulkBusy ? 'wait' : 'pointer',
        }"
        @click="onResumeDrafting"
      >
        <Icon name="edit" :size="10"/>
        <span>{{ bulkBusy ? "处理中…" : "继续盖楼" }}</span>
      </button>
    </div>

    <!-- 草稿态 (待评论 / 盖楼中) — floor tower + composer -->
    <template v-else>
      <div
        class="mt-3 flex flex-col"
        :style="{
          background: cardState === 'drafting'
            ? 'rgba(238,106,42,0.06)'
            : 'var(--card-2)',
          border: '1px solid ' + (cardState === 'drafting'
            ? 'rgba(238,106,42,0.20)'
            : 'var(--line)'),
          borderRadius: '12px',
          padding: '12px',
          gap: '10px',
        }"
      >
        <div class="flex items-center gap-1.5">
          <span
            :style="{
              width: '16px',
              height: '16px',
              borderRadius: '5px',
              background: cardState === 'drafting' ? 'var(--primary)' : 'var(--ink-4)',
              color: '#fff',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
            }"
          >
            <Icon name="stack" :size="10"/>
          </span>
          <span
            class="text-[10.5px] font-semibold tracking-wide"
            :style="{ color: cardState === 'drafting' ? 'var(--primary-deep)' : 'var(--ink-3)' }"
          >
            评论楼 · {{ comments.length }} 层
          </span>
          <span
            v-if="comments.length >= 3"
            class="ml-auto text-[10px]"
            :style="{ color: 'var(--ink-4)' }"
          >滚动查看全部</span>
        </div>

        <!--
          Floor area is FIXED to 150px so every card reserves the same
          vertical space regardless of how many floors are inside —
          keeps the 2-col grid rows visually aligned and gives empty /
          1-2-floor cards a "blueprint" that doesn't shift when content
          arrives. 3+ floors → internal scrollbar, tone-tinted via
          `floor-scroll-active` / `floor-scroll-idle` (style.css).
        -->
        <div
          :class="['floor-scroll', cardState === 'drafting' ? 'floor-scroll-active' : 'floor-scroll-idle']"
          :style="{ height: '150px', overflowY: comments.length >= 3 ? 'auto' : 'hidden', paddingRight: comments.length >= 3 ? '4px' : '0' }"
        >
          <FloorList
            v-if="comments.length > 0"
            :comments="comments"
            tone="active"
            @edit="onEditFloor"
            @delete="onDeleteComment"
          />
          <div
            v-else
            class="flex flex-col items-center justify-center text-center"
            :style="{
              height: '100%',
              background: 'var(--card-2)',
              border: '1px dashed var(--line-2)',
              borderRadius: '10px',
              color: 'var(--ink-3)',
              fontSize: '11.5px',
              gap: '10px',
            }"
          >
            <span
              :style="{
                width: '28px',
                height: '28px',
                borderRadius: '8px',
                background: 'var(--card)',
                color: 'var(--ink-4)',
                border: '1px dashed var(--line-2)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }"
            >
              <Icon name="comment" :size="13"/>
            </span>
            <span>还没有评论 · 在下面写一条作为第 1 层</span>
          </div>
        </div>
      </div>

      <!-- composer 自带"完成"按钮，无需外层再开一行 -->
      <div class="mt-3">
        <CommentComposer
          :video-id="v.id"
          :next-tier="nextTier"
          :previous-tiers="previousTiers"
          :editing-comment="editingComment"
          :can-complete="comments.length > 0"
          :complete-busy="bulkBusy"
          @saved="onCommentSaved"
          @cancel-edit="onCancelEdit"
          @complete="onMarkDone"
        />
      </div>
    </template>
  </div>
</template>
