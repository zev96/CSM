<script setup lang="ts">
/** 使用反馈面板（§6.4）—— 素材表现 + 角度组合表现两张简表。空态引导先导出。 */
import { onMounted, ref } from "vue";

import Spinner from "@/components/ui/Spinner.vue";
import { feedbackStats, type AngleStat, type NoteStat } from "@/api/client";

const loading = ref(true);
const error = ref<string | null>(null);
const notes = ref<NoteStat[]>([]);
const angles = ref<AngleStat[]>([]);

function pct(v: number | null): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}
function num(v: number | null): string {
  return v == null ? "—" : v.toFixed(1);
}

onMounted(async () => {
  try {
    const r = await feedbackStats();
    notes.value = r.notes ?? [];
    angles.value = r.angles ?? [];
  } catch (e: any) {
    error.value = e?.message ?? String(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="h-full min-h-0 overflow-y-auto">
    <div v-if="loading" class="flex items-center gap-2 p-3 text-sm text-ink/50">
      <Spinner :size="14" /> 加载中…
    </div>
    <div v-else-if="error" class="p-3 text-sm" :style="{ color: 'var(--red)' }">加载失败：{{ error }}</div>
    <div v-else-if="!notes.length && !angles.length" class="p-10 text-center text-sm text-ink/45">
      导出文章后这里会积累使用统计。
    </div>
    <div v-else class="flex flex-col gap-6">
      <section>
        <h2 class="mb-2 text-[13px] font-semibold">素材表现（保留度高 = 改得少 = 好用）</h2>
        <div class="overflow-x-auto rounded-card" :style="{ background: 'var(--card-2)' }">
          <table class="w-full text-[12px]">
            <thead :style="{ color: 'var(--ink-4)' }">
              <tr class="text-left">
                <th class="px-3 py-2 font-medium">素材</th>
                <th class="px-3 py-2 font-medium">用量</th>
                <th class="px-3 py-2 font-medium">保留度</th>
                <th class="px-3 py-2 font-medium">平均编辑</th>
                <th class="px-3 py-2 font-medium">平均分</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="n in notes" :key="n.note_id" :style="{ borderTop: '1px solid var(--card)' }">
                <td class="font-mono max-w-[240px] truncate px-3 py-2">{{ n.note_id }}</td>
                <td class="px-3 py-2">{{ n.uses }}</td>
                <td class="px-3 py-2">{{ pct(n.keep_score) }}</td>
                <td class="px-3 py-2">{{ pct(n.avg_edit_ratio) }}</td>
                <td class="px-3 py-2">{{ num(n.avg_score) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="angles.length">
        <h2 class="mb-2 text-[13px] font-semibold">角度组合表现</h2>
        <div class="overflow-x-auto rounded-card" :style="{ background: 'var(--card-2)' }">
          <table class="w-full text-[12px]">
            <thead :style="{ color: 'var(--ink-4)' }">
              <tr class="text-left">
                <th class="px-3 py-2 font-medium">人群</th>
                <th class="px-3 py-2 font-medium">卖点</th>
                <th class="px-3 py-2 font-medium">语调</th>
                <th class="px-3 py-2 font-medium">用量</th>
                <th class="px-3 py-2 font-medium">平均编辑</th>
                <th class="px-3 py-2 font-medium">平均分</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(a, i) in angles" :key="i" :style="{ borderTop: '1px solid var(--card)' }">
                <td class="px-3 py-2">{{ a.audience ?? "—" }}</td>
                <td class="max-w-[220px] truncate px-3 py-2">
                  {{ a.sellpoints.length ? a.sellpoints.join("、") : "—" }}
                </td>
                <td class="px-3 py-2">{{ a.tone ?? "—" }}</td>
                <td class="px-3 py-2">{{ a.uses }}</td>
                <td class="px-3 py-2">{{ pct(a.avg_edit_ratio) }}</td>
                <td class="px-3 py-2">{{ num(a.avg_score) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>
