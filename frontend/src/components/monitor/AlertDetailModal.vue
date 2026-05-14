<script setup lang="ts">
/**
 * 紧急告警 / 历史报告详情 modal —— 三种语义共用一张面板：
 *   - kind="zhihu_alert"    知乎排名告警 → 渲染 zhihuData
 *   - kind="comment_alert"  平台评论留存告警 → 渲染 commentData
 *   - kind="history_report" 历史监测报告 → 渲染 report 基本元信息
 *
 * 重构说明：原来所有数据都是 mock 常量（ZHIHU_TIMELINE / ZHIHU_TOP3 /
 * COMMENT_DELETED / REPORT_ITEMS 等），导致点开「查看报告」永远是设计稿
 * 假数据。现在改成纯展示组件：所有数据通过 props 传入，由 MonitorView 在
 * 打开模态时根据当前 alert 的 taskId / batchName 从真实 task + snapshot +
 * results 算好。数据不到位（首次未抓取）就显示空态而不是塞 mock。
 */
import { computed } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Sparkline from "@/components/ui/Sparkline.vue";

type Kind = "zhihu_alert" | "comment_alert" | "history_report";

interface AlertTimelineItem {
  t: string;
  rank: string;
  text: string;
  level: "alert" | "warn" | "info";
}
interface AlertGrabber {
  rank: number;
  who: string;
  title: string;
  voteup?: number;
  matchesBrand?: boolean;
}
interface AlertDeletedComment {
  who: string;
  text: string;
  date: string;
  state: "被删" | "折叠";
}
interface ZhihuAlertData {
  title: string;
  subtitle: string;
  matchedCount: number;
  matchedCountPrev: number | null;
  alertTopN: number;
  firstRank: number;
  scheduleLabel: string;
  sparkPoints: number[];
  sparkAxis: string[];
  timeline: AlertTimelineItem[];
  topAnswers: AlertGrabber[];
}
interface CommentAlertData {
  title: string;
  subtitle: string;
  retained: number;
  total: number;
  ratio: number;
  recentDelta: number;
  prevRetained: number | null;
  sparkPoints: number[];
  sparkAxis: string[];
  deleted: AlertDeletedComment[];
}

// history_report 模式下后端 /api/monitor/reports 单条 item 形状：
//   period: "2026-05-14" 或 "2026-W19"
//   total_checks: 该周期内总检查次数
//   alert_count: 触发告警的检查次数
//   by_status: { ok: N, failed: N, risk_control: N, ... } 状态分布
//   task_count: 涉及的任务数
// 老代码用 { n, scope, t, abn } 4 字段的简化形状，这里向后兼容，
// 没传新字段就 fallback 到旧字段。
interface HistoryReportProps {
  /** 显示名（period） */
  n: string;
  /** 覆盖范围副标 */
  scope: string;
  /** 时间字符串 */
  t: string;
  /** 异动数 */
  abn: number;
  /** 总检查次数（来自后端 total_checks） */
  total_checks?: number;
  /** 告警次数（== abn，但语义更明确） */
  alert_count?: number;
  /** 任务数 */
  task_count?: number;
  /** 状态分布 */
  by_status?: Record<string, number>;
  /** 按平台（task.type）拆分。后端返回 zhihu_question / bilibili_comment
   * / douyin_comment / kuaishou_comment 四种 key。 */
  by_platform?: Record<
    string,
    { checks: number; alerts: number; task_count: number }
  >;
}

const props = defineProps<{
  open: boolean;
  kind: Kind;
  /** history_report 模式下来源条目 */
  report?: HistoryReportProps;
  /** zhihu_alert 模式下从 MonitorView 喂的真实数据；null 时显示空态 */
  zhihuData?: ZhihuAlertData;
  /** comment_alert 模式下的真实数据 */
  commentData?: CommentAlertData;
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "action", a: "rescue" | "repost" | "close"): void;
}>();

function close() {
  emit("update:open", false);
}

const title = computed(() => {
  if (props.kind === "zhihu_alert") return props.zhihuData?.title ?? "知乎排名告警";
  if (props.kind === "comment_alert") return props.commentData?.title ?? "评论留存告警";
  return props.report?.n ?? "历史报告";
});
const subtitle = computed(() => {
  if (props.kind === "zhihu_alert") return props.zhihuData?.subtitle ?? "暂无数据";
  if (props.kind === "comment_alert") return props.commentData?.subtitle ?? "暂无数据";
  return `${props.report?.scope ?? ""} · ${props.report?.t ?? ""}`;
});
const eyebrow = computed(() => {
  if (props.kind === "zhihu_alert") return "知乎告警详情";
  if (props.kind === "comment_alert") return "评论留存详情";
  return "历史监测报告";
});

// ── history_report 派生数据 ───────────────────────────────────────
// 顶部 4 个 KPI 卡片的数据。total_checks/task_count 是后端新字段，
// 老调用方还没传时回退到 abn / "—"，保持向后兼容。
const reportKpis = computed(() => {
  const r = props.report;
  return [
    { l: "周期", v: r?.n ?? "—" },
    { l: "总检查", v: `${r?.total_checks ?? "—"} 次` },
    {
      l: "告警",
      v: `${r?.alert_count ?? r?.abn ?? 0} 次`,
      c: (r?.alert_count ?? r?.abn ?? 0) > 0 ? "var(--red)" : "var(--green)",
    },
    { l: "任务数", v: `${r?.task_count ?? "—"}` },
  ];
});

const alertRatePercent = computed(() => {
  const total = props.report?.total_checks ?? 0;
  const alerts = props.report?.alert_count ?? props.report?.abn ?? 0;
  if (total <= 0) return 0;
  return Math.round((alerts / total) * 100);
});

// 状态分布 —— 后端 by_status 的 dict 按"严重度"顺序展开。csm_core 里
// 出现过的 status：ok / warn / alert / failed / risk_control（参见
// MonitorResult.status）。没在 by_status 里出现的不渲染，避免一排零值。
const STATUS_META: Record<string, { label: string; color: string; order: number }> = {
  ok: { label: "正常", color: "var(--green)", order: 0 },
  warn: { label: "预警", color: "#c98a18", order: 1 },
  alert: { label: "告警", color: "var(--red)", order: 2 },
  risk_control: { label: "风控", color: "#a3382a", order: 3 },
  failed: { label: "抓取失败", color: "var(--ink-3)", order: 4 },
};

const statusBreakdown = computed(() => {
  const by = props.report?.by_status ?? {};
  const total = Object.values(by).reduce((a, b) => a + (b || 0), 0);
  if (total === 0) return [];
  return Object.entries(by)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => {
      const meta = STATUS_META[key] ?? { label: key, color: "var(--ink-3)", order: 99 };
      return {
        key,
        label: meta.label,
        color: meta.color,
        order: meta.order,
        count,
        percent: Math.round((count / total) * 100),
      };
    })
    .sort((a, b) => a.order - b.order);
});

// 平台拆分。把后端 task.type 的英文 key 翻译成中文展示标签，按知乎 →
// B站 → 抖音 → 快手的固定顺序展开（其它未知 type 排最后）。
const PLATFORM_META: Record<string, { label: string; color: string; order: number }> = {
  zhihu_question: { label: "知乎问题", color: "#1772f6", order: 0 },
  bilibili_comment: { label: "B 站", color: "var(--primary)", order: 1 },
  douyin_comment: { label: "抖音", color: "#1e1c19", order: 2 },
  kuaishou_comment: { label: "快手", color: "var(--yellow)", order: 3 },
};

const platformBreakdown = computed(() => {
  const by = props.report?.by_platform ?? {};
  const rows = Object.entries(by)
    .filter(([, v]) => (v?.checks ?? 0) > 0)
    .map(([key, v]) => {
      const meta = PLATFORM_META[key] ?? { label: key, color: "var(--ink-3)", order: 99 };
      return {
        key,
        label: meta.label,
        color: meta.color,
        order: meta.order,
        checks: v.checks,
        alerts: v.alerts,
        taskCount: v.task_count,
      };
    })
    .sort((a, b) => a.order - b.order);
  return rows;
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-40 flex items-center justify-center"
      :style="{ background: 'rgba(28,26,23,0.4)' }"
      @click.self="close"
    >
      <div
        class="anim-up overflow-hidden"
        :style="{
          background: 'var(--bg-inner)',
          width: '760px',
          maxWidth: '94vw',
          maxHeight: '90vh',
          borderRadius: 'var(--radius-card)',
          border: '1px solid var(--line)',
          boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
          display: 'flex',
          flexDirection: 'column',
        }"
      >
        <!-- header banner -->
        <div
          class="relative flex-shrink-0 overflow-hidden"
          :style="{
            background: kind === 'history_report' ? 'var(--card-2)' : 'var(--dark)',
            color: kind === 'history_report' ? 'var(--ink)' : '#fbf7ec',
            padding: '22px 26px',
            borderBottom: '1px solid var(--line)',
          }"
        >
          <template v-if="kind !== 'history_report'">
            <div
              aria-hidden="true"
              :style="{
                position: 'absolute',
                top: '-40px', right: '-20px',
                width: '220px', height: '220px',
                background: 'radial-gradient(circle, rgba(216,90,72,0.5), transparent 65%)',
                filter: 'blur(12px)',
                pointerEvents: 'none',
              }"
            />
          </template>
          <div class="relative flex items-start justify-between gap-4">
            <div class="min-w-0">
              <div
                class="text-[10.5px] uppercase"
                :style="{
                  letterSpacing: '1.5px',
                  color: kind === 'history_report' ? 'var(--ink-3)' : 'rgba(255,255,255,0.5)',
                }"
              >{{ eyebrow }}</div>
              <div
                class="font-display mt-1 font-bold"
                :style="{ fontSize: '22px', letterSpacing: '-0.5px', lineHeight: 1.25 }"
              >{{ title }}</div>
              <div
                class="mt-1 text-[12px]"
                :style="{
                  color: kind === 'history_report' ? 'var(--ink-3)' : 'rgba(255,255,255,0.6)',
                }"
              >{{ subtitle }}</div>
            </div>
            <button
              type="button"
              class="inline-flex flex-shrink-0 items-center justify-center"
              :style="{
                width: '32px',
                height: '32px',
                borderRadius: '999px',
                background: kind === 'history_report' ? 'var(--card)' : 'rgba(255,255,255,0.08)',
                border: kind === 'history_report' ? '1px solid var(--line)' : '1px solid rgba(255,255,255,0.12)',
                color: kind === 'history_report' ? 'var(--ink-2)' : '#fbf7ec',
              }"
              @click="close"
            >
              <Icon name="x" :size="16" />
            </button>
          </div>
        </div>

        <!-- body (scrollable) -->
        <div
          class="flex flex-1 flex-col gap-5 overflow-y-auto"
          :style="{ padding: '22px 26px' }"
        >
          <!-- ── 知乎告警 ──────────────────────────────────── -->
          <template v-if="kind === 'zhihu_alert'">
            <div
              v-if="!zhihuData"
              class="py-8 text-center text-[12.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              暂无数据 —— 先点「立刻监测」抓一次，再回到告警查看详情。
            </div>
            <template v-else>
              <!-- KPI 三联 -->
              <div class="grid grid-cols-3 gap-3">
                <div
                  :style="{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">本次命中</div>
                  <div class="font-display mt-0.5 font-bold" :style="{ fontSize: '20px' }">
                    <template v-if="zhihuData.matchedCount > 0">
                      {{ zhihuData.matchedCount }} / {{ zhihuData.alertTopN }}
                    </template>
                    <span
                      v-else
                      :style="{ color: 'var(--red, #d85a48)', fontSize: '15px' }"
                    >前 {{ zhihuData.alertTopN }} 以外</span>
                  </div>
                  <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                    <template v-if="zhihuData.firstRank > 0">
                      最高 #{{ zhihuData.firstRank }}
                    </template>
                    <template v-else>未上榜</template>
                  </div>
                </div>
                <div
                  :style="{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">上次命中</div>
                  <div class="font-display mt-0.5 font-bold" :style="{ fontSize: '20px' }">
                    <template v-if="zhihuData.matchedCountPrev !== null">
                      {{ zhihuData.matchedCountPrev }} / {{ zhihuData.alertTopN }}
                    </template>
                    <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                  </div>
                  <div
                    v-if="zhihuData.matchedCountPrev !== null"
                    class="mt-0.5 text-[11px]"
                    :style="{ color: 'var(--ink-3)' }"
                  >
                    变化
                    <span
                      :style="{
                        color: (zhihuData.matchedCount - zhihuData.matchedCountPrev) >= 0
                          ? 'var(--green, #6c9b5d)'
                          : 'var(--red, #d85a48)',
                      }"
                    >
                      {{ (zhihuData.matchedCount - zhihuData.matchedCountPrev) >= 0 ? '+' : '' }}{{ zhihuData.matchedCount - zhihuData.matchedCountPrev }}
                    </span>
                  </div>
                </div>
                <div
                  :style="{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">检查频率</div>
                  <div class="font-display mt-0.5 font-bold" :style="{ fontSize: '16px' }">
                    {{ zhihuData.scheduleLabel }}
                  </div>
                </div>
              </div>

              <!-- 排名 sparkline -->
              <div
                :style="{
                  background: 'var(--card)',
                  border: '1px solid var(--line)',
                  borderRadius: '12px',
                  padding: '14px 16px',
                }"
              >
                <div class="mb-2 flex items-center justify-between">
                  <div class="text-[12px] font-semibold">最近 {{ zhihuData.sparkPoints.length }} 次首条排名</div>
                  <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">数值越小越靠前</div>
                </div>
                <Sparkline
                  v-if="zhihuData.sparkPoints.length >= 2"
                  :points="zhihuData.sparkPoints"
                  :width="700"
                  :height="80"
                  stroke="var(--red, #d85a48)"
                  :axis-labels="zhihuData.sparkAxis"
                />
                <div
                  v-else
                  class="py-3 text-[11.5px]"
                  :style="{ color: 'var(--ink-3)' }"
                >至少需要两次检查才能成线。</div>
              </div>

              <!-- 异动时间线 -->
              <div v-if="zhihuData.timeline.length">
                <div class="mb-2 text-[12px] font-semibold">异动时间线</div>
                <div
                  v-for="(e, i) in zhihuData.timeline"
                  :key="i"
                  class="flex items-start gap-3"
                  :style="{
                    padding: '10px 12px',
                    borderRadius: '10px',
                    background: e.level === 'alert' ? 'rgba(216,90,72,0.08)' : 'var(--card)',
                    border: '1px solid var(--line)',
                    marginBottom: '6px',
                  }"
                >
                  <div
                    class="font-mono flex-shrink-0 text-[11px]"
                    :style="{ color: 'var(--ink-3)', width: '90px' }"
                  >{{ e.t }}</div>
                  <div class="font-display flex-shrink-0 text-[13px] font-bold" :style="{ width: '46px' }">
                    {{ e.rank }}
                  </div>
                  <div class="flex-1 text-[12.5px]">{{ e.text }}</div>
                  <Pill :tone="e.level">
                    {{ e.level === "alert" ? "告警" : e.level === "warn" ? "下滑" : "正常" }}
                  </Pill>
                </div>
              </div>

              <!-- Top 抢占者（带命中标记） -->
              <div v-if="zhihuData.topAnswers.length">
                <div class="mb-2 text-[12px] font-semibold">Top {{ zhihuData.topAnswers.length }} 答案</div>
                <div
                  v-for="(x, i) in zhihuData.topAnswers"
                  :key="i"
                  class="flex items-center gap-3"
                  :style="{
                    padding: '12px',
                    borderRadius: '10px',
                    background: x.matchesBrand ? 'var(--primary-soft)' : 'var(--card)',
                    border: '1px solid ' + (x.matchesBrand ? 'rgba(238,106,42,0.3)' : 'var(--line)'),
                    marginBottom: '6px',
                  }"
                >
                  <span
                    class="font-display text-[14px] font-bold"
                    :style="{
                      width: '26px',
                      color: x.matchesBrand ? 'var(--primary-deep)' : 'var(--ink-2)',
                    }"
                  >#{{ x.rank }}</span>
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-[13px] font-medium">{{ x.title || "（无摘要）" }}</div>
                    <div class="flex items-center gap-2 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                      <span>{{ x.who }}</span>
                      <span v-if="x.voteup">· 👍 {{ x.voteup }}</span>
                      <span
                        v-if="x.matchesBrand"
                        class="ml-auto"
                        :style="{ color: 'var(--primary-deep)', fontWeight: 600 }"
                      >自家</span>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </template>

          <!-- ── 评论告警 ──────────────────────────────────── -->
          <template v-else-if="kind === 'comment_alert'">
            <div
              v-if="!commentData"
              class="py-8 text-center text-[12.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              暂无数据 —— 批次内任务还没抓过，先点「立刻监测」。
            </div>
            <template v-else>
              <div class="grid grid-cols-3 gap-3">
                <div
                  :style="{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">当前留存</div>
                  <div class="font-display mt-0.5 font-bold" :style="{ fontSize: '20px' }">
                    {{ commentData.retained }} / {{ commentData.total }}
                  </div>
                  <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                    {{ commentData.ratio }}%
                  </div>
                </div>
                <div
                  :style="{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">上次留存</div>
                  <div class="font-display mt-0.5 font-bold" :style="{ fontSize: '20px' }">
                    <template v-if="commentData.prevRetained !== null">
                      {{ commentData.prevRetained }} / {{ commentData.total }}
                    </template>
                    <span v-else :style="{ color: 'var(--ink-3)' }">—</span>
                  </div>
                </div>
                <div
                  :style="{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                  }"
                >
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">两次变化</div>
                  <div
                    class="font-display mt-0.5 font-bold"
                    :style="{
                      fontSize: '20px',
                      color: commentData.recentDelta >= 0
                        ? 'var(--ink)'
                        : 'var(--red, #d85a48)',
                    }"
                  >
                    {{ commentData.recentDelta > 0 ? '+' : '' }}{{ commentData.recentDelta }} 条
                  </div>
                </div>
              </div>

              <div
                :style="{
                  background: 'var(--card)',
                  border: '1px solid var(--line)',
                  borderRadius: '12px',
                  padding: '14px 16px',
                }"
              >
                <div class="mb-2 flex items-center justify-between">
                  <div class="text-[12px] font-semibold">留存率趋势</div>
                  <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                    <template v-if="commentData.prevRetained !== null">
                      {{ commentData.prevRetained }} → {{ commentData.retained }} · {{ commentData.ratio }}%
                    </template>
                    <template v-else>仅一次快照</template>
                  </div>
                </div>
                <Sparkline
                  v-if="commentData.sparkPoints.length >= 2"
                  :points="commentData.sparkPoints"
                  :width="700"
                  :height="80"
                  stroke="var(--red, #d85a48)"
                  :axis-labels="commentData.sparkAxis"
                />
                <div
                  v-else
                  class="py-3 text-[11.5px]"
                  :style="{ color: 'var(--ink-3)' }"
                >至少需要两次检查才能成线。</div>
              </div>

              <div v-if="commentData.deleted.length">
                <div class="mb-2 text-[12px] font-semibold">
                  被删 / 折叠的 {{ commentData.deleted.length }} 条评论
                </div>
                <div
                  v-for="(c, i) in commentData.deleted"
                  :key="i"
                  class="flex items-start gap-3"
                  :style="{
                    padding: '10px 12px',
                    borderRadius: '10px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                    marginBottom: '6px',
                  }"
                >
                  <Pill :tone="c.state === '被删' ? 'alert' : 'warn'">{{ c.state }}</Pill>
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-[12.5px]">{{ c.text }}</div>
                    <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                      抢占者 {{ c.who }} · {{ c.date }}
                    </div>
                  </div>
                </div>
              </div>
              <div
                v-else
                class="py-3 text-[12px]"
                :style="{ color: 'var(--ink-3)' }"
              >批次内所有评论都还在 —— 不必紧张。</div>
            </template>
          </template>

          <!-- ── 历史报告 ──────────────────────────────────── -->
          <template v-else>
            <!--
              KPI 一行：检查次数 / 告警次数 / 涉及任务 / 周期。
              这 4 个数字直接来自后端 /api/monitor/reports 的单条 item，
              MonitorView 在 openReport() 时已经全量透传过来。
            -->
            <div class="grid grid-cols-4 gap-3 mb-4">
              <div
                v-for="s in reportKpis"
                :key="s.l"
                :style="{
                  padding: '12px 14px',
                  borderRadius: '12px',
                  background: 'var(--card)',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">{{ s.l }}</div>
                <div
                  class="font-display mt-0.5 font-bold"
                  :style="{ fontSize: '20px', color: s.c ?? 'var(--ink)' }"
                >{{ s.v }}</div>
              </div>
            </div>

            <!--
              告警率视觉：alert / total 比例条。total=0 时整段隐藏。
            -->
            <div
              v-if="(report?.total_checks ?? 0) > 0"
              class="mb-4"
              :style="{
                padding: '14px 16px',
                borderRadius: '12px',
                background: 'var(--card)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="flex items-baseline justify-between mb-2">
                <div class="text-[12px] font-semibold">告警率</div>
                <div
                  class="font-display font-bold tabular-nums"
                  :style="{ fontSize: '18px' }"
                >
                  {{ alertRatePercent }}%
                </div>
              </div>
              <div
                class="relative"
                :style="{
                  height: '6px',
                  background: 'var(--line-2)',
                  borderRadius: '999px',
                }"
              >
                <div
                  :style="{
                    width: `${alertRatePercent}%`,
                    height: '100%',
                    background: alertRatePercent >= 30 ? 'var(--red)' : alertRatePercent > 0 ? '#c98a18' : 'var(--green)',
                    borderRadius: '999px',
                  }"
                />
              </div>
              <div class="mt-2 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                {{ report?.alert_count ?? report?.abn ?? 0 }} 次告警 / {{ report?.total_checks ?? 0 }} 次总检查
              </div>
            </div>

            <!--
              按平台拆分 —— 让用户一眼看到这份报告里"知乎 X 次 / B 站
              Y 次 / 抖音 Z 次"各自的检查 / 告警 / 任务数。需求来自用户
              反馈："历史报告应当包括知乎问题的和三个平台的总的报告"。
            -->
            <div
              v-if="platformBreakdown.length > 0"
              class="mb-4"
              :style="{
                padding: '14px 16px',
                borderRadius: '12px',
                background: 'var(--card)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="text-[12px] font-semibold mb-3">按平台拆分</div>
              <div class="flex flex-col gap-2">
                <div
                  v-for="p in platformBreakdown"
                  :key="p.key"
                  class="grid items-center gap-2"
                  :style="{
                    gridTemplateColumns: '14px 80px 1fr auto auto',
                    fontSize: '12px',
                  }"
                >
                  <span
                    :style="{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background: p.color,
                    }"
                  />
                  <span class="font-medium">{{ p.label }}</span>
                  <span class="font-mono tabular-nums" :style="{ color: 'var(--ink-3)' }">
                    {{ p.checks }} 次检查
                  </span>
                  <span
                    class="inline-flex items-center rounded-full px-2 text-[10.5px] font-medium"
                    :style="{
                      background: p.alerts > 0 ? '#f3d3cd' : 'rgba(28,26,23,0.06)',
                      color: p.alerts > 0 ? '#a3382a' : 'var(--ink-3)',
                    }"
                  >
                    {{ p.alerts }} 次告警
                  </span>
                  <span class="font-mono text-[10.5px] tabular-nums" :style="{ color: 'var(--ink-3)' }">
                    {{ p.taskCount }} 任务
                  </span>
                </div>
              </div>
            </div>

            <!--
              按状态分布 —— ok / warn / alert / failed / risk_control 各
              多少次。后端 by_status 是个 dict，前端按预定义顺序展示，
              没出现过的 status 不渲染（避免一堆 0 噪音）。
            -->
            <div
              v-if="statusBreakdown.length > 0"
              :style="{
                padding: '14px 16px',
                borderRadius: '12px',
                background: 'var(--card)',
                border: '1px solid var(--line)',
              }"
            >
              <div class="text-[12px] font-semibold mb-3">检查结果分布</div>
              <div class="flex flex-col gap-2">
                <div
                  v-for="s in statusBreakdown"
                  :key="s.key"
                  class="flex items-center gap-3"
                >
                  <span
                    class="flex-shrink-0"
                    :style="{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background: s.color,
                    }"
                  />
                  <span class="text-[12px] font-medium" :style="{ width: '76px' }">{{ s.label }}</span>
                  <div
                    class="relative flex-1"
                    :style="{
                      height: '5px',
                      background: 'var(--line-2)',
                      borderRadius: '999px',
                    }"
                  >
                    <div
                      :style="{
                        width: `${s.percent}%`,
                        height: '100%',
                        background: s.color,
                        borderRadius: '999px',
                      }"
                    />
                  </div>
                  <span
                    class="font-mono text-[11.5px] tabular-nums"
                    :style="{ color: 'var(--ink-2)', width: '52px', textAlign: 'right' }"
                  >{{ s.count }} 次</span>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- footer -->
        <div
          class="flex flex-shrink-0 items-center justify-between"
          :style="{ padding: '14px 26px', borderTop: '1px solid var(--line)' }"
        >
          <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
            <template v-if="kind === 'zhihu_alert' && zhihuData">
              <template v-if="zhihuData.matchedCount === 0">
                建议：基于 Top 答案补一篇救场内容
              </template>
              <template v-else>
                自家命中 {{ zhihuData.matchedCount }} 条 · 持续观察
              </template>
            </template>
            <template v-else-if="kind === 'comment_alert' && commentData">
              <template v-if="commentData.deleted.length">
                建议：补发 {{ commentData.deleted.length }} 条同主题评论保留存
              </template>
              <template v-else>
                全部评论留存中
              </template>
            </template>
            <template v-else-if="kind === 'history_report'">
              报告元信息
            </template>
          </div>
          <div class="flex gap-2">
            <button
              type="button"
              :style="{
                background: 'transparent',
                border: '1px solid var(--line)',
                color: 'var(--ink-2)',
                padding: '7px 18px',
                fontSize: '12.5px',
                borderRadius: '999px',
              }"
              @click="close"
            >关闭</button>
            <button
              v-if="kind === 'zhihu_alert' && zhihuData"
              type="button"
              class="inline-flex items-center gap-1.5"
              :style="{
                background: 'var(--primary)',
                color: '#fff',
                padding: '7px 18px',
                fontSize: '12.5px',
                fontWeight: 500,
                borderRadius: '999px',
              }"
              @click="emit('action', 'rescue')"
            >
              <Icon name="edit" :size="13" />
              <span>起一篇救场</span>
            </button>
            <button
              v-else-if="kind === 'comment_alert' && commentData"
              type="button"
              class="inline-flex items-center gap-1.5"
              :style="{
                background: 'var(--primary)',
                color: '#fff',
                padding: '7px 18px',
                fontSize: '12.5px',
                fontWeight: 500,
                borderRadius: '999px',
              }"
              @click="emit('action', 'repost')"
            >
              <Icon name="refresh" :size="13" />
              <span>补发评论</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
