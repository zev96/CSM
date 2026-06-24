<script setup lang="ts">
import { computed, onMounted } from "vue";
import SplitPane from "@/components/ui/SplitPane.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Pill from "@/components/ui/Pill.vue";
import { useMaterials, type BrandModelRow } from "@/stores/materials";

const m = useMaterials();
onMounted(() => m.list());

const hero = computed(() => m.models.filter((r) => r.role === "主推"));
const rivals = computed(() => m.models.filter((r) => r.role !== "主推"));

function gaps(r: BrandModelRow): string[] {
  const c = r.coverage || {};
  const out: string[] = [];
  if (!c.has_specs) out.push("缺参数");
  if (!c.has_tests) out.push("缺测试");
  if (!c.script_dimensions) out.push("缺话术");
  return out;
}
</script>

<template>
  <div class="h-full min-h-0 p-5">
    <div class="mb-4 flex items-baseline gap-3">
      <h1 class="text-lg font-semibold">素材库</h1>
      <div class="flex gap-2 text-sm">
        <span class="rounded-full bg-ink/10 px-3 py-1 font-medium">品牌型号</span>
        <span class="px-3 py-1 text-ink/35">浏览（建设中）</span>
        <span class="px-3 py-1 text-ink/35">录入（建设中）</span>
      </div>
    </div>

    <SplitPane leftWidth="300px" gap="18px">
      <template #left>
        <div class="flex h-full min-h-0 min-w-0 flex-col overflow-y-auto">
          <div v-if="m.loading" class="flex items-center gap-2 p-3 text-sm text-ink/50">
            <Spinner :size="14" /> 加载中…
          </div>
          <div v-else-if="m.error" class="p-3 text-sm" :style="{ color: 'var(--red)' }">加载失败：{{ m.error }}</div>
          <div v-else-if="!m.models.length" class="p-3 text-sm text-ink/50">
            素材库无产品参数笔记。请在「设置」确认素材库路径。
          </div>
          <template v-else>
            <template v-for="(group, gi) in [
              { label: '主推', rows: hero },
              { label: '竞品', rows: rivals },
            ]" :key="gi">
              <div v-if="group.rows.length" class="px-2 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-ink/40">
                {{ group.label }}（{{ group.rows.length }}）
              </div>
              <button
                v-for="r in group.rows"
                :key="r.model"
                :data-model="r.model"
                class="flex flex-col gap-1 rounded-lg px-2 py-2 text-left transition-colors"
                :style="{ background: m.selectedModel === r.model ? 'var(--card-2, rgba(0,0,0,0.05))' : 'transparent' }"
                @click="m.select(r.model)"
              >
                <div class="flex items-center gap-2 text-sm font-medium">
                  <span>{{ r.brand }} · {{ r.model }}</span>
                </div>
                <div class="flex flex-wrap gap-1">
                  <Pill v-for="g in gaps(r)" :key="g" class="text-[10px]">{{ g }}</Pill>
                </div>
              </button>
            </template>
          </template>
        </div>
      </template>

      <template #right>
        <div class="h-full min-h-0 min-w-0 overflow-y-auto">
          <div v-if="m.detailLoading" class="flex items-center gap-2 p-4 text-sm text-ink/50">
            <Spinner :size="14" /> 加载详情…
          </div>
          <div v-else-if="!m.detail" class="grid h-full place-items-center text-sm text-ink/40">
            选择左侧型号查看记忆详情
          </div>
          <div v-else class="flex flex-col gap-5 p-1">
            <header class="flex items-center gap-3">
              <h2 class="text-base font-semibold">{{ m.detail.brand }} · {{ m.detail.model_full }}</h2>
              <span class="rounded-full bg-ink/10 px-2 py-0.5 text-xs">{{ m.detail.role }}</span>
            </header>

            <section v-if="Object.keys(m.detail.specs).length">
              <h3 class="mb-2 text-sm font-semibold">参数</h3>
              <table class="w-full text-sm">
                <tbody>
                  <tr v-for="(sv, field) in m.detail.specs" :key="field" class="border-b border-ink/5">
                    <td class="py-1 pr-3 text-ink/60">{{ field }}</td>
                    <td class="py-1" :class="sv.is_placeholder ? 'text-ink/30' : ''">{{ sv.raw }}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section v-if="m.detail.certs.length">
              <h3 class="mb-2 text-sm font-semibold">认证</h3>
              <div class="flex flex-wrap gap-1">
                <Pill v-for="c in m.detail.certs" :key="c">{{ c }}</Pill>
              </div>
            </section>

            <section v-if="Object.keys(m.detail.scripts).length">
              <h3 class="mb-2 text-sm font-semibold">技术话术（按维度）</h3>
              <ul class="space-y-1 text-sm">
                <li v-for="(vs, dim) in m.detail.scripts" :key="dim" class="text-ink/70">
                  {{ dim }}：{{ vs.length }} 条
                </li>
              </ul>
            </section>

            <section v-if="m.detail.endorsements.length">
              <h3 class="mb-2 text-sm font-semibold">品牌背书（{{ m.detail.endorsements.length }}）</h3>
              <ul class="list-disc space-y-1 pl-5 text-sm text-ink/70">
                <li v-for="(e, i) in m.detail.endorsements.slice(0, 5)" :key="i">{{ e }}</li>
              </ul>
            </section>

            <section v-if="m.detail.intro.length">
              <h3 class="mb-2 text-sm font-semibold">介绍</h3>
              <ul class="list-disc space-y-1 pl-5 text-sm text-ink/70">
                <li v-for="(t, i) in m.detail.intro.slice(0, 5)" :key="i">{{ t }}</li>
              </ul>
            </section>

            <section v-if="Object.keys(m.detail.tests).length">
              <h3 class="mb-2 text-sm font-semibold">测试结果（{{ Object.keys(m.detail.tests).length }}）</h3>
              <ul class="space-y-1 text-sm text-ink/70">
                <li v-for="(_v, k) in m.detail.tests" :key="k">{{ k }}</li>
              </ul>
            </section>

            <section>
              <h3 class="mb-2 text-sm font-semibold">缺口体检</h3>
              <div class="flex flex-wrap gap-1 text-xs">
                <Pill>{{ m.detail.coverage.has_specs ? "有参数" : "缺参数" }}</Pill>
                <Pill>{{ m.detail.coverage.has_tests ? "有测试" : "缺测试" }}</Pill>
                <Pill>话术 {{ m.detail.coverage.script_dimensions || 0 }} 维</Pill>
              </div>
            </section>

            <section>
              <h3 class="mb-2 text-sm font-semibold">注入预览（生成时会喂给 LLM 的事实，受 token 上限）</h3>
              <pre class="whitespace-pre-wrap rounded-lg bg-ink/5 p-3 text-xs leading-relaxed text-ink/80">{{ m.detail.inject_preview || "（无可注入事实）" }}</pre>
            </section>
          </div>
        </div>
      </template>
    </SplitPane>
  </div>
</template>
