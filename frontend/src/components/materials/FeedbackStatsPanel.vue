<script setup lang="ts">
/** 使用反馈面板（§6.4）—— 素材表现 + 角度组合表现两张简表。空态=3 步引导先导出。 */
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

const STEPS = ["录入素材", "生成文章", "导出后回流统计"];
</script>

<template>
  <div class="anim-up flex min-h-0 flex-1 flex-col">
    <div v-if="loading" class="flex items-center gap-2 p-3 text-sm" style="color: var(--ink-3)">
      <Spinner :size="14" /> 加载中…
    </div>
    <div v-else-if="error" class="p-3 text-sm" style="color: var(--red)">加载失败：{{ error }}</div>

    <!-- 空态：3 步引导 -->
    <section v-else-if="!notes.length && !angles.length" class="mat-panel flex flex-1 flex-col items-center justify-center gap-4 p-10">
      <div class="flex h-16 w-16 items-center justify-center rounded-full" style="background: rgba(238, 106, 42, 0.1); color: var(--primary)">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="20" x2="12" y2="10" /><line x1="18" y1="20" x2="18" y2="4" /><line x1="6" y1="20" x2="6" y2="16" />
        </svg>
      </div>
      <div class="font-display text-[15px] font-extrabold">还没有使用数据</div>
      <div class="max-w-[400px] text-center text-[13px] leading-[1.9]" style="color: var(--ink-3)">
        导出文章后，这里会按素材累计使用次数与反馈，帮你判断哪些话术真正有效、哪些该淘汰。
      </div>
      <div class="mt-1.5 flex flex-wrap items-center justify-center gap-2">
        <template v-for="(s, i) in STEPS" :key="s">
          <span class="flex items-center gap-[7px] rounded-full px-3.5 py-1.5 text-[12px] font-semibold" style="background: var(--card-2); color: var(--ink-2)">
            <span class="flex h-[17px] w-[17px] items-center justify-center rounded-full text-[10.5px] font-bold" style="background: var(--primary); color: #fff">{{ i + 1 }}</span>
            {{ s }}
          </span>
          <svg v-if="i < STEPS.length - 1" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--ink-4)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
          </svg>
        </template>
      </div>
    </section>

    <!-- 有数据：两张表 -->
    <div v-else class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
      <section class="mat-panel" style="padding: 14px 16px">
        <h2 class="mb-2.5 text-[13px] font-bold">素材表现<span class="ml-1.5 font-normal" style="color: var(--ink-4)">保留度高 = 改得少 = 好用</span></h2>
        <div class="overflow-x-auto">
          <table class="w-full text-[12px]">
            <thead style="color: var(--ink-4)">
              <tr class="text-left">
                <th class="px-3 py-2 font-medium">素材</th>
                <th class="px-3 py-2 font-medium">用量</th>
                <th class="px-3 py-2 font-medium">保留度</th>
                <th class="px-3 py-2 font-medium">平均编辑</th>
                <th class="px-3 py-2 font-medium">平均分</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="n in notes" :key="n.note_id" style="border-top: 1px solid rgba(var(--ink-rgb), 0.06)">
                <td class="font-mono max-w-[260px] truncate px-3 py-2">{{ n.note_id }}</td>
                <td class="px-3 py-2 tabular-nums">{{ n.uses }}</td>
                <td class="px-3 py-2 tabular-nums">{{ pct(n.keep_score) }}</td>
                <td class="px-3 py-2 tabular-nums">{{ pct(n.avg_edit_ratio) }}</td>
                <td class="px-3 py-2 tabular-nums">{{ num(n.avg_score) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="angles.length" class="mat-panel" style="padding: 14px 16px">
        <h2 class="mb-2.5 text-[13px] font-bold">角度组合表现</h2>
        <div class="overflow-x-auto">
          <table class="w-full text-[12px]">
            <thead style="color: var(--ink-4)">
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
              <tr v-for="(a, i) in angles" :key="i" style="border-top: 1px solid rgba(var(--ink-rgb), 0.06)">
                <td class="px-3 py-2">{{ a.audience ?? "—" }}</td>
                <td class="max-w-[220px] truncate px-3 py-2">{{ a.sellpoints.length ? a.sellpoints.join("、") : "—" }}</td>
                <td class="px-3 py-2">{{ a.tone ?? "—" }}</td>
                <td class="px-3 py-2 tabular-nums">{{ a.uses }}</td>
                <td class="px-3 py-2 tabular-nums">{{ pct(a.avg_edit_ratio) }}</td>
                <td class="px-3 py-2 tabular-nums">{{ num(a.avg_score) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>
