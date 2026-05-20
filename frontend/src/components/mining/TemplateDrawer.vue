<script setup lang="ts">
/**
 * TemplateDrawer — full template library browser.
 *
 * STUB for T10: emits the contract so CommentComposer compiles. T11
 * replaces this with the actual searchable / sortable / tag-filterable
 * drawer.
 */
import type { Template } from "@/stores/templates"

defineEmits<{
  (e: "close"): void
  (e: "pick", tpl: Template): void
}>()
</script>

<template>
  <!-- Stub — T11 implements full drawer -->
  <div />
</template>
