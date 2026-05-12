<script setup lang="ts">
/**
 * 新建模板的轻量模态：只问模板名 + 适合产品。
 * 提交后由父组件接管，把这两个字段当作初值带进 TemplateBuilder；
 * 模板 ID 在 builder 保存时由名字 + 时间戳自动 slug，不让用户填。
 */
import { ref, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "submit", payload: { name: string; product: string }): void;
}>();

const name = ref("");
const product = ref("");

watch(
  () => props.open,
  (v) => {
    if (v) {
      name.value = "";
      product.value = "";
    }
  },
);

function close() {
  emit("update:open", false);
}
function submit() {
  if (!name.value.trim() || !product.value.trim()) return;
  emit("submit", { name: name.value.trim(), product: product.value.trim() });
  close();
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/30"
      @click.self="close"
    >
      <div
        class="anim-up bg-bg-inner p-6"
        :style="{ width: '440px', maxWidth: '92vw', borderRadius: 'var(--radius-card)' }"
      >
        <div class="mb-4 flex items-center justify-between">
          <div class="font-display text-[16px] font-semibold">新建模板</div>
          <button type="button" @click="close">
            <Icon name="x" :size="18" />
          </button>
        </div>

        <div class="flex flex-col gap-4">
          <FormField label="模板名" hint="出现在模板库列表里的名字。">
            <FormInput
              v-model="name"
              placeholder="如 导购 · 吸尘器"
              debounce="live"
            />
          </FormField>

          <FormField label="适合产品类别" hint="这个模板写的是什么产品，用于检索时匹配。">
            <FormInput
              v-model="product"
              placeholder="如 无线吸尘器"
              debounce="live"
            />
          </FormField>
        </div>

        <div class="mt-6 flex justify-end gap-2">
          <Btn variant="ghost" small @click="close">取消</Btn>
          <Btn
            variant="solid"
            small
            :disabled="!name.trim() || !product.trim()"
            @click="submit"
          >
            <Icon name="arrowRight" :size="13" />
            <span>下一步 · 编辑结构</span>
          </Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
