<script setup lang="ts">
/**
 * 右栏：单条视频工作面板。
 *
 * 接收 `props.v: Video`（中栏选中的视频），渲染：
 *   - 顶部 header：平台 chip + 标题 + 视频数据（时长/播放/点赞） + 三态 pill + ⋯ menu
 *   - AI 速览（无则显示「点击生成 AI 速览」按钮）
 *   - 评论楼区域（FloorList + 空态）—— flex-1 + overflow-y-auto 撑满
 *   - CommentComposer 固定底部
 *
 * 逻辑直接 port 自 VideoCard.vue —— 同一份状态机（todo/drafting/done）
 * 和同样的 store API（loadComments / createComment / bulkMarkCommented /
 * summarize / deleteVideo）。区别在于布局：原 VideoCard 是 2 列网格里的
 * 单卡（固定 16px padding + 评论楼锁 150px），这里铺满右栏（无外卡 chrome、
 * 评论楼 flex-1 自动撑满剩余高度、composer sticky 底部）。
 *
 * checkbox + 标题选中态由中栏 SubtaskListPanel 管，本面板不再渲染。
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
}>();

const store = useMiningStore();
const toast = useToast();
const router = useRouter();

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
  () => Math.max(0, ...comments.value.map((c) => c.tier)) + 1,
);
const previousTiers = computed(() => comments.value.map((c) => c.text));

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
  editingComment.value = null;
});
watch(comments, (list) => {
  if (editingComment.value && !list.some((c) => c.id === editingComment.value!.id)) {
    editingComment.value = null;
  }
});

function onEditFloor(id: number) {
  const c = comments.value.find((x) => x.id === id);
  if (!c) return;
  editingComment.value = c;
}
function onCancelEdit() { editingComment.value = null; }

async function onDeleteComment(id: number) {
  const ok = await confirmDialog("删除这层评论吗?", { title: "删除评论", okLabel: "删除" });
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
function onCommentSaved() { /* store 已写入 commentsByVideo */ }

// ── 完成 / 继续盖楼 ────────────────────────────────────────────────────
const bulkBusy = ref(false);
async function onMarkDone() {
  if (comments.value.length === 0 || bulkBusy.value) return;
  const ok = await confirmDialog("确认这条已搞定？", {
    title: "标记完成", okLabel: "确认", kind: "info",
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

// ── ⋯ 下拉菜单 ────────────────────────────────────────────────────────
const menuOpen = ref(false);
function openMenu(ev: MouseEvent) {
  ev.stopPropagation();
  menuOpen.value = !menuOpen.value;
}
function onWindowClick() { menuOpen.value = false; }
watch(menuOpen, (open) => {
  if (open) setTimeout(() => window.addEventListener("click", onWindowClick), 0);
  else window.removeEventListener("click", onWindowClick);
});
onUnmounted(() => { window.removeEventListener("click", onWindowClick); });

async function onCopyAllComments() {
  menuOpen.value = false;
  const list = comments.value;
  if (list.length === 0) {
    toast.info?.("还没有评论可复制");
    return;
  }
  const text = list.map((c) => `[第 ${c.tier} 层] ${c.text || ""}`).join("\n");
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

// ── Pill props per state ──────────────────────────────────────────────
const pillStyle = computed(() => {
  if (cardState.value === "todo") {
    return { bg: "var(--yellow-soft)", fg: "#a07a18", border: "transparent" };
  }
  if (cardState.value === "drafting") {
    return { bg: "var(--primary-soft)", fg: "var(--primary-deep)", border: "transparent" };
  }
  return { bg: "rgba(122,155,94,0.18)", fg: "#3a7d44", border: "transparent" };
});
const pillLabel = computed(() => {
  if (cardState.value === "todo") return "待评论";
  if (cardState.value === "drafting") return `盖楼中 · ${comments.value.length} 层`;
  return `已完成 · ${comments.value.length} 层`;
});
</script>

<template>
  <section
    :style="{
      flex: 1,
      minWidth: 0,
      minHeight: 0,
      background: 'var(--card)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-card)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }"
  >
    <!-- ── Header：title + meta + pill + ⋯ menu ──────────────── -->
    <header
      class="flex flex-col gap-2"
      :style="{
        padding: '18px 20px',
        borderBottom: '1px solid var(--line)',
        flexShrink: 0,
      }"
    >
      <div class="flex items-center gap-2">
        <PlatformChip :k="v.platform as Platform" />
        <span
          class="inline-flex items-center gap-1"
          :style="{
            height: '22px', padding: '0 9px', borderRadius: '999px',
            background: pillStyle.bg, color: pillStyle.fg,
            fontSize: '11px', fontWeight: 600,
          }"
        >
          <Icon v-if="cardState === 'done'" name="check" :size="10" />
          <span>{{ pillLabel }}</span>
        </span>
        <div class="ml-auto" style="position: relative;">
          <button
            class="inline-flex items-center justify-center"
            style="width: 26px; height: 26px; border-radius: 999px; color: var(--ink-3); cursor: pointer; background: var(--card-2); border: 1px solid var(--line);"
            title="更多"
            @click="openMenu"
          ><Icon name="more" :size="13" /></button>
          <div
            v-if="menuOpen"
            class="absolute z-30"
            :style="{
              top: '32px', right: '0', minWidth: '160px',
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
                height: '30px', padding: '0 10px', borderRadius: '7px',
                fontSize: '12px', color: 'var(--ink)', background: 'transparent', cursor: 'pointer',
              }"
              @mouseenter="($event.currentTarget as HTMLElement).style.background = 'var(--card-2)'"
              @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
              @click="onCopyAllComments"
            >
              <Icon name="copy" :size="12" />
              <span>复制全部评论</span>
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 text-left"
              :style="{
                height: '30px', padding: '0 10px', borderRadius: '7px',
                fontSize: '12px', color: 'var(--red, #c0392b)', background: 'transparent', cursor: 'pointer',
              }"
              @mouseenter="($event.currentTarget as HTMLElement).style.background = 'rgba(192,57,43,0.08)'"
              @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
              @click="onDeleteVideo"
            >
              <Icon name="trash" :size="12" />
              <span>删除视频</span>
            </button>
          </div>
        </div>
      </div>
      <!--
        视频标题 —— 固定两行，超出截断（…）。
        line-clamp 在 WebKit/Blink 走 -webkit-line-clamp + -webkit-box，
        Edge/Chrome 都支持。lineHeight 1.35 × fontSize 17px ≈ 23px/行，
        两行 ~46px；右栏宽度足够时多数标题一行能装下，长标题截断在第二行
        末尾加 …。完整标题挂在 title 属性，hover tooltip 兜底可读。
      -->
      <a
        :href="v.url"
        target="_blank"
        rel="noopener"
        class="font-display font-semibold hover:underline"
        :style="{
          fontSize: '17px',
          lineHeight: 1.35,
          color: 'var(--ink)',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
          wordBreak: 'break-word',
        }"
        :title="v.title || '(无标题)'"
      >{{ v.title || "(无标题)" }}</a>
      <div class="flex items-center gap-3" style="color: var(--ink-3); font-size: 11.5px;">
        <span v-if="v.duration_sec" class="inline-flex items-center gap-1">
          <Icon name="clock" :size="12" />
          <span class="font-mono">{{ fmtDuration(v.duration_sec) }}</span>
        </span>
        <span v-if="v.play_count" class="inline-flex items-center gap-1">
          <Icon name="eye" :size="12" />
          <span class="font-mono">{{ fmt(v.play_count) }}</span>
        </span>
        <span v-if="v.like_count" class="inline-flex items-center gap-1">
          <Icon name="heart" :size="12" />
          <span class="font-mono">{{ fmt(v.like_count) }}</span>
        </span>
        <span v-if="v.author_name" class="ml-auto truncate" :title="v.author_name">
          @{{ v.author_name }}
        </span>
      </div>
    </header>

    <!--
      AI 速览 —— 固定容器高度（120px），header 锁顶，body 区域 flex-1 +
      overflow-y-auto。摘要文本再长也不会把下方评论楼区域顶下去；空态
      （loading / 未生成按钮）也吃同一个高度槽位，整页 layout 不会因
      生成与否产生跳动。
    -->
    <div
      class="flex flex-col"
      :style="{
        margin: '14px 20px 0 20px',
        background: 'rgba(245,192,66,0.10)',
        border: '1px solid rgba(245,192,66,0.32)',
        borderRadius: '12px',
        padding: '10px 14px 12px',
        flexShrink: 0,
        height: '120px',
        gap: '6px',
        overflow: 'hidden',
      }"
    >
      <div class="flex items-center gap-1.5 flex-shrink-0">
        <span style="width: 18px; height: 18px; border-radius: 5px; background: var(--dark); color: var(--yellow); display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="spark" :size="11" />
        </span>
        <span class="text-[11px] font-semibold tracking-wide" style="color: #7a5400">AI 速览</span>
        <button
          v-if="v.ai_summary && !summaryLoading"
          type="button"
          class="ml-auto inline-flex items-center justify-center transition hover:bg-[rgba(122,84,0,0.12)]"
          :style="{
            width: '22px', height: '22px', borderRadius: '999px',
            color: '#7a5400', cursor: 'pointer',
          }"
          title="重新生成"
          @click="triggerSummarize(true)"
        ><Icon name="refresh" :size="11" /></button>
      </div>
      <!-- body 槽位：固定高度容器内 flex-1，文本溢出走内部滚动条 -->
      <div
        :style="{ flex: 1, minHeight: 0, overflowY: 'auto', paddingRight: '4px' }"
      >
        <div v-if="summaryLoading" class="flex items-center gap-2 text-[12px]" style="color: var(--ink-2);">
          <Spinner :size="12" /><span>生成中…</span>
        </div>
        <div
          v-else-if="v.ai_summary"
          class="text-[12.5px] leading-relaxed"
          style="color: var(--ink); white-space: pre-wrap;"
        >{{ v.ai_summary }}</div>
        <button
          v-else
          type="button"
          class="inline-flex items-center gap-1.5 transition"
          :style="{
            height: '28px', padding: '0 12px', borderRadius: '999px',
            fontSize: '12px', fontWeight: 500,
            background: 'var(--dark)', color: 'var(--yellow)', border: '1px solid var(--dark)', cursor: 'pointer',
          }"
          @click="triggerSummarize(false)"
        >
          <Icon name="spark" :size="12" />
          <span>点击生成 AI 速览</span>
        </button>
      </div>
    </div>

    <!-- ── 评论楼 + composer ─────────────────────────────── -->
    <div
      v-if="cardState === 'done'"
      class="flex items-center"
      :style="{
        margin: '14px 20px 20px 20px',
        background: 'rgba(122,155,94,0.10)',
        border: '1px solid rgba(122,155,94,0.32)',
        borderRadius: '12px',
        padding: '14px 16px',
        gap: '10px',
        flexShrink: 0,
      }"
    >
      <span style="width: 22px; height: 22px; border-radius: 999px; background: var(--green); color: #fff; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;">
        <Icon name="check" :size="12" />
      </span>
      <span style="font-size: 12.5px; color: #3a7d44;">
        这条已经搞定 · 共 {{ comments.length }} 层。需要补盖楼或编辑？
      </span>
      <button
        type="button"
        class="ml-auto inline-flex items-center gap-1 transition"
        :disabled="bulkBusy"
        :style="{
          height: '28px', padding: '0 12px', borderRadius: '999px',
          fontSize: '11.5px', fontWeight: 600,
          background: '#3a7d44', color: '#fff', border: '1px solid #3a7d44',
          cursor: bulkBusy ? 'wait' : 'pointer',
        }"
        @click="onResumeDrafting"
      >
        <Icon name="edit" :size="11" />
        <span>{{ bulkBusy ? "处理中…" : "继续盖楼" }}</span>
      </button>
    </div>

    <template v-else>
      <!--
        草稿态（待评论 / 盖楼中）—— 评论楼区域 flex-1 + overflow-y-auto
        撑满 header/AI 速览 下方剩余高度。CommentComposer 用 flex-shrink-0
        固定在最底部。
      -->
      <div
        class="flex flex-col"
        :style="{
          margin: '14px 20px 0 20px',
          flex: 1, minHeight: 0,
          background: cardState === 'drafting'
            ? 'rgba(238,106,42,0.06)'
            : 'var(--card-2)',
          border: '1px solid ' + (cardState === 'drafting'
            ? 'rgba(238,106,42,0.20)'
            : 'var(--line)'),
          borderRadius: '12px',
          padding: '14px',
          gap: '10px',
          overflow: 'hidden',
        }"
      >
        <div class="flex items-center gap-1.5 flex-shrink-0">
          <span
            :style="{
              width: '18px', height: '18px', borderRadius: '5px',
              background: cardState === 'drafting' ? 'var(--primary)' : 'var(--ink-4)',
              color: '#fff',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }"
          >
            <Icon name="stack" :size="11" />
          </span>
          <span
            class="text-[11px] font-semibold tracking-wide"
            :style="{ color: cardState === 'drafting' ? 'var(--primary-deep)' : 'var(--ink-3)' }"
          >
            评论楼 · {{ comments.length }} 层
          </span>
          <span
            v-if="comments.length >= 3"
            class="ml-auto text-[10.5px]"
            :style="{ color: 'var(--ink-4)' }"
          >滚动查看全部</span>
        </div>
        <!--
          flex-1 + min-h-0 + overflow-y-auto 让评论楼自动撑满剩余高度，
          多层时内部滚；少层时直接撑开，下方空白让 composer 贴底。
        -->
        <div
          :class="['floor-scroll', cardState === 'drafting' ? 'floor-scroll-active' : 'floor-scroll-idle']"
          :style="{
            flex: 1, minHeight: 0,
            overflowY: 'auto',
            paddingRight: comments.length >= 3 ? '4px' : '0',
          }"
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
              minHeight: '120px',
              background: 'var(--card-2)',
              border: '1px dashed var(--line-2)',
              borderRadius: '10px',
              color: 'var(--ink-3)',
              fontSize: '12px',
              gap: '10px',
            }"
          >
            <span
              :style="{
                width: '32px', height: '32px', borderRadius: '9px',
                background: 'var(--card)', color: 'var(--ink-4)',
                border: '1px dashed var(--line-2)',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              }"
            >
              <Icon name="comment" :size="14" />
            </span>
            <span>还没有评论 · 在下面写一条作为第 1 层</span>
          </div>
        </div>
      </div>
      <div
        :style="{
          margin: '14px 20px 20px 20px',
          flexShrink: 0,
        }"
      >
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
  </section>
</template>
