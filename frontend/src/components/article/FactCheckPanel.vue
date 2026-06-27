<script setup lang="ts">
/**
 * 事实核对审查面板 —— 生成被 Plan 3 硬门禁拦下时弹出（ArticleView 监听
 * `article.factcheck.blocked` 自动弹）。列出疑似编造的数字/认证违规项，
 * 每项一个「本次放行」勾选；用户改完「成稿」或勾选放行后点「重新核对并
 * 导出」，走 `article.resolveFactcheck`（→ `POST /api/generate/{id}/export`
 * 的放行门禁）。全部违规清掉才会导出（ok=true 时清 factcheck + 关面板）。
 *
 * 放行回传的关键点：number 违规回传**归一值** `v.number`（万已展开，如
 * "15万转" → 150000），不是 parseFloat(v.value)；cert 违规回传 `v.value`
 * （认证名，如 "CCC"）。这样万-值才对得上后端白名单。
 *
 * Dialog 镜像 ArticleView 既有导出 modal 的 chrome（v-model:open / title /
 * size / #footer slot）。
 */
import { computed, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Pill from "@/components/ui/Pill.vue";
import { useToast } from "@/composables/useToast";
import { useArticle, type FactcheckViolation } from "@/stores/article";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ lint: [] }>();
const article = useArticle();
const toast = useToast();

const submitting = ref(false);
const released = ref<Set<string>>(new Set());

const violations = computed<FactcheckViolation[]>(() => article.factcheck?.violations ?? []);
const vkey = (v: FactcheckViolation) => `${v.kind}:${v.value}`;
function toggle(v: FactcheckViolation) {
  const k = vkey(v);
  if (released.value.has(k)) released.value.delete(k);
  else released.value.add(k);
}
function isReleased(v: FactcheckViolation) {
  return released.value.has(vkey(v));
}

async function recheckExport() {
  if (article.lintBlocking) { emit("lint"); open.value = false; return; }
  submitting.value = true;
  const nums: number[] = [];
  const certs: string[] = [];
  for (const v of violations.value) {
    if (!isReleased(v)) continue;
    if (v.kind === "number" && v.number != null) nums.push(v.number);
    else if (v.kind === "cert") certs.push(v.value);
  }
  const r = await article.resolveFactcheck(article.finalText, nums, certs);
  submitting.value = false;
  if (r.ok) {
    toast.success("已通过事实核对并导出");
    released.value.clear();
    open.value = false;
  } else if (r.error) {
    toast.error(`核对失败：${r.error}`);
  } else {
    toast.warn(`仍有 ${r.violations?.length ?? 0} 处未解决（已勾选的可放行，其余请在「成稿」改写）`);
  }
}
</script>

<template>
  <Dialog v-model:open="open" title="事实核对 — 发现疑似编造的数字/认证" size="lg">
    <div class="flex flex-col gap-3">
      <p class="text-ink-3 text-sm">
        以下数字/认证不在该型号的事实白名单里。可在「成稿」标签改写后重新核对，或勾选「本次放行」（确认是通用表述、非型号参数）。全部清掉才会导出。
      </p>
      <ul class="flex flex-col gap-2">
        <li
          v-for="(v, i) in violations"
          :key="i"
          class="border-ink/10 rounded-lg border p-3"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-sm">
              <Pill>{{ v.kind === "number" ? "数字" : "认证" }}</Pill>
              <span class="font-medium">{{ v.value }}</span>
            </div>
            <label class="text-ink-3 flex items-center gap-1 text-xs">
              <input type="checkbox" :checked="isReleased(v)" @change="toggle(v)" />
              本次放行
            </label>
          </div>
          <div class="text-ink-3 mt-1 text-xs">{{ v.sentence }}</div>
          <div class="text-ink-4 mt-1 text-[11px]">建议：{{ v.suggestion }}</div>
        </li>
      </ul>
    </div>
    <template #footer>
      <Btn variant="ghost" small :disabled="submitting" @click="open = false">关闭（去改正文）</Btn>
      <Btn
        variant="solid"
        small
        :disabled="submitting || !violations.length"
        @click="recheckExport"
      >
        {{ submitting ? "核对中…" : "重新核对并导出" }}
      </Btn>
    </template>
  </Dialog>
</template>
