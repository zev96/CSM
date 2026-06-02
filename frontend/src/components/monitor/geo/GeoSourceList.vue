<script setup lang="ts">
/**
 * 信源权重排行榜 `SourceList` —— 移植 design full-app.jsx。
 * 每行：序号 + 圆点(信源专属色) + 域名 + 类型 + 引用次数细条 + 右侧「N 次引用」
 * 「平台引用率 X%」。平台引用率 = 该信源覆盖平台数 ÷ 总平台数。配色/字号照稿。
 *
 * 入参：board[]（{domain,type,count,platforms数}）、total（总平台数，作引用率分母）。
 */
import { computed } from "vue";

import { SRC_COLORS, type BoardRow } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  board: BoardRow[];
  total: number;
}>();

const maxCount = computed(() => Math.max(1, ...props.board.map((b) => b.count)));
const denom = computed(() => Math.max(1, props.total));
</script>

<template>
  <div class="flex flex-col" :style="{ gap: '6px' }">
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
            <div :style="{ width: `${Math.max(0, Math.min(1, b.count / maxCount)) * 100}%`, height: '100%', background: SRC_COLORS[i % SRC_COLORS.length], borderRadius: '999px' }" />
          </div>
        </div>
      </div>
      <div :style="{ textAlign: 'right' }">
        <span class="font-display" :style="{ fontSize: '13px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ b.count }}</span>
        <span :style="{ fontSize: '10px', color: 'var(--ink-3)' }"> 次引用</span>
        <div :style="{ fontSize: '9.5px', color: 'var(--ink-3)', fontVariantNumeric: 'tabular-nums' }">平台引用率 {{ Math.round((b.platforms / denom) * 100) }}%</div>
      </div>
    </div>
  </div>
</template>
