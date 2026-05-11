<script setup lang="ts">
/**
 * Render the AssemblyPlan as an editable block tree.
 *
 * For each ``BlockResult`` we show:
 *   - The kind badge + label / id
 *   - Each PickedVariant on its own row, with the picked text + source
 *   - A "重随" button on rows whose source is rerollable
 *
 * Rerollable kinds (per csm_core.assembler.reroll._get_notes_source):
 *   paragraph / numbered_list / competitor_pool — the rest are literal
 *   text (heading / hero_brand / literal / test_framework).
 *
 * Children of paragraph blocks are rendered nested with an indent.
 */
import { ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import { useArticle } from "@/stores/article";
import { useToast } from "@/composables/useToast";

interface PickedVariant {
  note_id: string;
  variant_index: number;
  text: string;
  meta: Record<string, any>;
}
interface BlockResultDTO {
  block_id: string;
  kind: string;
  picks: PickedVariant[];
  text: string;
  meta: Record<string, any>;
  note: string;
  children: BlockResultDTO[];
}

defineProps<{
  results: BlockResultDTO[];
  /** Indent depth for nested children, defaults to 0 at the root. */
  depth?: number;
}>();

const article = useArticle();
const toast = useToast();
const rerollingKey = ref<string | null>(null);

const REROLLABLE_KINDS = new Set([
  "paragraph",
  "numbered_list",
  "competitor_pool",
]);

function isRerollable(kind: string): boolean {
  return REROLLABLE_KINDS.has(kind);
}

async function reroll(blockId: string, pickIndex: number) {
  const key = `${blockId}:${pickIndex}`;
  if (rerollingKey.value) return;
  rerollingKey.value = key;
  try {
    const ok = await article.rerollPick(blockId, pickIndex);
    if (ok) toast.success("已换新一段");
  } catch (e: any) {
    const msg = String(e?.message ?? e);
    if (msg.includes("exhausted") || msg.includes("no more candidates")) {
      toast.warn("候选池已抽干 — 没有更多变体可换");
    } else if (msg.includes("unknown job_id")) {
      toast.warn("生成记录已过期 — 请先重新起飞");
    } else {
      toast.error(`重随失败：${msg}`);
    }
  } finally {
    rerollingKey.value = null;
  }
}

const KIND_LABEL: Record<string, string> = {
  paragraph: "段落",
  heading: "标题",
  numbered_list: "编号列表",
  hero_brand: "主推",
  competitor_pool: "竞品",
  literal: "字面量",
  test_framework: "测试框架",
};
</script>

<template>
  <div :style="{ paddingLeft: `${(depth ?? 0) * 16}px` }" class="flex flex-col gap-2">
    <div
      v-for="r in results"
      :key="r.block_id"
      class="bg-card-2 px-3 py-2.5 text-[12.5px]"
      :style="{ borderRadius: 'var(--radius-inner)', border: '1px solid var(--line)' }"
    >
      <!-- Header -->
      <div class="flex items-center gap-2 mb-1.5">
        <Pill>{{ KIND_LABEL[r.kind] ?? r.kind }}</Pill>
        <span class="font-mono text-[10.5px] text-ink-3">{{ r.block_id }}</span>
        <span v-if="r.note" class="text-[11px] text-ink-3 italic truncate">— {{ r.note }}</span>
      </div>

      <!-- Picks list (paragraph / numbered_list / competitor_pool) -->
      <ul v-if="r.picks?.length" class="flex flex-col gap-1.5">
        <li
          v-for="(p, i) in r.picks"
          :key="`${r.block_id}-${i}`"
          class="flex items-start gap-2"
        >
          <span class="font-mono text-[10.5px] text-ink-3 tabular-nums shrink-0 mt-0.5">
            {{ i + 1 }}.
          </span>
          <div class="min-w-0 flex-1">
            <div class="font-serif-cn leading-relaxed">{{ p.text }}</div>
            <div class="font-mono text-[10.5px] text-ink-3 mt-0.5 truncate">
              {{ p.note_id }}<span v-if="p.variant_index >= 0"> · 变体 {{ p.variant_index }}</span>
            </div>
          </div>
          <Btn
            v-if="isRerollable(r.kind)"
            variant="ghost"
            small
            :disabled="rerollingKey !== null"
            @click="reroll(r.block_id, i)"
          >
            <Spinner v-if="rerollingKey === `${r.block_id}:${i}`" :size="11" />
            <Icon v-else name="refresh" :size="11" />
            <span>重随</span>
          </Btn>
        </li>
      </ul>

      <!-- Literal text (heading / hero_brand / literal) -->
      <div v-else-if="r.text" class="font-serif-cn leading-relaxed">{{ r.text }}</div>
      <div v-else class="text-[11.5px] text-ink-3 italic">（空块）</div>

      <!-- Recurse into children (paragraph nesting) -->
      <AssemblyTree
        v-if="r.children?.length"
        :results="r.children"
        :depth="(depth ?? 0) + 1"
        class="mt-2"
      />
    </div>
  </div>
</template>
