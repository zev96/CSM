<script setup lang="ts">
/**
 * Single comment row inside a VideoCard's 评论楼.
 *
 * Renders one tier of a comment draft: a small "第 N 层" pill on top
 * left, copy + delete icon buttons top right, the body text, and a
 * horizontal strip of 48×48 image thumbnails (each thumb opens the
 * full-size image in a new tab — we deliberately don't ship a modal
 * preview yet, per Phase 2 scope).
 *
 * The component is purely presentational. Copy uses the browser
 * Clipboard API and emits ``copy`` so the parent (VideoCard) can show
 * a toast; delete just emits ``delete`` with the comment id so the
 * parent decides whether to confirm.
 */
import { computed, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import type { Comment } from "@/stores/mining";

const props = defineProps<{
  comment: Comment;
  videoId: number;
}>();

const emit = defineEmits<{
  (e: "delete", id: number): void;
  (e: "copy"): void;
}>();

// 评论里 image_urls 是相对路径（"/api/mining/images/..."），需要拼上
// sidecar 的 baseURL + token 才能在 WebView 里实际请求到。SSE 那条用
// 的也是同一套 sseURL builder，复用。
const sidecar = useSidecar();
const thumbUrls = computed(() =>
  (props.comment.image_urls || []).map(u => sidecar.sseURL(u))
);

const isCopying = ref(false);

async function onCopy() {
  if (isCopying.value) return;
  isCopying.value = true;
  try {
    await navigator.clipboard.writeText(props.comment.text || "");
    emit("copy");
  } catch {
    // Clipboard API can fail in non-secure contexts (rare in Tauri but
    // theoretically possible). Silently swallow — the parent toast won't
    // fire and the user can retry. We avoid a hard console.error so the
    // production build stays quiet.
  } finally {
    isCopying.value = false;
  }
}
</script>

<template>
  <div
    class="flex flex-col"
    :style="{
      background: 'var(--card-white)',
      border: '1px solid var(--line)',
      borderRadius: '10px',
      padding: '10px 11px 9px',
    }"
  >
    <!-- 顶部：tier 徽章 + 操作按钮 -->
    <div class="flex items-center gap-2">
      <span
        class="inline-flex items-center"
        :style="{
          height: '20px',
          padding: '0 8px',
          borderRadius: '999px',
          background: 'var(--primary-soft)',
          color: 'var(--primary-deep)',
          fontSize: '10.5px',
          fontWeight: 600,
          letterSpacing: '0.2px',
        }"
      >第 {{ comment.tier }} 层</span>
      <span
        v-if="comment.source === 'ai_suggested'"
        class="inline-flex items-center gap-1"
        :style="{
          height: '20px',
          padding: '0 7px',
          borderRadius: '999px',
          background: 'rgba(245,192,66,0.18)',
          color: '#7a5400',
          fontSize: '10px',
          fontWeight: 500,
        }"
      ><Icon name="wand" :size="9"/> AI</span>
      <div class="ml-auto flex items-center gap-1">
        <button
          type="button"
          class="inline-flex items-center justify-center transition hover:bg-[rgba(28,26,23,0.05)]"
          :style="{
            width: '24px',
            height: '24px',
            borderRadius: '999px',
            color: 'var(--ink-3)',
          }"
          :disabled="isCopying"
          title="复制评论文本"
          @click="onCopy"
        ><Icon name="copy" :size="12"/></button>
        <button
          type="button"
          class="inline-flex items-center justify-center transition hover:bg-[rgba(28,26,23,0.05)]"
          :style="{
            width: '24px',
            height: '24px',
            borderRadius: '999px',
            color: 'var(--ink-3)',
          }"
          title="删除评论"
          @click="emit('delete', comment.id)"
        ><Icon name="trash" :size="12"/></button>
      </div>
    </div>

    <!-- 正文文本 -->
    <div
      class="mt-1.5 whitespace-pre-wrap break-words"
      :style="{
        fontSize: '12.5px',
        lineHeight: 1.55,
        color: 'var(--ink)',
      }"
    >{{ comment.text || "（空草稿）" }}</div>

    <!-- 缩略图（点击新窗口看原图） -->
    <div
      v-if="thumbUrls.length"
      class="mt-2 flex flex-wrap items-center gap-1.5"
    >
      <a
        v-for="(url, i) in thumbUrls"
        :key="comment.image_ids[i] || i"
        :href="url"
        target="_blank"
        rel="noopener"
        :title="'查看原图 #' + (i + 1)"
        :style="{
          width: '48px',
          height: '48px',
          borderRadius: '8px',
          overflow: 'hidden',
          border: '1px solid var(--line-2)',
          background: 'var(--card-2)',
          display: 'block',
        }"
      >
        <img
          :src="url"
          :alt="'comment image ' + (i + 1)"
          loading="lazy"
          :style="{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            display: 'block',
          }"
        />
      </a>
    </div>
  </div>
</template>
