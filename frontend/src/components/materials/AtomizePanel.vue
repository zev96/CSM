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
    a.sort((x, y) => ORDER[x.confidence] - ORDER[y.confidence]);   // low 置顶
    atoms.value = a;
  } finally {
    atomizing.value = false;
  }
}

async function commitAll(): Promise<void> {
  let n = 0;
  for (const c of cards.value) {
    if (c?.commitAuto) { await c.commitAuto(); n++; }
  }
  notify.push(`已尝试入库 ${n} 条（low 置信度需逐条确认）`, { tone: "info" });
}
</script>

<template>
  <div class="flex h-full min-h-0 gap-4">
    <!-- 左：粘贴 + 拆条 -->
    <div class="flex w-96 min-w-0 flex-col gap-2">
      <label class="text-xs text-ink/50">粘贴一篇家电营销资料，AI 忠实拆条 + 归类</label>
      <textarea v-model="text" data-atomize-input rows="12" placeholder="把文章/资料整段贴这里…"
        class="w-full flex-1 rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
      <div class="flex items-center gap-2">
        <button data-atomize-run
          class="rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          :style="{ background: 'var(--primary)' }" :disabled="!text.trim() || atomizing" @click="run">
          <span v-if="atomizing" class="inline-flex items-center gap-1"><Spinner :size="12" /> 拆条中…</span>
          <span v-else>AI 拆条</span>
        </button>
        <button v-if="atoms.length" class="rounded-lg border border-ink/15 px-3 py-1.5 text-sm text-ink/70" @click="commitAll">
          全部入库（high/med）
        </button>
      </div>
      <p v-if="m.intakeError" class="text-xs" :style="{ color: 'var(--red)' }">{{ m.intakeError }}</p>
    </div>

    <!-- 右：原子卡列表 -->
    <div class="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto">
      <div v-if="!atoms.length && !atomizing" class="grid h-full place-items-center text-sm text-ink/40">
        拆条结果会出现在这里（低置信度置顶，请重点核对）
      </div>
      <AtomCard v-for="(a, i) in atoms" :key="i" :ref="(el) => (cards[i] = el)"
        :atom="a" :folders="m.writableFolders" />
    </div>
  </div>
</template>
