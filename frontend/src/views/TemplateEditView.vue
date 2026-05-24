<script setup lang="ts">
/**
 * 结构模板编辑/新建 独立页 —— 替代原 TemplatesView 的 inBuilder modal-takeover
 * 模式。`/templates/edit/:id`，`:id = "new"` 表示新建（templateId=null）。
 *
 * 本页是个薄壳：解析路由参数 → 渲染 <TemplateBuilder>，监听 @saved/@cancel
 * 跳回模板库列表。新建时支持 query 透传 `name` / `product` 作为 builder 的
 * 初值（保留原 CreateTemplateModal 的"先填基本信息再进 builder"流程）。
 */
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import TemplateBuilder from "@/components/templates/TemplateBuilder.vue";

const route = useRoute();
const router = useRouter();

const templateId = computed<string | null>(() => {
  const raw = route.params.id;
  const id = Array.isArray(raw) ? raw[0] : raw;
  if (!id || id === "new") return null;
  return id;
});

const initialName = computed<string>(
  () => (route.query.name as string | undefined) || "",
);
const initialProduct = computed<string>(
  () => (route.query.product as string | undefined) || "",
);

function backToList(savedId?: string) {
  // 始终回到结构模板 tab，避免新建/编辑完跳回 skills tab 找不到自己刚改的模板。
  // savedId 透传给列表页是为了将来可以"高亮选中刚保存的那张卡"，目前 list 页
  // 不依赖这个 query，丢了也无害。
  router.push({
    name: "templates",
    query: {
      tab: "templates",
      ...(savedId ? { highlight: savedId } : {}),
    },
  });
}
</script>

<template>
  <div class="flex h-full flex-col" style="gap: var(--density-gap)">
    <TemplateBuilder
      :template-id="templateId"
      :initial-name="initialName"
      :initial-product="initialProduct"
      @saved="backToList"
      @cancel="backToList()"
    />
  </div>
</template>
