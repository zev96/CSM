<script setup lang="ts">
/**
 * Tower-style 评论楼 list.
 *
 * Renders a vertical 1px line on the left, with FloorItem rows stacked
 * down it. The numbered circles in each FloorItem ride on z-index 1 with
 * a halo (boxShadow ring matching the card background) so the line
 * appears to terminate cleanly at each circle's edge — cheaper than
 * computing pixel-perfect segments between circles.
 *
 * Tone is applied uniformly: ``active`` (盖楼中, orange) or ``done``
 * (已完成, green). VideoCard decides which to pass.
 */
import FloorItem from "./FloorItem.vue";
import type { Comment } from "@/stores/mining";

defineProps<{
  comments: Comment[];
  tone: "active" | "done";
}>();

defineEmits<{
  (e: "edit", id: number): void;
  (e: "delete", id: number): void;
}>();
</script>

<template>
  <div class="relative flex flex-col" style="gap: 10px;">
    <!-- 左侧竖线 — draws behind the floor rows (z=0). Floor circles use
         a card-color box-shadow to look like the line stops at each
         circle without us having to draw N segments. -->
    <div
      aria-hidden="true"
      :style="{
        position: 'absolute',
        top: '4px',
        bottom: '4px',
        left: '10.5px',
        width: '1px',
        background: tone === 'done'
          ? 'rgba(122,155,94,0.30)'
          : 'rgba(238,106,42,0.30)',
        zIndex: 0,
      }"
    />
    <FloorItem
      v-for="c in comments"
      :key="c.id"
      :comment="c"
      :tone="tone"
      @edit="(id: number) => $emit('edit', id)"
      @delete="(id: number) => $emit('delete', id)"
    />
  </div>
</template>
