<script setup lang="ts">
/**
 * One settings section card. Wraps a title + optional description and a
 * vertically-stacked list of FormField children. Section ID is provided
 * by the parent SettingsView so the side-nav anchor scroll works.
 */
import Card from "@/components/ui/Card.vue";

defineProps<{
  title: string;
  desc?: string;
}>();
</script>

<template>
  <Card>
    <div class="mb-4">
      <h2 class="font-display text-[16px] font-semibold">{{ title }}</h2>
      <p v-if="desc" class="mt-1 text-[12.5px] text-ink-3">{{ desc }}</p>
    </div>
    <div class="flex flex-col gap-d">
      <slot />
    </div>
  </Card>
</template>
