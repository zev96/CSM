<script setup lang="ts">
/**
 * 紧急告警 / 历史报告详情 modal —— 演示性质，承载三种语义：
 *   - kind="zhihu_alert"   知乎排名告警（hero「查看报告」入口）
 *   - kind="comment_alert" 平台评论留存告警（hero「查看报告」入口）
 *   - kind="history_report" 历史检测报告（report tab「查看 →」入口）
 *
 * 内容是 V1 设计稿里的 mock，所以这是一张静态展示页 —— 任何 CTA
 * 都通过 emit("action", "...") 抛给上层（MonitorView 决定跳转 /article、
 * 复制评论、关闭等具体动作）。这样 modal 自身不持有路由 / 剪贴板等
 * 副作用，方便单独抽样调试。
 */
import { computed } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Sparkline from "@/components/ui/Sparkline.vue";

type Kind = "zhihu_alert" | "comment_alert" | "history_report";

const props = defineProps<{
  open: boolean;
  kind: Kind;
  /** history_report 模式下来源条目（n 标题 / scope 覆盖 / t 时间 / abn 异动数） */
  report?: { n: string; scope: string; t: string; abn: number };
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "action", a: "rescue" | "repost" | "close"): void;
}>();

function close() {
  emit("update:open", false);
}

/**
 * 5 个等距日期锚点 —— 14 次快照横跨 14 天，axis 给左→右等距小日期，
 * 视觉上让用户能定位「这条 dip 是哪天」。从今天倒推：今 / -3天 / -7天
 * / -10天 / -13天 五档，覆盖整条折线。
 *
 * 用 Date 本地化生成 MM-DD，时区按用户系统走（监测数据本来就只在本机
 * 看），比 hard-code 字符串更不容易日期错位。
 */
function daysAgoMMDD(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}-${dd}`;
}
const ZHIHU_SPARK_AXIS = [
  daysAgoMMDD(13),
  daysAgoMMDD(10),
  daysAgoMMDD(7),
  daysAgoMMDD(3),
  daysAgoMMDD(0),
];
// 评论留存图覆盖 7 天，给 4 个锚点够用
const COMMENT_SPARK_AXIS = [
  daysAgoMMDD(6),
  daysAgoMMDD(4),
  daysAgoMMDD(2),
  daysAgoMMDD(0),
];

const ZHIHU_TIMELINE = [
  { t: "今天 14:05", text: "「投影仪客厅家用」掉出前 10", level: "alert" as const, rank: "—" },
  { t: "今天 12:00", text: "下滑至第 9 名（−2）", level: "warn" as const, rank: "#9" },
  { t: "今天 09:00", text: "第 7 名（持平）", level: "info" as const, rank: "#7" },
  { t: "昨天 22:00", text: "第 7 名（−2）", level: "info" as const, rank: "#7" },
  { t: "昨天 16:00", text: "第 5 名（持平）", level: "info" as const, rank: "#5" },
];

const ZHIHU_TOP3 = [
  { rank: 1, who: "@家电搭子", title: "投影仪客厅怎么选 一篇就够", views: "12.4w", score: 1834 },
  { rank: 2, who: "@小白测评派", title: "客厅 100 寸投影避坑实测", views: "8.7w", score: 1402 },
  { rank: 3, who: "@光影工坊", title: "白天客厅亮度问题这样解", views: "6.1w", score: 1108 },
];

const COMMENT_DELETED = [
  { who: "@家电小王", text: "用了三个月，客厅 100 寸投影画面真的很震撼…", date: "5 月 7 日 14:20", state: "被删" as const },
  { who: "@电器搭子", text: "这台投影机的色彩还原确实强，亲测半年无问题…", date: "5 月 6 日 18:45", state: "被删" as const },
  { who: "@测评派", text: "白天看效果一般，晚上拉窗帘就香了…", date: "5 月 5 日 20:10", state: "折叠" as const },
  { who: "@影音迷", text: "推荐就别配 100 寸幕了，120 寸更带感…", date: "5 月 4 日 21:00", state: "被删" as const },
  { who: "@小张评测", text: "对比了三台同价位的，这台亮度最稳…", date: "5 月 3 日 11:30", state: "被删" as const },
  { who: "@家居博主", text: "客厅吊装效果可以，就是布线麻烦…", date: "5 月 2 日 09:15", state: "被删" as const },
];

const REPORT_ITEMS = [
  { kw: "无线吸尘器哪款好用", type: "知乎问题", from: "#5", to: "#3", change: 2, status: "ok" as const },
  { kw: "宠物家庭吸尘器", type: "知乎问题", from: "#1", to: "#1", change: 0, status: "ok" as const },
  { kw: "母婴加湿器推荐", type: "知乎问题", from: "#7", to: "#12", change: -5, status: "warn" as const },
  { kw: "投影仪客厅家用", type: "知乎问题", from: "#9", to: "—", change: -99, status: "alert" as const },
  { kw: "客厅投影仪 100 寸", type: "B 站评论", from: "14/14", to: "8/14", change: -3, status: "alert" as const },
];

const title = computed(() => {
  if (props.kind === "zhihu_alert") return "「投影仪客厅家用」紧急告警";
  if (props.kind === "comment_alert") return "「客厅投影仪 100 寸」评论留存告警";
  return props.report?.n ?? "历史报告";
});

const subtitle = computed(() => {
  if (props.kind === "zhihu_alert") return "知乎问题 · 1 小时前的快照";
  if (props.kind === "comment_alert") return "B 站 · 近 2 小时";
  return `${props.report?.scope ?? ""} · ${props.report?.t ?? ""}`;
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
        <!-- header banner — 红色渐光提醒 (alert kind) / 中性 (report kind) -->
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
            <div
              aria-hidden="true"
              :style="{
                position: 'absolute',
                bottom: '-60px', left: '120px',
                width: '180px', height: '180px',
                background: 'radial-gradient(circle, rgba(238,106,42,0.35), transparent 65%)',
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
              >
                {{
                  kind === "zhihu_alert"
                    ? "1 个紧急告警"
                    : kind === "comment_alert"
                      ? "1 个紧急告警 · B 站"
                      : "历史检测报告"
                }}
              </div>
              <div
                class="font-display mt-1 font-bold"
                :style="{ fontSize: '22px', letterSpacing: '-0.5px', lineHeight: 1.25 }"
              >
                {{ title }}
              </div>
              <div
                class="mt-1 text-[12px]"
                :style="{
                  color: kind === 'history_report' ? 'var(--ink-3)' : 'rgba(255,255,255,0.6)',
                }"
              >
                {{ subtitle }}
              </div>
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
            <!-- KPIs -->
            <div class="grid grid-cols-3 gap-3">
              <div
                v-for="s in [
                  { l: '当前排名', v: '—', sub: '已掉出前 10' },
                  { l: '上次排名', v: '#9', sub: '1 小时前' },
                  { l: '检查频率', v: '每 6 小时', sub: '次日 09:00 复查' },
                ]"
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
                  :style="{ fontSize: '20px' }"
                >{{ s.v }}</div>
                <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                  {{ s.sub }}
                </div>
              </div>
            </div>

            <!-- sparkline -->
            <div
              :style="{
                background: 'var(--card)',
                border: '1px solid var(--line)',
                borderRadius: '12px',
                padding: '14px 16px',
              }"
            >
              <div class="mb-2 flex items-center justify-between">
                <div class="text-[12px] font-semibold">最近 14 次快照</div>
                <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                  排名越大越靠后
                </div>
              </div>
              <Sparkline
                :points="[1, 1, 2, 1, 3, 2, 3, 5, 4, 6, 7, 9, 12, 12]"
                :width="700"
                :height="80"
                stroke="var(--red, #d85a48)"
                :axis-labels="ZHIHU_SPARK_AXIS"
              />
            </div>

            <!-- timeline -->
            <div>
              <div class="mb-2 text-[12px] font-semibold">异动时间线</div>
              <div
                v-for="(e, i) in ZHIHU_TIMELINE"
                :key="i"
                class="flex items-start gap-3"
                :style="{
                  padding: '10px 12px',
                  borderRadius: '10px',
                  background: i === 0 ? 'rgba(216,90,72,0.08)' : 'var(--card)',
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

            <!-- top3 -->
            <div>
              <div class="mb-2 text-[12px] font-semibold">Top 3 抢占者</div>
              <div
                v-for="(x, i) in ZHIHU_TOP3"
                :key="i"
                class="flex items-center gap-3"
                :style="{
                  padding: '12px',
                  borderRadius: '10px',
                  background: i === 0 ? 'var(--primary-soft)' : 'var(--card)',
                  border: '1px solid var(--line)',
                  marginBottom: '6px',
                }"
              >
                <span
                  class="font-display text-[14px] font-bold"
                  :style="{
                    width: '26px',
                    color: i === 0 ? 'var(--primary-deep)' : 'var(--ink-2)',
                  }"
                >#{{ x.rank }}</span>
                <div class="min-w-0 flex-1">
                  <div class="truncate text-[13px] font-medium">{{ x.title }}</div>
                  <div class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                    {{ x.who }} · 浏览 {{ x.views }} · 赞同 {{ x.score }}
                  </div>
                </div>
                <Icon name="external" :size="13" class="opacity-50" />
              </div>
            </div>
          </template>

          <!-- ── 评论告警 ──────────────────────────────────── -->
          <template v-else-if="kind === 'comment_alert'">
            <div class="grid grid-cols-3 gap-3">
              <div
                v-for="s in [
                  { l: '当前留存', v: '8 / 14', sub: '57%' },
                  { l: '历史峰值', v: '14', sub: '5 月 1 日' },
                  { l: '近 2 小时', v: '−6 条', sub: '14 → 8' },
                ]"
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
                  :style="{ fontSize: '20px' }"
                >{{ s.v }}</div>
                <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                  {{ s.sub }}
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
                <div class="text-[12px] font-semibold">7 天留存趋势</div>
                <div class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                  14 → 8 · 跌至 57%
                </div>
              </div>
              <Sparkline
                :points="[14, 14, 13, 12, 11, 10, 8]"
                :width="700"
                :height="80"
                stroke="var(--red, #d85a48)"
                :axis-labels="COMMENT_SPARK_AXIS"
              />
            </div>

            <div>
              <div class="mb-2 text-[12px] font-semibold">被删 / 折叠的 6 条评论</div>
              <div
                v-for="(c, i) in COMMENT_DELETED"
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
                    {{ c.who }} · {{ c.date }}
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- ── 历史报告 ──────────────────────────────────── -->
          <template v-else>
            <div class="grid grid-cols-3 gap-3">
              <div
                v-for="s in [
                  { l: '覆盖范围', v: report?.scope ?? '—' },
                  { l: '记录时间', v: report?.t ?? '—' },
                  { l: '异动数量', v: `${report?.abn ?? 0} 个` },
                ]"
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
                  :style="{ fontSize: '18px' }"
                >{{ s.v }}</div>
              </div>
            </div>

            <div>
              <div class="mb-2 text-[12px] font-semibold">各任务变化明细</div>
              <div
                :style="{
                  border: '1px solid var(--line)',
                  borderRadius: '12px',
                  overflow: 'hidden',
                }"
              >
                <div
                  class="grid items-center text-[11px] uppercase"
                  :style="{
                    gridTemplateColumns: '1.6fr .8fr .6fr .6fr .6fr .6fr',
                    background: 'var(--card-2)',
                    padding: '8px 14px',
                    letterSpacing: '1.2px',
                    color: 'var(--ink-3)',
                  }"
                >
                  <div>关键词</div><div>类型</div><div>上期</div><div>本期</div><div>变化</div><div>状态</div>
                </div>
                <div
                  v-for="(r, i) in REPORT_ITEMS"
                  :key="i"
                  class="grid items-center text-[12.5px]"
                  :style="{
                    gridTemplateColumns: '1.6fr .8fr .6fr .6fr .6fr .6fr',
                    padding: '12px 14px',
                    borderTop: '1px solid var(--line)',
                    background: r.status === 'alert' ? 'rgba(216,90,72,0.05)' : 'transparent',
                  }"
                >
                  <div class="truncate font-medium">{{ r.kw }}</div>
                  <div :style="{ color: 'var(--ink-2)' }">{{ r.type }}</div>
                  <div class="font-mono" :style="{ color: 'var(--ink-3)' }">{{ r.from }}</div>
                  <div class="font-mono font-bold">{{ r.to }}</div>
                  <div>
                    <Pill v-if="r.change > 0" tone="ok">+{{ r.change }}</Pill>
                    <Pill v-else-if="r.change === 0" tone="info">持平</Pill>
                    <Pill v-else-if="r.change > -10" tone="warn">{{ r.change }}</Pill>
                    <Pill v-else tone="alert">掉出</Pill>
                  </div>
                  <div>
                    <Pill v-if="r.status === 'ok'" tone="ok">正常</Pill>
                    <Pill v-else-if="r.status === 'warn'" tone="warn">关注</Pill>
                    <Pill v-else tone="alert">告警</Pill>
                  </div>
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
            <template v-if="kind === 'zhihu_alert'">
              建议：基于 Top 3 内容补一篇救场答案
            </template>
            <template v-else-if="kind === 'comment_alert'">
              建议：补发 6 条同主题评论保留存
            </template>
            <template v-else>
              共 {{ REPORT_ITEMS.length }} 项任务参与本次检测
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
              v-if="kind === 'zhihu_alert'"
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
              v-else-if="kind === 'comment_alert'"
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
