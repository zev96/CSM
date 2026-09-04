<script setup lang="ts">
/**
 * 批量 AI 生成评论 —— 参数弹窗。
 *
 * 勾选视频后从中栏浮动工具条唤起。参数只有两个：每视频楼层数（1-5，
 * 上限对齐评论工作流的楼层结构；同步到腾讯文档时实际写入层数以该表表头
 * 有几列「评论X」为准，与此处设置的层数无关）+ 语气提示（选填）。模板不在这里选 ——
 * 后端自动从模板库轮换（星标/常用优先），避免同一模板高频重复出现；
 * 想控制模板池就去模板库里星标/隐藏。
 */
import { ref, watch } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Icon from "@/components/ui/Icon.vue";

const props = defineProps<{
  open: boolean;
  count: number;           // 已勾选视频数
}>();

const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "submit", payload: { tiersPerVideo: number; toneHint: string }): void;
}>();

const tiers = ref(1);
const toneHint = ref("");

watch(
  () => props.open,
  (v) => {
    if (!v) return;
    tiers.value = 1;
    toneHint.value = "";
  },
);

function close() {
  emit("update:open", false);
}

function onSubmit() {
  emit("submit", { tiersPerVideo: tiers.value, toneHint: toneHint.value.trim() });
}
</script>

<template>
  <Dialog :open="open" size="sm" @update:open="close">
    <div class="relative mb-4 flex items-start justify-between">
      <div class="font-display font-bold" style="font-size: 18px; letter-spacing: -0.4px;">
        AI 批量生成评论
      </div>
      <button
        @click="close"
        class="inline-flex items-center justify-center"
        style="width: 28px; height: 28px; border-radius: 999px; background: var(--card-2); color: var(--ink-2); border: 1px solid var(--line);"
      >
        <Icon name="x" :size="12"/>
      </button>
    </div>

    <div class="text-[12px] mb-4" style="color: var(--ink-2); line-height: 1.6;">
      对已勾选的 <b class="font-display" style="color: var(--primary-deep)">{{ count }}</b> 条视频，
      按「模板 × 视频分析」逐条改写生成评论草稿。模板从模板库自动轮换（星标优先），
      生成结果进入<b>待审核</b>队列，通过后才算数。
    </div>

    <div class="mb-4">
      <label class="text-[11.5px] font-semibold mb-1.5 block">每视频楼层数</label>
      <div class="flex" style="background: var(--card-2); border-radius: 999px; padding: 3px; border: 1px solid var(--line); max-width: 220px;">
        <button
          v-for="n in [1, 2, 3, 4, 5]" :key="n"
          @click="tiers = n"
          :style="{
            flex: 1, height: '28px', borderRadius: '999px', fontSize: '11.5px', fontWeight: 500,
            background: tiers === n ? 'var(--dark)' : 'transparent',
            color: tiers === n ? 'var(--card)' : 'var(--ink-2)',
            border: 'none', cursor: 'pointer',
          }"
        >{{ n }} 层</button>
      </div>
      <div class="mt-1.5 text-[11px]" style="color: var(--ink-3);">
        第 2 层起是盖楼跟评（与前层形成对话感）。上限 5 层，实际写入层数由腾讯文档表头的「评论X」列数决定。
      </div>
    </div>

    <div class="mb-1">
      <label class="text-[11.5px] font-semibold mb-1.5 block">语气提示（选填）</label>
      <input
        v-model="toneHint"
        placeholder="例如：宝妈口吻 / 多用 emoji / 短句"
        maxlength="100"
        class="w-full outline-none"
        style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 12px; padding: 0 12px; height: 40px; font-size: 13px; color: var(--ink);"
      />
    </div>

    <template #footer>
      <div class="flex-1"/>
      <Btn variant="ghost" @click="close">取消</Btn>
      <Btn variant="solid" :disabled="count === 0" @click="onSubmit">
        <Icon name="wand" :size="11"/> 开始生成
      </Btn>
    </template>
  </Dialog>
</template>
