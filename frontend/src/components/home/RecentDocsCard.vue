<script setup lang="ts">
/**
 * 最近文档 — 严格按 CSM-RE1（V1）/src/screens/home.jsx 的 RecentDocsCard 复刻：
 *   - 头部："Recent · 文档" 小标 + "最近文档" 大标 + "近 7 天 · N 篇"
 *   - 右上 "全部 →" 跳转模板库 / 创作区
 *   - 列表：状态色块图标 + 标题 + 模板·字数 + 状态 chip + 时间
 *
 * 数据：sidecar /api/recent。如果 out_dir 还没有任何导出（新装机）
 * 就退到 V1 设计稿同款示例 6 条，保证 UI 完整。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { listRecent } from "@/api/client";
import { useSidecarReady } from "@/composables/useSidecarReady";

type Status = "已发布" | "草稿" | "归档";

interface Doc {
  id: string;
  title: string;
  tpl: string;
  words: number;
  when: string;
  status: Status;
  /** 跳转目标路径，真实文档可能是 file:// 路径，示例文档没有路径 */
  path?: string;
}

// V1 设计稿同款 fallback —— /api/recent 没数据时撑场。给 10 条让卡片
// 内部的下拉条真的有用武之地（少于卡片可见高度时不会出现 scrollbar）。
const FALLBACK_DOCS: Doc[] = [
  {
    id: "demo-d1",
    title: "宠物家庭吸尘器推荐：5 款无毛发缠绕实测",
    tpl: "导购 · 场景人群",
    words: 2380,
    when: "2 小时前",
    status: "已发布",
  },
  {
    id: "demo-d2",
    title: "无线吸尘器值不值得换？三年用户的真心话",
    tpl: "测评 · 长期使用",
    words: 1820,
    when: "今天 09:14",
    status: "草稿",
  },
  {
    id: "demo-d3",
    title: "投影仪选购：客厅 vs 卧室的两套方案",
    tpl: "导购 · 科普物品",
    words: 2150,
    when: "昨天",
    status: "已发布",
  },
  {
    id: "demo-d4",
    title: "扫地机和拖地机怎么选？一篇讲清",
    tpl: "导购 · 场景人群",
    words: 1640,
    when: "昨天",
    status: "草稿",
  },
  {
    id: "demo-d5",
    title: "母婴家庭加湿器避坑指南",
    tpl: "测评 · 安全合规",
    words: 1450,
    when: "5 月 6 日",
    status: "归档",
  },
  {
    id: "demo-d6",
    title: "千元价位降噪耳机横评：地铁 / 飞机 / 办公场景",
    tpl: "测评 · 横评",
    words: 2780,
    when: "5 月 5 日",
    status: "已发布",
  },
  {
    id: "demo-d7",
    title: "电动牙刷预算 300：值得入手的 4 款",
    tpl: "导购 · 科普物品",
    words: 1920,
    when: "5 月 4 日",
    status: "已发布",
  },
  {
    id: "demo-d8",
    title: "蒸汽拖把怎么选？厨房 / 客厅 / 木地板分场景",
    tpl: "导购 · 场景人群",
    words: 1680,
    when: "5 月 3 日",
    status: "草稿",
  },
  {
    id: "demo-d9",
    title: "扫地机器人 800 元档：哪些功能可以砍掉",
    tpl: "测评 · 长期使用",
    words: 2050,
    when: "5 月 2 日",
    status: "已发布",
  },
  {
    id: "demo-d10",
    title: "母婴温度计选购：水银 / 红外 / 耳温的取舍",
    tpl: "测评 · 安全合规",
    words: 1380,
    when: "5 月 1 日",
    status: "归档",
  },
];

const router = useRouter();
const { whenReady } = useSidecarReady();

const realDocs = ref<Doc[]>([]);
const loaded = ref(false);

function relativeTime(iso: string): string {
  try {
    const ms = Date.now() - new Date(iso).getTime();
    const m = Math.floor(ms / 60000);
    if (m < 1) return "刚刚";
    if (m < 60) return `${m} 分钟前`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} 小时前`;
    const d = Math.floor(h / 24);
    if (d === 1) return "昨天";
    if (d < 7) return `${d} 天前`;
    const date = new Date(iso);
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  } catch {
    return "—";
  }
}

const docs = computed<Doc[]>(() => {
  if (!loaded.value) return FALLBACK_DOCS;
  if (realDocs.value.length === 0) return FALLBACK_DOCS;
  return realDocs.value.slice(0, 10);
});

onMounted(async () => {
  try {
    await whenReady();
    // 最多取 10 条 —— 卡片高度有限，多于这个就靠卡片内滚动条翻看。
    const r = await listRecent(10, 7);
    realDocs.value = r.documents.map((d) => ({
      id: d.path,
      title: d.title,
      tpl: d.template_name ?? "—",
      words: d.words,
      when: relativeTime(d.modified_at),
      // 真实文档没有 status 字段，先一律标"草稿"；等导出元数据带上 status 再细化
      status: "草稿" as Status,
      path: d.path,
    }));
  } catch {
    /* 静默失败 — fallback 顶住 */
  } finally {
    loaded.value = true;
  }
});

// 状态映射 —— 图标方块底色 + 状态 chip 配色，对齐 V1 调色板。
function badgeStyle(status: Status) {
  if (status === "已发布")
    return { background: "#dde7d2", color: "#4d6b2f" };
  if (status === "草稿")
    return { background: "var(--yellow-soft)", color: "#7a5400" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-3)" };
}

function pillStyle(status: Status) {
  if (status === "已发布")
    return { background: "#dde7d2", color: "#4d6b2f" };
  if (status === "草稿")
    return { background: "var(--yellow-soft)", color: "#7a5400" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}

function openDoc(_d: Doc) {
  // 示例文档（demo-）就跳到创作区让用户起一篇真的；真文档先也跳创作区，
  // 之后接 ArticleView 的 "open existing" 入口（v2 路线再细化）。
  router.push({ name: "article" });
}
</script>

<template>
  <!--
    h-full + min-h-0 + flex column —— 卡片本体撑满 HomeView 给的
    "剩余空间"（recent 行 flex-1）。内部分两段：标题区固定，列表区
    flex-1 min-h-0 + overflow-y-auto 自己滚。这样最近文档的滚动条
    严格在卡片内，工作台外层不会出现整页滚动条。
  -->
  <section
    class="relative flex h-full min-h-0 flex-col overflow-hidden"
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
          Recent · 文档
        </div>
        <div
          class="font-display mt-1 font-bold"
          :style="{ fontSize: '18px', letterSpacing: '-0.4px' }"
        >
          最近文档
        </div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          近 7 天 · {{ docs.length }} 篇
        </div>
      </div>
      <!--
        「更多」按钮跳转到完整历史页（RecentHistoryView） —— 卡片本身
        只显示最近 10 篇，要看全部 / 清空记录 / 看导出位置都得进去。
        起飞文章入口改去 KeywordHero / LeftNav 上的「创作区」直达，
        不再夹一个「新建」二级入口。
      -->
      <button
        type="button"
        class="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11.5px]"
        :style="{
          background: 'var(--card-2)',
          color: 'var(--ink-2)',
          border: '1px solid var(--line)',
        }"
        @click="router.push({ name: 'recent-history' })"
      >
        更多
        <Icon name="arrowRight" :size="10" />
      </button>
    </div>

    <!--
      文档列表 —— 自适应：默认单列；recent 是整行宽度，xl 视口下
      卡片宽 ≥ 1100px 时切双列，每条最多展示 ~520px 内容空间。
      flex-1 + overflow-y-auto 让超出高度只在卡片内部出现滚动条。
    -->
    <div class="grid min-h-0 flex-1 grid-cols-1 gap-1.5 overflow-y-auto xl:grid-cols-2">
      <div
        v-for="d in docs"
        :key="d.id"
        class="flex cursor-pointer items-center gap-3 rounded-[10px] p-2.5 transition"
        :style="{
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
        }"
        @click="openDoc(d)"
        @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--card-white)')"
        @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--card-2)')"
      >
        <span
          class="inline-flex flex-shrink-0 items-center justify-center"
          :style="{
            width: '28px',
            height: '28px',
            borderRadius: '8px',
            ...badgeStyle(d.status),
          }"
        >
          <Icon name="fileText" :size="12" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12px] font-semibold">{{ d.title }}</div>
          <div
            class="mt-0.5 text-[10.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            {{ d.tpl }} · {{ d.words.toLocaleString() }} 字
          </div>
        </div>
        <span
          class="inline-flex h-5 items-center rounded-full px-2 text-[10.5px] font-medium"
          :style="pillStyle(d.status)"
        >
          {{ d.status }}
        </span>
        <span
          class="flex-shrink-0 text-[10px]"
          :style="{ color: 'var(--ink-4)' }"
          >{{ d.when }}</span
        >
      </div>
    </div>
  </section>
</template>
