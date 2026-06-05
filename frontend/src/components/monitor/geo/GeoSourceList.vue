<script setup lang="ts">
/**
 * 信源权重排行榜 `SourceList` —— 移植 design full-app.jsx。
 * 每行：序号 + 圆点(信源专属色) + 域名 + 类型 + 引用次数细条 + 右侧「N 次引用」
 * 「平台引用率 X%」+ 「去引流中心铺」闭环按钮。
 * 平台引用率 = 该信源覆盖平台数 ÷ 总平台数。配色/字号照稿。
 *
 * 入参：board[]（{domain,type,count,platforms数}）、total（总平台数，作引用率分母）、
 * taskId（用于构造 Excel 导出 URL）、keyword（当前关键词，透传给闭环跳转）。
 */
import { computed } from "vue";
import { useRouter } from "vue-router";

import { SRC_COLORS, type BoardRow } from "@/components/monitor/geo/geoDetail";
import { useSidecar } from "@/stores/sidecar";
import { saveUrlToFile } from "@/utils/saveFile";

const props = defineProps<{
  board: BoardRow[];
  total: number;
  taskId: number;
  keyword: string;
}>();

const router = useRouter();

async function exportXlsx() {
  const url = useSidecar().sseURL(`/api/monitor/geo/${props.taskId}/export?days=30`);
  const dateStr = new Date().toISOString().slice(0, 10);
  await saveUrlToFile(url, `信源榜-${dateStr}.xlsx`, { name: "Excel", extensions: ["xlsx"] });
}

function goMining(domain: string) {
  router.push({ name: "mining", query: { geo_keyword: props.keyword, geo_source: domain } });
}

const maxWeight = computed(() => Math.max(1, ...props.board.map((b) => b.weight)));
const denom = computed(() => Math.max(1, props.total));
</script>

<template>
  <div class="flex flex-col" :style="{ gap: '6px' }">
    <!-- 工具栏：导出按钮右对齐 -->
    <div class="flex items-center justify-end" :style="{ marginBottom: '4px' }">
      <button
        :style="{ fontSize: '11px', padding: '2px 8px', borderRadius: '4px', border: '1px solid var(--line)', background: 'var(--card)', color: 'var(--ink-2)', cursor: 'pointer', lineHeight: '20px' }"
        @click="exportXlsx"
      >导出信源榜</button>
    </div>
    <!-- 两列 + 固定高度，信源多时内部滚动（不撑高把上方散点图挤变形） -->
    <div :style="{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: '18px', maxHeight: '280px', overflowY: 'auto', alignContent: 'start' }">
    <div
      v-for="(b, i) in board"
      :key="b.domain"
      :style="{ display: 'grid', gridTemplateColumns: '18px 1fr 92px', alignItems: 'center', gap: '9px', padding: '5px 0' }"
    >
      <span
        class="font-display"
        :style="{ fontSize: '12px', fontWeight: 700, color: 'var(--ink-4)', textAlign: 'center', fontVariantNumeric: 'tabular-nums' }"
      >{{ i + 1 }}</span>
      <div :style="{ minWidth: 0 }">
        <div class="flex items-center" :style="{ gap: '6px' }">
          <span :style="{ width: '8px', height: '8px', borderRadius: '999px', background: SRC_COLORS[i % SRC_COLORS.length], flexShrink: 0 }" />
          <span class="truncate" :style="{ fontSize: '12px', fontWeight: 600 }" :title="b.domain">{{ b.domain || "—" }}</span>
          <span :style="{ fontSize: '9.5px', color: 'var(--ink-4)', flexShrink: 0 }">{{ b.type }}</span>
        </div>
        <div :style="{ marginTop: '5px' }">
          <div :style="{ height: '5px', borderRadius: '999px', background: 'rgba(28,26,23,.06)', overflow: 'hidden' }">
            <div :style="{ width: `${Math.max(0, Math.min(1, b.weight / maxWeight)) * 100}%`, height: '100%', background: SRC_COLORS[i % SRC_COLORS.length], borderRadius: '999px' }" />
          </div>
        </div>
      </div>
      <div :style="{ textAlign: 'right' }">
        <span class="font-display" :style="{ fontSize: '13px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ b.count }}</span>
        <span :style="{ fontSize: '10px', color: 'var(--ink-3)' }"> 次引用</span>
        <div :style="{ fontSize: '9.5px', color: 'var(--ink-3)', fontVariantNumeric: 'tabular-nums' }">平台引用率 {{ Math.round((b.platforms / denom) * 100) }}%</div>
        <div :style="{ fontSize: '9.5px', color: 'var(--ink-3)' }">权重 {{ b.weight }}</div>
        <button
          type="button"
          :style="{ fontSize: '9px', color: 'var(--ink-4)', background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 0', lineHeight: 1.4 }"
          :title="`去引流中心铺「${b.domain}」`"
          @click="goMining(b.domain)"
        >去引流中心铺 →</button>
      </div>
    </div>
    </div>
  </div>
</template>
