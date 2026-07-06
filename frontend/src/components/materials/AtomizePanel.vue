<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useMaterials, type AtomDraft } from "@/stores/materials";
import { useNotifications } from "@/composables/useNotifications";
import Spinner from "@/components/ui/Spinner.vue";
import AtomCard from "@/components/materials/AtomCard.vue";

const m = useMaterials();
const notify = useNotifications();
const text = ref("");
const atoms = ref<AtomDraft[]>([]);
const atomizing = ref(false);
const cards = ref<any[]>([]);

onMounted(() => m.loadFolders());

const ORDER: Record<string, number> = { low: 0, med: 1, high: 2 };

async function run(): Promise<void> {
  if (!text.value.trim() || atomizing.value) return;
  atomizing.value = true; atoms.value = []; cards.value = [];
  try {
    const a = await m.atomizeText(text.value);
    if (m.lastAtomizeTruncated) {
      notify.push(`原文超长，已截尾 ${m.lastAtomizeTruncated.dropped} 字（最多 8 块）`, { tone: "warn" });
    }
    a.sort((x, y) => ORDER[x.confidence] - ORDER[y.confidence]);   // low 置顶
    atoms.value = a;
  } finally {
    atomizing.value = false;
  }
}

async function commitAll(): Promise<void> {
  let committed = 0, failed = 0, skipped = 0;
  for (const c of cards.value) {
    if (!c?.commitAuto) continue;
    const r = await c.commitAuto();
    if (r === "committed") committed++;
    else if (r === "failed") failed++;
    else skipped++;
  }
  const parts = [`成功入库 ${committed} 条`];
  if (failed) parts.push(`失败 ${failed} 条`);
  if (skipped) parts.push(`跳过（低置信/已入库）${skipped} 条`);
  notify.push(parts.join("，"), { tone: failed ? "warn" : "success" });
}
</script>

<template>
  <div class="anim-up flex min-h-0 flex-1 gap-d">
    <!-- 左：原文输入 -->
    <section class="mat-panel flex flex-none flex-col overflow-hidden" style="width: 460px">
      <div class="flex-none px-[var(--density-pad)] pb-2 pt-4">
        <div class="text-[13px] font-bold">原文</div>
        <div class="mt-1 text-[11.5px]" style="color: var(--ink-4)">粘贴一篇家电营销资料，AI 忠实拆条 + 归类，不改写原文</div>
      </div>
      <div class="flex min-h-0 flex-1 px-[var(--density-pad)] pt-2">
        <textarea
          v-model="text" data-atomize-input placeholder="在这里粘贴营销资料原文…"
          class="mat-input flex-1 resize-none leading-[1.9]" style="padding: 14px; border-radius: 14px"
        />
      </div>
      <div class="flex flex-none items-center gap-3 px-[var(--density-pad)] pb-[18px] pt-3">
        <button data-atomize-run class="mat-btn" :disabled="!text.trim() || atomizing" @click="run">
          <template v-if="atomizing || m.chunkProgress">
            <Spinner :size="13" />
            <span v-if="m.chunkProgress">分块 {{ m.chunkProgress.current }}/{{ m.chunkProgress.total }} 拆条中…</span>
            <span v-else>拆条中…</span>
          </template>
          <template v-else>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M15 4V2" /><path d="M15 16v-2" /><path d="M8 9h2" /><path d="M20 9h2" /><path d="M17.8 11.8L19 13" /><path d="M17.8 6.2L19 5" /><path d="M3 21l9-9" /><path d="M12.2 6.2L11 5" />
            </svg>
            AI 拆条
          </template>
        </button>
        <button v-if="m.chunkProgress" data-atomize-cancel class="mat-btn-border" @click="m.cancelAtomize()">取消</button>
        <span class="text-[11.5px]" style="color: var(--ink-4)">{{ text.length }} 字</span>
      </div>
    </section>

    <!-- 右：拆条结果 -->
    <section class="mat-panel flex min-w-0 flex-1 flex-col overflow-hidden">
      <!-- idle -->
      <div v-if="!atoms.length && !atomizing && !m.chunkProgress" class="flex flex-1 flex-col items-center justify-center gap-3.5 p-10 text-center">
        <div class="flex h-[58px] w-[58px] items-center justify-center rounded-full" style="background: rgba(238, 106, 42, 0.1); color: var(--primary)">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M15 4V2" /><path d="M15 16v-2" /><path d="M8 9h2" /><path d="M20 9h2" /><path d="M17.8 11.8L19 13" /><path d="M17.8 6.2L19 5" /><path d="M3 21l9-9" /><path d="M12.2 6.2L11 5" />
          </svg>
        </div>
        <div class="text-[14px] font-bold">拆条结果会出现在这里</div>
        <div class="max-w-[320px] text-[12.5px] leading-[1.8]" style="color: var(--ink-3)">AI 会把原文按素材树归类拆成独立条目；低置信度条目置顶，请重点核对后再入库。</div>
      </div>

      <!-- loading -->
      <div v-else-if="atomizing || m.chunkProgress" class="flex flex-1 flex-col items-center justify-center gap-3.5">
        <Spinner :size="26" />
        <div class="text-[12.5px]" style="color: var(--ink-3)">
          <template v-if="m.chunkProgress">分块 {{ m.chunkProgress.current }}/{{ m.chunkProgress.total }} · 忠实原文，不做改写…</template>
          <template v-else>正在拆条 · 忠实原文，不做改写…</template>
        </div>
      </div>

      <!-- done -->
      <template v-else>
        <div class="flex flex-none items-center gap-2.5 px-[var(--density-pad)] pb-2.5 pt-4">
          <span class="text-[13px] font-bold">拆出 {{ atoms.length }} 条</span>
          <span class="text-[11.5px]" style="color: var(--ink-4)">低置信度已置顶 — 核对归类是否正确、数字是否与原文一致，再入库</span>
          <button data-atomize-commit-all class="mat-btn-dark ml-auto" @click="commitAll">全部入库</button>
        </div>
        <div class="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-[var(--density-pad)] pb-[var(--density-pad)] pt-1">
          <AtomCard v-for="(a, i) in atoms" :key="i" :ref="(el) => (cards[i] = el)" :atom="a" :folders="m.writableFolders" />
        </div>
      </template>
    </section>
  </div>
</template>
