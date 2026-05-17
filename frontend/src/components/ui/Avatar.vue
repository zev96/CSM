<script setup lang="ts">
/**
 * Tiny first-letter avatar used in author chips. Ported from CSM-RE1
 * ui.jsx::Avatar. If no ``color`` prop is supplied we hash the name
 * into one of a handful of palette colors so repeated renders are
 * stable.
 */
const props = withDefaults(
  defineProps<{
    name: string;
    size?: number;
    /** Background color — pass an explicit color or let us hash one. */
    color?: string;
  }>(),
  { size: 24 },
);

const PALETTE = [
  "#ee6a2a", "#f5c042", "#7a9b5e", "#5b8def",
  "#c25d8f", "#9f7ab0", "#d8946a", "#5fa8b3",
];

function hashColor(name: string): string {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}

const bg = () => props.color || hashColor(props.name || "?");
const letter = () => (props.name || "?").trim().slice(0, 1).toUpperCase();
</script>

<template>
  <span
    class="inline-flex items-center justify-center font-semibold text-white flex-shrink-0"
    :style="{
      width: size + 'px',
      height: size + 'px',
      borderRadius: '999px',
      background: bg(),
      fontSize: Math.max(9, size * 0.42) + 'px',
      lineHeight: 1,
    }"
  >
    {{ letter() }}
  </span>
</template>
