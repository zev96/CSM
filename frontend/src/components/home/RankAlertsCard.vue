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

interface MonitorTaskRow {
  id: number;
  name: string;
  enabled: boolean;
  latest: {
    status: string;
    rank: number;
    checked_at: string | null;
    metric?: Record<string, any>;
  } | null;
}

// 知乎任务 + 三个评论平台任务都纳入预警视野（用户要求：评论留存率低和
// 知乎命中数少也要在首页"预警卡"里看到，不仅是排名跌出）。
const tasks = ref<MonitorTaskRow[]>([]);            // 知乎
const commentPlatforms = ref<
  { platform: string; label: string; tasks: MonitorTaskRow[] }[]
>([]);
const loaded = ref(false);

const topN = computed(() => cfg.data?.monitor?.alert_top_n ?? 5);

// 知乎"命中数"阈值 —— 用户品牌在 top_n 答案里出现次数低于这个值就预警。
// 默认 3（详见用户对齐后的需求），后续若要让用户在设置页改，把这个常量
// 替换成 cfg.data?.monitor?.zhihu_min_matched 即可。
const ZHIHU_MIN_MATCHED = 3;
// 评论 batch 留存率阈值 —— 一个 batch 里 matched=true 的占比低于这个值
// 就预警。默认 60%。
const COMMENT_MIN_RETENTION = 0.6;

// 评论平台 task.name 的 batch 前缀解析（约定见 MonitorView.parseBatchName）：
// 批量导入的 task.name = "{batchName} - {urlTail}"，单条新增没前缀。
function parseBatchName(name: string): string {
  const idx = name.lastIndexOf(" - ");
  if (idx <= 0) return name;
  return name.slice(0, idx);
}

function zhihuSeverity(t: MonitorTaskRow): Level | "ok" {
  if (!t.latest) return "info";
  if (t.latest.status === "failed" || t.latest.status === "risk_control")
    return "alert";
  if (t.latest.status !== "ok") return "info";
  const rank = t.latest.rank;
  const matched = Number(t.latest.metric?.matched_count ?? 0);
  if (rank < 1 || rank > topN.value) return "warn";
  if (matched < ZHIHU_MIN_MATCHED) return "warn";   // 新增：命中数过少
  return "ok";
}

// 知乎预警行 —— 兼容旧逻辑（rank 掉出 top_n）+ 新逻辑（matched_count < 3）。
const zhihuAlerts = computed<AlertRow[]>(() => {
  const out: AlertRow[] = [];
  for (const t of tasks.value) {
    const lvl = zhihuSeverity(t);
    if (lvl === "ok") continue;
    const rank = t.latest?.rank ?? -1;
    const matched = Number(t.latest?.metric?.matched_count ?? 0);
    let body: string;
    if (lvl === "alert") {
      body = "排名异常 — 失败或风控";
    } else if (!t.latest) {
      body = "等待首次抓取";
    } else if (rank < 1 || rank > topN.value) {
      body = `跌出前 ${topN.value} — 当前第 ${rank > 0 ? rank : "—"} 名`;
    } else if (matched < ZHIHU_MIN_MATCHED) {
      body = `命中数偏少 — 仅 ${matched} 条上榜（< ${ZHIHU_MIN_MATCHED}）`;
    } else {
      body = "等待首次抓取";
    }
    out.push({
      id: `zhihu-${t.id}`,
      kw: t.name,
      body,
      when: t.latest?.checked_at ? formatTime(t.latest.checked_at) : "—",
      level: lvl,
      kind: "warn",
    });
  }
  return out;
});

// 评论 batch 留存率预警 —— 把同一 batch（task.name 前缀相同）的 ok 状态
// task 聚合：matched / ok_count < 60% 触发 batch 维度 warn。
const commentBatchAlerts = computed<AlertRow[]>(() => {
  const out: AlertRow[] = [];
  for (const { platform, label, tasks: ts } of commentPlatforms.value) {
    const groups = new Map<string, MonitorTaskRow[]>();
    for (const t of ts) {
      const bn = parseBatchName(t.name);
      const arr = groups.get(bn) ?? [];
      arr.push(t);
      groups.set(bn, arr);
    }
    for (const [batchName, group] of groups) {
      const okGroup = group.filter((t) => t.latest?.status === "ok");
      if (okGroup.length === 0) continue;   // 没跑过的 batch 不算预警
      const matched = okGroup.filter(
        (t) => t.latest?.metric?.matched === true,
      ).length;
      const ratio = matched / okGroup.length;
      if (ratio >= COMMENT_MIN_RETENTION) continue;
      // 取 batch 内最新一次 checked_at 作为预警时间
      const latestIso = okGroup
        .map((t) => t.latest?.checked_at)
        .filter((x): x is string => !!x)
        .sort()
        .pop();
      out.push({
        id: `${platform}-${batchName}`,
        kw: `${label} · ${batchName}`,
        body: `留存率 ${Math.round(ratio * 100)}% · ${matched}/${okGroup.length} 条还在`,
        when: latestIso ? formatTime(latestIso) : "—",
        level: "warn" as Level,
        kind: "warn" as const,
      });
    }
  }
  return out;
});

// 真实预警 = 知乎告警 + 评论批次告警，按严重度排
const realAlerts = computed<AlertRow[]>(() => {
  const order: Record<Level, number> = { alert: 0, warn: 1, info: 2 };
  return [...zhihuAlerts.value, ...commentBatchAlerts.value].sort(
    (a, b) => order[a.level] - order[b.level],
  );
});

// 无异动时的兜底行：把知乎"上榜中"的任务展示出来，让首页能看到监测在
// 跑、当前排名是多少。否则用户在监测中心明明有任务，首页却空白。
const okRows = computed<AlertRow[]>(() =>
  tasks.value
    .filter((t) => zhihuSeverity(t) === "ok")
    .map((t) => ({
      id: `zhihu-ok-${t.id}`,
      kw: t.name,
      body: `上榜 · 第 ${t.latest?.rank ?? "—"} 名`,
      when: t.latest?.checked_at ? formatTime(t.latest.checked_at) : "—",
      level: "info" as Level,
      kind: "vault" as const,
    })),
);

const rows = computed<AlertRow[]>(() => {
  if (!loaded.value) return FALLBACK_ALERTS;
  // 有异动 → 优先显示异动行；不够 4 条用 ok 任务补满（异动在上，平稳在下）。
  // 全部任务都平稳 → 完全显示 ok 行作为概览。
  // 一个任务都没有 → 走空状态文案。
  const merged = [...realAlerts.value, ...okRows.value];
  return merged.slice(0, 4);
});

const subLabel = computed(() => {
  const alerts = realAlerts.value.length;
  const zhihuTotal = tasks.value.length;
  const commentTotal = commentPlatforms.value.reduce(
    (a, p) => a + p.tasks.length,
    0,
  );
  const totalTasks = zhihuTotal + commentTotal;
  if (alerts > 0) return `近 1 小时 · ${alerts} 个预警`;
  if (totalTasks > 0) {
    const parts: string[] = [];
    if (zhihuTotal > 0) parts.push(`知乎 ${zhihuTotal}`);
    if (commentTotal > 0) parts.push(`评论 ${commentTotal}`);
    return `${parts.join(" · ")} 任务监测中 · 暂无预警`;
  }
  return "暂无监测任务";
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

const COMMENT_PLATFORM_LABEL: Record<string, string> = {
  bilibili_comment: "B 站",
  douyin_comment: "抖音",
  kuaishou_comment: "快手",
};

onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/summary");
    const platforms = r.data.platforms ?? {};
    tasks.value = platforms.zhihu_question?.tasks ?? [];
    commentPlatforms.value = (Object.keys(COMMENT_PLATFORM_LABEL) as string[])
      .map((key) => ({
        platform: key,
        label: COMMENT_PLATFORM_LABEL[key],
        tasks: (platforms[key]?.tasks ?? []) as MonitorTaskRow[],
      }))
      .filter((x) => x.tasks.length > 0);
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
          Monitor · 全平台预警
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
