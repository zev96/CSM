<script setup lang="ts">
/**
 * Single 楼 (floor) in a VideoCard's tower-style 评论楼.
 *
 * Visual model — a numbered circle on the LEFT, comment body on the RIGHT.
 * A faint vertical line in the parent (FloorList) runs behind the circles
 * to connect floors visually; this component itself only renders one row.
 *
 * State-driven color:
 *   - 盖楼中 (tone="active")  → orange circle, plain card body
 *   - 已完成 (tone="done")    → green circle, green-tinted card body
 *
 * Actions emitted upwards:
 *   - ``edit`` → parent loads this comment into the composer
 *   - ``delete`` → parent confirms + calls store.deleteComment
 *
 * Copy is intentionally NOT exposed as a per-floor icon any more —
 * VideoCard's ⋯ menu has "复制全部评论" which covers the same need
 * without bloating the floor row's right edge.
 */
import { computed } from "vue";

import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import type { Comment } from "@/stores/mining";

const props = defineProps<{
  comment: Comment;
  /** "active" = 盖楼中 (orange), "done" = 已完成 (green). */
  tone: "active" | "done";
}>();

defineEmits<{
  (e: "edit", id: number): void;
  (e: "delete", id: number): void;
}>();

const sidecar = useSidecar();
const thumbUrls = computed(() =>
  (props.comment.image_urls || []).map(u => sidecar.sseURL(u)),
);

// Color tokens centralized so the same palette is reused below.
const circleBg = computed(() =>
  props.tone === "done" ? "var(--green)" : "var(--primary)",
);
const ts = computed(() => {
  // Tier rows show 创建 timestamp; mm-dd HH:MM is plenty for "when did I
  // write this" without dragging in dayjs.
  const d = new Date(props.comment.updated_at || props.comment.created_at);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
});
</script>

<template>
  <div
    class="flex items-stretch"
    style="gap: 10px; position: relative;"
  >
    <!-- 编号圆圈（左列）. The faint vertical line is drawn by FloorList. -->
    <div
      class="flex-shrink-0 flex items-start justify-center"
      style="width: 22px; position: relative; z-index: 1;"
    >
      <span
        class="inline-flex items-center justify-center font-display font-semibold"
        :style="{
          width: '22px',
          height: '22px',
          borderRadius: '999px',
          background: circleBg,
          color: '#fff',
          fontSize: '11px',
          marginTop: '1px',
          boxShadow: '0 0 0 3px var(--card)',
        }"
      >{{ comment.tier }}</span>
    </div>

    <!-- 内容区 -->
    <div
      class="flex-1 min-w-0 flex flex-col"
      :style="{
        background: tone === 'done' ? 'rgba(122,155,94,0.10)' : 'var(--card-white)',
        border: '1px solid ' + (tone === 'done' ? 'rgba(122,155,94,0.32)' : 'var(--line)'),
        borderRadius: '10px',
        padding: '8px 11px 6px',
      }"
    >
      <!-- 正文 -->
      <div
        class="whitespace-pre-wrap break-words"
        :style="{
          fontSize: '12.5px',
          lineHeight: 1.55,
          color: 'var(--ink)',
        }"
      >{{ comment.text || "（空草稿）" }}</div>

      <!-- 图片缩略图行 -->
      <div
        v-if="thumbUrls.length"
        class="mt-1.5 flex flex-wrap items-center"
        style="gap: 6px;"
      >
        <a
          v-for="(url, i) in thumbUrls"
          :key="comment.image_ids[i] || i"
          :href="url"
          target="_blank"
          rel="noopener"
          :title="'查看原图 #' + (i + 1)"
          :style="{
            width: '50px',
            height: '50px',
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

      <!-- 底部：时间 + 编辑 + 删除 -->
      <div
        class="mt-1.5 flex items-center"
        style="gap: 4px; font-size: 10.5px; color: var(--ink-3);"
      >
        <span v-if="ts" class="font-mono">{{ ts }}</span>
        <span v-if="comment.source === 'ai_suggested'"
          class="inline-flex items-center gap-1"
          style="color: var(--yellow-deep);"
        >
          <span style="margin: 0 2px;">·</span>
          <Icon name="wand" :size="9"/> AI
        </span>
        <div class="ml-auto flex items-center" style="gap: 2px;">
          <button
            type="button"
            class="inline-flex items-center gap-1 transition hover:bg-[rgba(var(--ink-rgb),0.05)]"
            :style="{
              height: '20px',
              padding: '0 7px',
              borderRadius: '6px',
              color: 'var(--ink-3)',
              fontSize: '10.5px',
              cursor: 'pointer',
            }"
            title="编辑这层"
            @click="$emit('edit', comment.id)"
          ><Icon name="edit" :size="10"/><span>编辑</span></button>
          <button
            type="button"
            class="inline-flex items-center gap-1 transition hover:bg-[rgba(216,90,72,0.10)]"
            :style="{
              height: '20px',
              padding: '0 7px',
              borderRadius: '6px',
              color: 'var(--ink-3)',
              fontSize: '10.5px',
              cursor: 'pointer',
            }"
            title="删除这层"
            @click="$emit('delete', comment.id)"
          ><Icon name="trash" :size="10"/><span>删除</span></button>
        </div>
      </div>
    </div>
  </div>
</template>
