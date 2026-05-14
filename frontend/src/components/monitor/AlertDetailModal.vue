<script setup lang="ts">
/**
 * 紧急告警详情 modal —— 两种语义共用一张面板：
 *   - kind="zhihu_alert"    知乎排名告警 → 渲染 zhihuData
 *   - kind="comment_alert"  平台评论留存告警 → 渲染 commentData
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

type Kind = "zhihu_alert" | "comment_alert";

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

const props = defineProps<{
  open: boolean;
  kind: Kind;
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
  return props.commentData?.title ?? "评论留存告警";
});
const subtitle = computed(() => {
  if (props.kind === "zhihu_alert") return props.zhihuData?.subtitle ?? "暂无数据";
  return props.commentData?.subtitle ?? "暂无数据";
});
const eyebrow = computed(() => {
  if (props.kind === "zhihu_alert") return "知乎告警详情";
  return "评论留存详情";
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
            background: 'var(--dark)',
            color: '#fbf7ec',
            padding: '22px 26px',
            borderBottom: '1px solid var(--line)',
          }"
        >
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
          <div class="relative flex items-start justify-between gap-4">
            <div class="min-w-0">
              <div
                class="text-[10.5px] uppercase"
                :style="{ letterSpacing: '1.5px', color: 'rgba(255,255,255,0.5)' }"
              >{{ eyebrow }}</div>
              <div
                class="font-display mt-1 font-bold"
                :style="{ fontSize: '22px', letterSpacing: '-0.5px', lineHeight: 1.25 }"
              >{{ title }}</div>
              <div
                class="mt-1 text-[12px]"
                :style="{ color: 'rgba(255,255,255,0.6)' }"
              >{{ subtitle }}</div>
            </div>
            <button
              type="button"
              class="inline-flex flex-shrink-0 items-center justify-center"
              :style="{
                width: '32px',
                height: '32px',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.12)',
                color: '#fbf7ec',
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
