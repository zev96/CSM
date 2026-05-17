<script setup lang="ts">
/**
 * Soft blurred decoration blob — used to recreate the warm glow on
 * dark hero cards. Heavy CSS blur turns a solid round div into a
 * lighting effect. Always pointer-events: none.
 */
withDefaults(
  defineProps<{
    color: string;
    size?: number;
    top?: number | string;
    left?: number | string;
    right?: number | string;
    bottom?: number | string;
    opacity?: number;
  }>(),
  { size: 200, opacity: 0.35 },
);
</script>

<template>
  <span
    aria-hidden="true"
    class="blur-blob"
    :style="{
      position: 'absolute',
      width: size + 'px',
      height: size + 'px',
      borderRadius: '999px',
      background: color,
      opacity,
      top: top != null ? (typeof top === 'number' ? top + 'px' : top) : undefined,
      left: left != null ? (typeof left === 'number' ? left + 'px' : left) : undefined,
      right: right != null ? (typeof right === 'number' ? right + 'px' : right) : undefined,
      bottom: bottom != null ? (typeof bottom === 'number' ? bottom + 'px' : bottom) : undefined,
    }"
  />
</template>
