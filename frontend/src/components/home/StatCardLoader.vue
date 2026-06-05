<script setup lang="ts">
/**
 * StatCard 取数包装：从某个 history 端点拉 kpis，算 value + 较上周 delta，
 * 渲染 StatCard，点击跳监测中心对应 tab。百度/知乎问题/知乎搜索 三张共用。
 *
 *   value = kpis[valueKey]（changed_keywords / changed_questions）
 *   delta = value - kpis.changed_prev（无 changed_prev → null，不显示徽章）
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import StatCard from "@/components/home/StatCard.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

const props = defineProps<{
  category: string;
  endpoint: string;
  valueKey: string; // "changed_keywords" | "changed_questions"
  tab: string;
}>();

const sidecar = useSidecar();
const router = useRouter();
const { whenReady } = useSidecarReady();

const value = ref(0);
const delta = ref<number | null>(null);
const loaded = ref(false);

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get(props.endpoint, { params: { range: "7d" } });
    const k = r.data?.kpis ?? {};
    value.value = Number(k[props.valueKey] ?? 0);
    delta.value =
      typeof k.changed_prev === "number" ? value.value - k.changed_prev : null;
  } catch {
    /* 静默：空态顶住 */
  } finally {
    loaded.value = true;
  }
});
</script>

<template>
  <StatCard
    :category="category"
    :value="value"
    :delta="delta"
    :loaded="loaded"
    @detail="router.push({ name: 'monitor', query: { tab } })"
  />
</template>
