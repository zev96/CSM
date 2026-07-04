<script setup lang="ts">
/**
 * 完整性缺失面板 —— 激进契约删稿后，主推型号关键事实缺失清单（软提醒）。
 * 纯信息展示：不拦导出、无 proceed（PR#148 教训只约束带 proceed 的门禁面板）。
 */
import Dialog from "@/components/ui/Dialog.vue";
import Pill from "@/components/ui/Pill.vue";
import { useArticle } from "@/stores/article";

const open = defineModel<boolean>("open", { default: false });
const article = useArticle();
</script>

<template>
  <Dialog v-model:open="open" title="完整性检查 — 主推事实缺失" size="md">
    <p class="text-ink-3 text-sm">
      激进契约允许删减，以下主推型号关键事实在成稿中消失了。可回「成稿」手动补回，或重新润色。
    </p>
    <ul class="mt-3 flex flex-col gap-2">
      <li v-for="(m, i) in article.completeness?.missing ?? []" :key="i"
          data-missing-fact class="border-ink/10 rounded-lg border p-3">
        <div class="flex items-center gap-2 text-sm">
          <Pill tone="warn">{{ m.kind === "number" ? "参数" : "认证" }}</Pill>
          <span class="font-medium">{{ m.token }}</span>
        </div>
        <div class="text-ink-3 mt-1 text-xs">初稿：{{ m.sentence }}</div>
      </li>
    </ul>
  </Dialog>
</template>
