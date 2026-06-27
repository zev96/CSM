<script setup lang="ts">
/**
 * 禁区 lint 审查面板 —— 成稿被禁区 lint 命中时弹（ArticleView 监听
 * article.lintBlocking 自动弹）。机械类（emoji/破折号/双引号）「一键清」
 * 批量修；判断类（元话术/绝对化/引流）逐条「本次放行」或回成稿手改。
 * 全部清/放行后「确认并导出」emit proceed（ArticleView 开导出 modal）。
 * 镜像 FactCheckPanel 的 Dialog chrome。
 */
import { computed } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Pill from "@/components/ui/Pill.vue";
import { useArticle, type LintHit } from "@/stores/article";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ proceed: [] }>();
const article = useArticle();

const CAT_LABEL: Record<string, string> = {
  meta_speak: "元话术", absolute: "绝对化", traffic: "引流",
  emoji: "emoji", dash: "破折号", quote: "双引号",
};
const lintKey = (h: LintHit) => `${h.category}:${h.start}:${h.text}`;
const hits = computed<LintHit[]>(() => article.lint?.hits ?? []);
const hasMechanical = computed(() => hits.value.some((h) => h.fixable));
function isReleased(h: LintHit) { return article.lintReleased.includes(lintKey(h)); }

async function autofix() { await article.autofixLint(); }
async function recheck() { if (article.finalText.trim()) await article.runLint(article.finalText); }
function proceed() { emit("proceed"); open.value = false; }
</script>

<template>
  <Dialog v-model:open="open" title="禁区检查 — 发现违规措辞/标点" size="lg">
    <div class="flex flex-col gap-3">
      <p class="text-ink-3 text-sm">
        机械类（emoji/破折号/双引号）可「一键清」批量修；判断类（元话术/绝对化/引流）请在「成稿」改写，或勾「本次放行」（确认是合理表述）。全部处理后才可导出。
      </p>
      <ul class="flex flex-col gap-2">
        <li v-for="(h, i) in hits" :key="i" data-lint-hit class="border-ink/10 rounded-lg border p-3">
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-sm">
              <Pill>{{ CAT_LABEL[h.category] }}</Pill>
              <span class="font-medium">{{ h.text }}</span>
            </div>
            <label v-if="!h.fixable" class="text-ink-3 flex items-center gap-1 text-xs">
              <input type="checkbox" :checked="isReleased(h)" @change="article.toggleLintRelease(h)" />
              本次放行
            </label>
            <span v-else class="text-ink-4 text-[11px]">可一键清</span>
          </div>
          <div class="text-ink-3 mt-1 text-xs">{{ h.sentence }}</div>
          <div class="text-ink-4 mt-1 text-[11px]">建议：{{ h.suggestion }}</div>
        </li>
      </ul>
    </div>
    <template #footer>
      <Btn v-if="hasMechanical" variant="ghost" small data-lint-autofix @click="autofix">一键清机械类</Btn>
      <Btn variant="ghost" small data-lint-recheck @click="recheck">重新检查</Btn>
      <Btn variant="solid" small data-lint-proceed :disabled="article.lintBlocking" @click="proceed">
        确认并导出
      </Btn>
    </template>
  </Dialog>
</template>
