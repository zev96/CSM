<script setup lang="ts">
/**
 * 信源权重排行榜 `SourceList` —— 单列（对齐图二/三）。
 * 每行：序号 + 圆点(信源专属色) + 域名 + 类型 + 引用次数 + 引用率细条 + 权重。
 * 引用率 = 该信源覆盖平台数 ÷ 总平台数。
 * 上榜门槛（引用 ≥ 10 次 + 有真实网址）已在数据层 filterBoard 处理，这里只渲染。
 */
import { computed } from "vue";

import { SRC_COLORS, type BoardRow } from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  board: BoardRow[];
  total: number;
}>();

const denom = computed(() => Math.max(1, props.total));
function rate(b: BoardRow): number {
  return Math.round((b.platforms / denom.value) * 100);
}
</script>

<template>
  <div class="flex min-h-0 flex-col">
    <!-- 排序说明 -->
    <div class="flex flex-shrink-0 items-center" :style="{ marginBottom: '6px' }">
      <span :style="{ fontSize: '10.5px', color: 'var(--ink-3)' }">按权重排序</span>
    </div>

    <div v-if="!board.length" class="py-8 text-center" :style="{ fontSize: '12px', color: 'var(--ink-3)' }">暂无符合上榜门槛的信源</div>
    <!-- 单列列表，内部滚动 -->
    <div v-else class="min-h-0 flex-1 overflow-y-auto" :style="{ paddingRight: '2px' }">
      <div
        v-for="(b, i) in board"
        :key="b.domain + i"
        class="grid items-center"
        :style="{
          gridTemplateColumns: '20px minmax(0, 1fr) 56px minmax(92px, 1.5fr) 72px',
          gap: '10px',
          padding: '8px 0',
          borderBottom: i < board.length - 1 ? '1px solid rgba(28,26,23,0.05)' : 'none',
        }"
      >
        <!-- 序号 -->
        <span class="font-display" :style="{ fontSize: '12px', fontWeight: 700, color: 'var(--ink-4)', textAlign: 'center', fontVariantNumeric: 'tabular-nums' }">{{ i + 1 }}</span>
        <!-- 域名（类型徽章按用户要求移除，仅留圆点 + 域名）-->
        <div class="flex items-center" :style="{ gap: '6px', minWidth: 0 }">
          <span :style="{ width: '8px', height: '8px', borderRadius: '999px', background: SRC_COLORS[i % SRC_COLORS.length], flexShrink: 0 }" />
          <span class="truncate" :style="{ fontSize: '12.5px', fontWeight: 600 }" :title="b.domain">{{ b.domain || "—" }}</span>
        </div>
        <!-- 引用次数 -->
        <div :style="{ textAlign: 'right', whiteSpace: 'nowrap' }">
          <span class="font-display" :style="{ fontSize: '13px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ b.count }}</span>
          <span :style="{ fontSize: '9.5px', color: 'var(--ink-3)' }"> 次</span>
        </div>
        <!-- 引用率 + 细条 -->
        <div :style="{ minWidth: 0 }">
          <div :style="{ fontSize: '9.5px', color: 'var(--ink-3)', marginBottom: '3px' }">引用率 {{ rate(b) }}%</div>
          <div :style="{ height: '5px', borderRadius: '999px', background: 'rgba(28,26,23,.06)', overflow: 'hidden' }">
            <div :style="{ width: rate(b) + '%', height: '100%', background: SRC_COLORS[i % SRC_COLORS.length], borderRadius: '999px' }" />
          </div>
        </div>
        <!-- 权重 -->
        <div :style="{ textAlign: 'right', whiteSpace: 'nowrap' }">
          <span :style="{ fontSize: '9.5px', color: 'var(--ink-3)' }">权重 </span>
          <span class="font-display" :style="{ fontSize: '12px', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }">{{ b.weight }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
