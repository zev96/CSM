<script setup lang="ts">
/**
 * 本月排期 — 严格按 CSM-RE1（V1）/src/screens/home.jsx 的 Calendar 复刻：
 *   - 深色卡片（var(--dark) 底）
 *   - 右上橙色 blob 装饰
 *   - 标题区："本月排期" + "已完成 N · 排期 N" + 月份下拉 chip
 *   - 周历表头 M T W T F S S（周一为首）
 *   - 日期格 26×26 圆形，三态：
 *       * 今天     → var(--primary) 实心，白字
 *       * 已完成   → var(--yellow) 实心，深字
 *       * 排期     → 透明 + 虚线圈
 *       * 普通     → 透明，浅字
 *   - 底部 legend
 *
 * 为什么 shell 用本地 Date 而不是等 sidecar：sidecar bootstrap 期间
 * /api/calendar 拿不到，整张日历就会一直空白（之前的版本就是这毛病）。
 * 现在年月/天数/前导偏移这些静态的东西都来自 ``new Date()``，UI 一开门
 * 就有完整日历可看；等 ``whenReady`` 通过、``getCalendar`` 回来再把
 * 真实的 done/scheduled 计数覆盖上去。失败也无所谓，fallback 示例顶住。
 */
import { computed, onMounted, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";
import { getCalendar } from "@/api/client";
import { useSidecarReady } from "@/composables/useSidecarReady";

// V1 设计稿示例数据，发布前清空保留空状态 —— 新装机日历干净无圆点，
// 等真实数据从 /api/calendar 回来填充。
const FALLBACK_DONE: number[] = [];
const FALLBACK_SCHEDULED: number[] = [];

// ── 月历骨架（本地计算，不依赖网络）────────────────────────────────────
const now = new Date();
const viewYear = now.getFullYear();
const viewMonth = now.getMonth() + 1; // 1-12
const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
const firstDow = new Date(viewYear, viewMonth - 1, 1).getDay();
// JS Date.getDay()：0=周日。设计稿是周一为首，所以 (firstDow + 6) % 7。
const leadingOffset = (firstDow + 6) % 7;
const todayDay = now.getDate();
const monthLabel = `${viewMonth} 月`;

// ── API 真实数据（异步覆盖）──────────────────────────────────────────
const apiDone = ref<number[] | null>(null); // 长度 = daysInMonth，按天计数
const apiScheduled = ref<number[] | null>(null);
const error = ref<string | null>(null);
const { whenReady } = useSidecarReady();

// 已完成日号集合 — apiDone 里 count > 0 的位置；空数据时用 fallback。
const doneSet = computed(() => {
  if (apiDone.value === null) return new Set(FALLBACK_DONE);
  const real = apiDone.value
    .map((n, i) => (n > 0 ? i + 1 : null))
    .filter((d): d is number => d !== null);
  if (real.length > 0) return new Set(real);
  return new Set(FALLBACK_DONE);
});

// 排期日号集合 — sidecar 现在恒返回全 0，那就用 fallback 撑场。
const scheduledSet = computed(() => {
  if (apiScheduled.value === null) return new Set(FALLBACK_SCHEDULED);
  const real = apiScheduled.value
    .map((n, i) => (n > 0 ? i + 1 : null))
    .filter((d): d is number => d !== null);
  if (real.length > 0) return new Set(real);
  return new Set(FALLBACK_SCHEDULED);
});

// 网格单元 — 静态，由本地日期算出，sidecar 状态变化不影响骨架。
interface Cell {
  day: number | null;
}
const cells = computed<Cell[]>(() => {
  const out: Cell[] = [];
  for (let i = 0; i < leadingOffset; i++) out.push({ day: null });
  for (let d = 1; d <= daysInMonth; d++) out.push({ day: d });
  return out;
});

const doneCount = computed(() => doneSet.value.size);
const scheduledCount = computed(() => scheduledSet.value.size);

onMounted(async () => {
  try {
    await whenReady();
    const r = await getCalendar();
    apiDone.value = r.done;
    apiScheduled.value = r.scheduled;
  } catch (e: any) {
    // 静默失败 —— 月历骨架已经在画了，fallback 数据顶着，UI 不会塌。
    error.value = e?.message ?? String(e);
  }
});

// 表头改用中文单字 — 原来用「M T W T F S S」首字母，两个 T 跟两个 S
// 视觉重复，跟整页中文也违和；改成「一/二/三/四/五/六/日」既无歧义又
// 一致。仍按周一为首。
const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"] as const;

// 单元格视觉状态计算 — 抽出来避免 template 里堆三层三元。
function cellStyle(day: number | null) {
  if (day === null) return { background: "transparent" };
  const isToday = todayDay === day;
  const isDone = doneSet.value.has(day);
  const isSched = scheduledSet.value.has(day);
  if (isToday) {
    return {
      background: "var(--primary)",
      color: "#fff",
      fontWeight: 700,
    };
  }
  if (isDone) {
    return {
      background: "var(--yellow)",
      color: "#1e1c19",
      fontWeight: 700,
    };
  }
  if (isSched) {
    return {
      background: "rgba(255,255,255,0.08)",
      color: "#fbf7ec",
      border: "1px dashed rgba(255,255,255,0.25)",
    };
  }
  return {
    background: "transparent",
    color: "rgba(255,255,255,0.6)",
  };
}
</script>

<template>
  <!--
    自带样式，不走通用 Card —— Card 是浅色卡基底，深色版本就直接在这里
    画。relative+overflow-hidden 是为了 blob 被裁住不溢出圆角。
  -->
  <!--
    minHeight 320px 跟 KeywordHero 对齐。两张卡都自报 min-height 而
    不是依赖 grid 父容器的 stretch + 类穿透，跨组件层级最稳。
  -->
  <section
    class="relative flex h-full flex-col overflow-hidden"
    :style="{
      background: 'var(--dark)',
      borderRadius: 'var(--radius-card)',
      border: '1px solid rgba(255,255,255,0.06)',
      color: '#f1ebde',
      padding: '18px',
      minHeight: '340px',
    }"
  >
    <!-- 橙色 blob 装饰 — 偏右上，比 hero 那两个小一点 -->
    <div
      class="blur-blob"
      :style="{
        position: 'absolute',
        width: '180px',
        height: '180px',
        top: '-40px',
        left: '180px',
        borderRadius: '50%',
        background: 'var(--primary)',
        opacity: 0.32,
        zIndex: 0,
      }"
    />

    <div class="relative flex h-full flex-col" :style="{ zIndex: 2 }">
      <!-- 标题区 -->
      <div class="mb-3 flex flex-shrink-0 items-center justify-between">
        <div>
          <div
            class="font-display font-semibold text-[14px]"
            :style="{ color: '#fbf7ec' }"
          >
            本月排期
          </div>
          <div
            class="mt-0.5 text-[10.5px]"
            :style="{ color: 'rgba(255,255,255,0.5)' }"
          >
            已完成 {{ doneCount }} · 排期 {{ scheduledCount }}
          </div>
        </div>
        <button
          type="button"
          class="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px]"
          :style="{
            background: 'rgba(255,255,255,0.08)',
            color: '#fbf7ec',
          }"
        >
          {{ monthLabel }}
          <Icon name="arrowDown" :size="10" />
        </button>
      </div>

      <!-- 周历表头 -->
      <div class="mb-1.5 grid flex-shrink-0 grid-cols-7 gap-y-2">
        <div
          v-for="(d, i) in WEEKDAYS"
          :key="i"
          class="text-center text-[10px] tracking-[1px]"
          :style="{ color: 'rgba(255,255,255,0.4)' }"
        >
          {{ d }}
        </div>
      </div>

      <!-- 日期格 -->
      <div
        class="grid flex-1 grid-cols-7"
        :style="{ rowGap: '6px', alignContent: 'start' }"
      >
        <div
          v-for="(cell, i) in cells"
          :key="i"
          class="flex items-center justify-center"
        >
          <span
            v-if="cell.day !== null"
            class="inline-flex items-center justify-center"
            :style="{
              width: '26px',
              height: '26px',
              borderRadius: '50%',
              fontSize: '11.5px',
              fontWeight: 500,
              ...cellStyle(cell.day),
            }"
          >
            {{ cell.day }}
          </span>
        </div>
      </div>

      <!-- 底部 legend -->
      <div
        class="mt-auto flex flex-shrink-0 items-center gap-3 pt-2"
        :style="{ borderTop: '1px solid rgba(255,255,255,0.08)' }"
      >
        <span
          class="inline-flex items-center gap-1.5 text-[10.5px]"
          :style="{ color: 'rgba(255,255,255,0.55)' }"
        >
          <span
            :style="{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: 'var(--primary)',
            }"
          />
          今天
        </span>
        <span
          class="inline-flex items-center gap-1.5 text-[10.5px]"
          :style="{ color: 'rgba(255,255,255,0.55)' }"
        >
          <span
            :style="{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: 'var(--yellow)',
            }"
          />
          已发
        </span>
        <span
          class="inline-flex items-center gap-1.5 text-[10.5px]"
          :style="{ color: 'rgba(255,255,255,0.55)' }"
        >
          <span
            :style="{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: 'transparent',
              border: '1px dashed rgba(255,255,255,0.4)',
            }"
          />
          排期
        </span>
      </div>
    </div>
  </section>
</template>
