<script setup lang="ts">
/**
 * 排名异动 — 严格按 CSM-RE1（V1）/src/screens/home.jsx 的 RankingDelta 复刻：
 *   - 头部："MONITOR · 知乎" 小标 + "排名异动" 大标 + "近 1 小时 · N 个异动"
 *   - 右上 "全部 →" 跳转监测中心
 *   - 列表：图标方框 + 关键词 + 一行说明 + 时间，最多 4 条
 *
 * 数据：sidecar /api/monitor/summary 的 zhihu_question.tasks。如果监测
 * 模块还没初始化、或者真实任务为空，就退回到 V1 设计稿同款示例
 * （投影仪客厅家用 / 母婴加湿器推荐 / vault 索引），保证 UI 完整。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

const sidecar = useSidecar();
const cfg = useConfig();
const router = useRouter();
const { whenReady } = useSidecarReady();

type Level = "alert" | "warn" | "info";

interface AlertRow {
  id: string;
  kw: string;
  body: string;
  when: string;
  level: Level;
  /** 图标 key — alert/warn 用警告三角，info 用 vault。 */
  kind: "warn" | "vault";
}

// V1 设计稿示例数据，发布前清空保留空状态 —— 首次启动不再撑场假告警。
const FALLBACK_ALERTS: AlertRow[] = [];

interface ZhihuTask {
  id: number;
  name: string;
  enabled: boolean;
  latest: {
    status: string;
    rank: number;
    checked_at: string | null;
  } | null;
}
const tasks = ref<ZhihuTask[]>([]);
const loaded = ref(false);

const topN = computed(() => cfg.data?.monitor?.alert_top_n ?? 5);

function severity(t: ZhihuTask): Level | "ok" {
  if (!t.latest) return "info";
  if (t.latest.status === "failed" || t.latest.status === "risk_control")
    return "alert";
  if (t.latest.status !== "ok") return "info";
  if (t.latest.rank < 1 || t.latest.rank > topN.value) return "warn";
  return "ok";
}

// 把真实任务映射成 AlertRow，只取有异动的（非 ok）。
const realAlerts = computed<AlertRow[]>(() => {
  const order: Record<Level, number> = { alert: 0, warn: 1, info: 2 };
  const out: AlertRow[] = [];
  for (const t of tasks.value) {
    const lvl = severity(t);
    if (lvl === "ok") continue;
    out.push({
      id: String(t.id),
      kw: t.name,
      body:
        lvl === "alert"
          ? "排名异常 — 失败或风控"
          : lvl === "warn"
            ? `跌出前 ${topN.value} — 当前第 ${t.latest?.rank ?? "—"} 名`
            : "等待首次抓取",
      when: t.latest?.checked_at ? formatTime(t.latest.checked_at) : "—",
      level: lvl,
      kind: "warn",
    });
  }
  return out.sort((a, b) => order[a.level] - order[b.level]);
});

const rows = computed<AlertRow[]>(() => {
  // sidecar 没回 / 失败 → 始终 fallback；有任务但全部 ok → 也 fallback，
  // 避免列表完全空白。一旦真实有异动就用真实数据。
  if (!loaded.value) return FALLBACK_ALERTS;
  if (realAlerts.value.length === 0) return FALLBACK_ALERTS;
  return realAlerts.value.slice(0, 4);
});

const subLabel = computed(() => {
  const n = rows.value.length;
  return `近 1 小时 · ${n} 个异动`;
});

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const diffMin = (Date.now() - d.getTime()) / 60000;
    if (diffMin < 1) return "刚刚";
    if (diffMin < 60) return `${Math.round(diffMin)} 分钟前`;
    if (diffMin < 60 * 24) return `${Math.round(diffMin / 60)} 小时前`;
    return d.toLocaleDateString();
  } catch {
    return iso;
  }
}

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/summary");
    tasks.value = r.data.platforms?.zhihu_question?.tasks ?? [];
  } catch {
    /* 静默失败 — fallback 顶住 */
  } finally {
    loaded.value = true;
  }
});

// 行内图标方框配色 — 三档。
function badgeStyle(level: Level) {
  if (level === "alert")
    return {
      background: "rgba(216,90,72,0.14)",
      color: "var(--red)",
    };
  if (level === "warn")
    return {
      background: "rgba(245,192,66,0.16)",
      color: "#c98a18",
    };
  return {
    background: "var(--card-2)",
    color: "var(--ink-3)",
  };
}
</script>

<template>
  <section
    class="relative flex h-full flex-col overflow-hidden"
    :style="{
      background: 'var(--card)',
      borderRadius: 'var(--radius-card)',
      border: '1px solid var(--line)',
      padding: '16px',
    }"
  >
    <!-- 标题区 -->
    <div class="mb-3 flex flex-shrink-0 items-center justify-between">
      <div>
        <div
          class="text-[10.5px] font-medium uppercase tracking-[1.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          Monitor · 知乎
        </div>
        <div
          class="font-display mt-1 font-bold"
          :style="{ fontSize: '18px', letterSpacing: '-0.4px' }"
        >
          排名异动
        </div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          {{ subLabel }}
        </div>
      </div>
      <button
        type="button"
        class="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px]"
        :style="{
          background: 'var(--card-2)',
          color: 'var(--ink-2)',
          border: '1px solid var(--line)',
        }"
        @click="router.push({ name: 'monitor', query: { tab: 'zhihu' } })"
      >
        全部
        <Icon name="arrowRight" :size="10" />
      </button>
    </div>

    <!--
      异动列表 —— 自适应布局：默认单列；卡片足够宽（视口 ≥ xl=1280px
      时，每张卡 ≈ 600px）切换成双列展示，让用户一眼看更多告警。
      rows 为空时显示友好的空状态占位，等真实告警进来再覆盖。
    -->
    <div
      v-if="rows.length === 0"
      class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      暂无告警 · 监测任务还没有触发掉名
    </div>
    <div v-else class="grid min-h-0 flex-1 grid-cols-1 gap-1.5 overflow-y-auto xl:grid-cols-2">
      <div
        v-for="a in rows"
        :key="a.id"
        class="flex items-start gap-2.5 rounded-[10px] p-2.5"
        :style="{
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
        }"
      >
        <span
          class="inline-flex flex-shrink-0 items-center justify-center"
          :style="{
            width: '24px',
            height: '24px',
            borderRadius: '7px',
            ...badgeStyle(a.level),
          }"
        >
          <Icon :name="a.kind" :size="11" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12px] font-semibold">{{ a.kw }}</div>
          <div
            class="mt-0.5 truncate text-[10.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            {{ a.body }}
          </div>
        </div>
        <span
          class="flex-shrink-0 text-[10px]"
          :style="{ color: 'var(--ink-4)' }"
          >{{ a.when }}</span
        >
      </div>
    </div>
  </section>
</template>
