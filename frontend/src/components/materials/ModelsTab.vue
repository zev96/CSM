<script setup lang="ts">
/**
 * 品牌型号页（素材库 V3）：左型号列表（产品线筛选·主推/竞品·品牌分组·搜索）
 * + 右详情（摘要卡 + 按笔记真实 H2 小节分组的参数卡）。数据接 useMaterials，
 * 分组/摘要逻辑见 modelSpecs.ts（V3 起数据驱动，设计稿 6 组本体已废）。
 */
import { computed, nextTick, ref } from "vue";
import { useMaterials } from "@/stores/materials";
import { useFactsChanges } from "@/stores/factsChanges";
import Spinner from "@/components/ui/Spinner.vue";
import Select from "@/components/ui/Select.vue";
import {
  buildSpecGroups,
  buildStats,
  productHref,
  stripBrand,
} from "@/components/materials/modelSpecs";

const m = useMaterials();
const facts = useFactsChanges();

const query = ref("");
const activeGroup = ref(0);
const scrollRef = ref<HTMLElement | null>(null);

// ── 产品线筛选(store 持有,汇总栏联动) ─────────────────────────────
const lineOptions = computed(() => {
  const counts = new Map<string, number>();
  for (const r of m.models) {
    const line = r.product_line || "未分类";
    counts.set(line, (counts.get(line) ?? 0) + 1);
  }
  const opts = [{ value: "全部", label: `全部产品线（${m.models.length}）` }];
  for (const [line, n] of counts) opts.push({ value: line, label: `${line}（${n}）` });
  return opts;
});
const lineModels = computed(() =>
  m.lineFilter === "全部"
    ? m.models
    : m.models.filter((r) => (r.product_line || "未分类") === m.lineFilter),
);

// ── 左侧：搜索 + 主推/竞品 + 品牌分组 ──────────────────────────────
const q = computed(() => query.value.trim().toLowerCase());
function match(brand: string, model: string): boolean {
  return !q.value || (brand + model).toLowerCase().includes(q.value);
}

interface SideModel {
  model: string;
  brand: string;
  disp: string;
  showBrand: boolean;
  missing: boolean;
}
interface SideGroup {
  brand: string;
  showBrand: boolean;
  models: SideModel[];
}
interface SideSection {
  title: string;
  count: number;
  titleColor: string;
  groups: SideGroup[];
}

function mkModel(r: { model: string; brand: string; coverage: any }, showBrand: boolean): SideModel {
  return {
    model: r.model,
    brand: r.brand,
    disp: stripBrand(r.model, r.brand),
    showBrand,
    missing: !r.coverage?.script_dimensions, // 缺话术 = 无技术话术维度
  };
}

const sideSections = computed<SideSection[]>(() => {
  const primary = lineModels.value.filter((r) => r.role === "主推" && match(r.brand, r.model));
  const comps = lineModels.value.filter((r) => r.role !== "主推" && match(r.brand, r.model));
  const out: SideSection[] = [];
  if (primary.length) {
    out.push({
      title: "主推",
      count: primary.length,
      titleColor: "var(--primary-deep)",
      groups: [{ brand: "", showBrand: false, models: primary.map((r) => mkModel(r, true)) }],
    });
  }
  if (comps.length) {
    const order: string[] = [];
    const byBrand: Record<string, typeof comps> = {};
    comps.forEach((r) => {
      if (!byBrand[r.brand]) {
        byBrand[r.brand] = [];
        order.push(r.brand);
      }
      byBrand[r.brand].push(r);
    });
    out.push({
      title: "竞品",
      count: comps.length,
      titleColor: "var(--ink-3)",
      groups: order.map((b) => ({
        brand: b + (byBrand[b].length > 1 ? `（${byBrand[b].length}）` : ""),
        showBrand: true,
        models: byBrand[b].map((r) => mkModel(r, false)),
      })),
    });
  }
  return out;
});

const noResults = computed(() => sideSections.value.length === 0);

function selectModel(model: string): void {
  m.select(model);
  activeGroup.value = 0;
  nextTick(() => {
    if (scrollRef.value) scrollRef.value.scrollTop = 0;
  });
}

// ── 右侧：详情派生 ──────────────────────────────────────────────
const detail = computed(() => m.detail);
const specData = computed(() => (detail.value ? buildSpecGroups(detail.value.specs) : null));
const paramGroups = computed(() => specData.value?.groups ?? []);
const filled = computed(() => specData.value?.filled ?? 0);
const total = computed(() => specData.value?.total ?? 0);
const pctW = computed(() => (total.value ? Math.round((filled.value / total.value) * 100) : 0) + "%");
const stats = computed(() => (detail.value ? buildStats(detail.value.specs, detail.value.category) : []));
const href = computed(() => (detail.value ? productHref(detail.value.specs) : null));
const hasSpecs = computed(() => !!detail.value && Object.keys(detail.value.specs).length > 0);

const selTitle = computed(() => {
  const d = detail.value;
  if (!d) return "";
  return `${d.brand} · ${stripBrand(d.model_full, d.brand)}`;
});
const isPrimary = computed(() => detail.value?.role === "主推");
const selMissing = computed(() => !detail.value?.coverage?.script_dimensions);

// ── 分组锚点 scroll-spy ────────────────────────────────────────
function goGroup(idx: number): void {
  activeGroup.value = idx;
  nextTick(() => {
    requestAnimationFrame(() => {
      const c = scrollRef.value;
      if (!c) return;
      const el = c.querySelector<HTMLElement>(`#pg-${idx}`);
      if (!el) return;
      const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop - 2;
      c.scrollTop = Math.max(0, top);
    });
  });
}
function onDetailScroll(): void {
  const c = scrollRef.value;
  if (!c) return;
  const cTop = c.getBoundingClientRect().top;
  let active = paramGroups.value.length ? paramGroups.value[0].idx : 0;
  for (const g of paramGroups.value) {
    const el = c.querySelector<HTMLElement>(`#pg-${g.idx}`);
    if (el && el.getBoundingClientRect().top - cTop <= 60) active = g.idx;
  }
  if (active !== activeGroup.value) activeGroup.value = active;
}
</script>

<template>
  <div class="anim-up flex min-h-0 flex-1 gap-d">
    <!-- ── 左：型号列表 ── -->
    <aside class="mat-panel flex flex-none flex-col overflow-hidden" style="width: 264px">
      <div class="flex-none px-3.5 pb-2.5 pt-3.5">
        <Select
          v-if="lineOptions.length > 2"
          v-model="m.lineFilter"
          :options="lineOptions"
          size="sm"
          min-width="100%"
          class="mb-2 w-full"
        />
        <div class="relative">
          <svg class="pointer-events-none absolute left-[11px] top-1/2 -translate-y-1/2" width="14" height="14"
            viewBox="0 0 24 24" fill="none" stroke="var(--ink-4)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
          </svg>
          <input v-model="query" placeholder="搜品牌 / 型号…" class="mat-input w-full" style="padding-left: 32px" />
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        <div v-if="m.loading" class="flex items-center gap-2 p-3 text-sm" style="color: var(--ink-3)">
          <Spinner :size="14" /> 加载中…
        </div>
        <div v-else-if="m.error" class="p-3 text-sm" style="color: var(--red)">加载失败：{{ m.error }}</div>
        <div v-else-if="!m.models.length" class="p-3 text-[12px]" style="color: var(--ink-3)">
          素材库无产品参数笔记。请在「设置」确认素材库路径。
        </div>
        <template v-else>
          <div v-for="sec in sideSections" :key="sec.title">
            <div class="flex items-baseline gap-1.5 px-2.5 pb-1.5 pt-3">
              <span class="text-[11px] font-bold tracking-wide" :style="{ color: sec.titleColor }">{{ sec.title }}</span>
              <span class="text-[11px]" style="color: var(--ink-4)">{{ sec.count }}</span>
            </div>
            <div v-for="(g, gi) in sec.groups" :key="gi">
              <div v-if="g.showBrand" class="px-2.5 pb-0.5 pt-1.5 text-[10.5px]" style="color: var(--ink-4)">{{ g.brand }}</div>
              <button
                v-for="mo in g.models" :key="mo.model" :data-model="mo.model"
                class="mat-row" :class="{ 'mat-row--sel': m.selectedModel === mo.model }"
                @click="selectModel(mo.model)"
              >
                <span v-if="m.selectedModel === mo.model" class="mat-row__bar" />
                <span v-if="mo.showBrand" class="flex-none text-[12px]" style="color: var(--ink-3)">{{ mo.brand }}</span>
                <span class="min-w-0 flex-1 truncate text-[13px] font-semibold" style="color: var(--ink)">{{ mo.disp }}</span>
                <span v-if="facts.isStale(mo.model)" class="mat-tag-warn flex-none">参数已更新</span>
                <span v-if="mo.missing" class="mat-tag-miss flex-none">缺话术</span>
              </button>
            </div>
          </div>
          <div v-if="noResults" class="px-2.5 py-6 text-center text-[12px]" style="color: var(--ink-4)">
            没有匹配「<span style="color: var(--ink-2)">{{ query }}</span>」的型号
          </div>
        </template>
      </div>
    </aside>

    <!-- ── 右：参数详情 ── -->
    <div class="flex min-w-0 flex-1 flex-col gap-3">
      <div v-if="m.detailLoading" class="grid flex-1 place-items-center text-sm" style="color: var(--ink-3)">
        <span class="flex items-center gap-2"><Spinner :size="14" /> 加载详情…</span>
      </div>
      <div v-else-if="!detail" class="grid flex-1 place-items-center text-sm" style="color: var(--ink-4)">
        选择左侧型号查看记忆详情
      </div>
      <template v-else>
        <!-- 摘要卡 -->
        <section class="card-frosted flex flex-none flex-col gap-3.5" style="padding: calc(var(--density-pad) - 4px) var(--density-pad)">
          <div class="flex items-center gap-2.5">
            <h2 class="font-display m-0 text-[19px] font-extrabold">{{ selTitle }}</h2>
            <span class="rounded-full px-2.5 py-[3px] text-[11px] font-semibold"
              :style="{ background: isPrimary ? 'var(--primary-soft)' : 'var(--card-2)', color: isPrimary ? 'var(--primary-deep)' : 'var(--ink-3)' }">
              {{ detail.role }}
            </span>
            <span v-if="selMissing" class="mat-tag-miss">缺话术</span>
            <div class="ml-auto flex items-center gap-3.5">
              <div v-if="hasSpecs" class="flex items-center gap-2">
                <span class="text-[11.5px]" style="color: var(--ink-3)">参数 {{ filled }} / {{ total }}</span>
                <span class="inline-block h-[5px] w-[88px] overflow-hidden rounded-full" style="background: rgba(var(--ink-rgb), 0.08)">
                  <span class="block h-full rounded-full" :style="{ width: pctW, background: 'var(--primary)' }" />
                </span>
              </div>
              <span v-if="!hasSpecs" class="text-[11.5px]" style="color: var(--ink-4)">暂无参数笔记</span>
              <a v-if="href" :href="href" target="_blank" rel="noopener" class="mat-linkbtn">
                商品页
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
                </svg>
              </a>
            </div>
          </div>
          <div v-if="stats.length" class="flex min-w-0 items-stretch overflow-x-auto">
            <div v-for="(s, si) in stats" :key="si" class="flex flex-none flex-col gap-[3px] px-[26px]"
              :style="{ borderLeft: si === 0 ? 'none' : '1px solid rgba(var(--ink-rgb), 0.08)' }">
              <span class="text-[17px] font-bold" :style="{ color: s.dim ? 'var(--ink-4)' : 'var(--ink)' }">{{ s.value }}</span>
              <span class="text-[11px]" style="color: var(--ink-4)">{{ s.label }}</span>
            </div>
          </div>
        </section>

        <!-- 分组锚点导航 -->
        <div v-if="hasSpecs" class="flex flex-none items-center gap-[7px]">
          <button v-for="g in paramGroups" :key="g.idx" class="mat-chip" :class="{ 'mat-chip--on': activeGroup === g.idx }"
            @click="goGroup(g.idx)">{{ g.title }}</button>
          <span class="ml-auto text-[11.5px]" style="color: var(--ink-4)">「—」为未收集 · 可在录入页补齐</span>
        </div>

        <!-- 参数分组卡 -->
        <div v-if="hasSpecs" ref="scrollRef" class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-0.5" @scroll="onDetailScroll">
          <section v-for="g in paramGroups" :id="`pg-${g.idx}`" :key="g.idx" class="flex-none"
            style="background: var(--card); border: 1px solid rgba(var(--ink-rgb), 0.08); border-radius: 18px; padding: 16px var(--density-pad) 8px">
            <div class="mb-1.5 flex items-baseline justify-between">
              <h3 class="m-0 text-[13.5px] font-bold">{{ g.title }}</h3>
              <span class="text-[11.5px]" style="color: var(--ink-4)">{{ g.filled }} 已填</span>
            </div>
            <div>
              <div v-for="(r, ri) in g.rows" :key="ri" class="grid items-baseline gap-4 py-2"
                style="grid-template-columns: 180px 1fr; border-bottom: 1px solid rgba(var(--ink-rgb), 0.05)">
                <span class="text-[12.5px]" style="color: var(--ink-3)">{{ r.label }}</span>
                <span class="text-[13px] leading-relaxed" :style="{ fontWeight: r.dim ? 400 : 500, color: r.dim ? 'var(--ink-4)' : 'var(--ink)' }">{{ r.value }}</span>
              </div>
            </div>
          </section>
          <div class="h-1 flex-none" />
        </div>
        <div v-if="!hasSpecs" class="grid flex-1 place-items-center text-sm" style="color: var(--ink-4)">
          该型号暂无产品参数笔记 · 可在「录入」页选择对应产品线的「产品参数」文件夹补录
        </div>
      </template>
    </div>
  </div>
</template>
