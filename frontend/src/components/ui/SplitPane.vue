<script setup lang="ts">
/**
 * 监控页两栏壳 —— GEO 比例（左定宽 + 右自适应）固化一处；窄屏(<lg) 上下堆叠。
 * 各页只填 #left / #right 插槽。
 */
import { ref, onMounted, onBeforeUnmount, computed } from "vue";

const props = defineProps<{ leftWidth?: string; gap?: string }>();

const wide = ref(true);
let mq: MediaQueryList | null = null;
const onChange = () => { wide.value = mq?.matches ?? true; };
onMounted(() => {
  mq = window.matchMedia("(min-width: 1024px)");
  wide.value = mq.matches;
  mq.addEventListener("change", onChange);
});
onBeforeUnmount(() => mq?.removeEventListener("change", onChange));

const gridStyle = computed(() => ({
  display: "grid",
  minHeight: "0",
  flex: "1",
  gap: props.gap ?? "18px",
  gridTemplateColumns: wide.value ? `${props.leftWidth ?? "340px"} 1fr` : "1fr",
}));
</script>

<template>
  <div :style="gridStyle">
    <div class="min-h-0 min-w-0"><slot name="left" /></div>
    <div class="min-h-0 min-w-0"><slot name="right" /></div>
  </div>
</template>
