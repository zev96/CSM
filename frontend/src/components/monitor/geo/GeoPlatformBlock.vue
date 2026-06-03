<script setup lang="ts">
/**
 * 平台对比卡片 `PlatformBlock`（Notion 风格）—— 移植 design full-app.jsx。
 * 色块头部(状态着色) + 关于「品牌」的原文(摘录，品牌名高亮；未提及红块) +
 * AI 采用的信源(全部，无数量徽章)。masonry 两列由父组件 column-count 布局。
 * 采集失败 → 正文显「本平台本次采集失败」。配色/字号严格照稿。
 */
import { computed } from "vue";

import {
  cellStatus,
  isFailed,
  isPending,
  sentDotColor,
  sentLabel,
  type PlatformVM,
} from "@/components/monitor/geo/geoDetail";

const props = defineProps<{
  platform: PlatformVM;
  brand: string;
  // 品牌名 + 别名 —— 高亮原文 / 「未提及{brand}」用。第一个非空作显示名。
  brandTerms: string[];
}>();

const st = computed(() => cellStatus(props.platform));
const failed = computed(() => isFailed(props.platform));
const pending = computed(() => isPending(props.platform));

// 头部色调：首推=绿、提及=橙、未运行=中性灰、未提及/失败=红。
const tint = computed(() =>
  st.value.kind === "first"
    ? "rgba(122,155,94,.16)"
    : st.value.kind === "hit"
      ? "var(--primary-soft)"
      : st.value.kind === "pending"
        ? "var(--card-2)"
        : "rgba(216,90,72,.12)",
);
const badgeBg = computed(() => (st.value.kind === "first" ? "var(--green)" : "#fff"));
const badgeColor = computed(() => (st.value.kind === "first" ? "#fff" : st.value.color));
const badgeBorder = computed(() =>
  st.value.kind === "first" ? "none" : `1px solid ${st.value.color}33`,
);

const displayBrand = computed(
  () => props.brandTerms.find((t) => t && t.trim()) ?? props.brand ?? "",
);

// 高亮原文里的品牌名（+别名）。把摘录按所有 brandTerms 切分，命中段渲染 primary-deep 粗体。
interface Seg {
  text: string;
  hl: boolean;
}
const excerptSegs = computed<Seg[]>(() => {
  const text = props.platform.excerpt || "";
  const terms = props.brandTerms.map((t) => t.trim()).filter(Boolean);
  if (!terms.length) return [{ text, hl: false }];
  // 转义正则特殊字符，按 | 拼成一个匹配组，长词优先（避免别名是品牌名子串时短匹配抢先）。
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = terms
    .slice()
    .sort((a, b) => b.length - a.length)
    .map(esc)
    .join("|");
  const re = new RegExp(`(${pattern})`, "g");
  const out: Seg[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), hl: false });
    out.push({ text: m[0], hl: true });
    last = m.index + m[0].length;
    if (m.index === re.lastIndex) re.lastIndex++; // 防零宽死循环
  }
  if (last < text.length) out.push({ text: text.slice(last), hl: false });
  return out.length ? out : [{ text, hl: false }];
});
</script>

<template>
  <div
    :style="{ breakInside: 'avoid', marginBottom: '14px', border: '1px solid var(--line)', borderRadius: '16px', overflow: 'hidden', background: 'var(--card)' }"
  >
    <!-- 色块头部 -->
    <div :style="{ padding: '13px 16px 12px', background: tint }">
      <div class="flex items-center justify-between" :style="{ gap: '10px' }">
        <span class="font-display" :style="{ fontSize: '16px', fontWeight: 700 }">{{ platform.name }}</span>
        <span
          class="font-display inline-flex items-center"
          :style="{ padding: '3px 11px', fontSize: '12px', fontWeight: 700, borderRadius: '999px', color: badgeColor, background: badgeBg, border: badgeBorder, fontVariantNumeric: 'tabular-nums' }"
        >{{ st.label }}</span>
      </div>
      <div v-if="!failed && !pending" class="flex items-center" :style="{ gap: '12px', marginTop: '8px' }">
        <span class="inline-flex items-center" :style="{ gap: '5px' }">
          <span :style="{ width: '8px', height: '8px', borderRadius: '999px', background: sentDotColor(platform.sentiment), display: 'inline-block', flexShrink: 0 }" />
          <span :style="{ fontSize: '11.5px', color: 'var(--ink-2)' }">口碑{{ sentLabel(platform.sentiment) }}</span>
        </span>
        <span :style="{ fontSize: '11.5px', color: 'var(--ink-3)' }">信源 {{ platform.cites.length }}</span>
      </div>
    </div>

    <!-- 正文 -->
    <div
      v-if="pending"
      class="flex items-center"
      :style="{ padding: '14px 16px', fontSize: '12px', color: 'var(--ink-3)', gap: '7px' }"
    >
      <span :style="{ width: '6px', height: '6px', borderRadius: '999px', background: 'var(--ink-4)' }" />
      该平台本次未运行 · 运行一次后这里显示原文与信源。
    </div>
    <div
      v-else-if="failed"
      class="flex items-center"
      :style="{ padding: '14px 16px', fontSize: '12px', color: 'var(--ink-3)', gap: '7px' }"
    >
      <span :style="{ width: '6px', height: '6px', borderRadius: '999px', background: 'var(--red)' }" />
      本平台本次采集失败，未取到结果。
    </div>
    <div v-else :style="{ padding: '13px 16px 15px' }">
      <!-- 关于品牌的原文 -->
      <div :style="{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: '7px' }">关于「{{ displayBrand }}」的原文</div>
      <div
        v-if="platform.excerpt"
        :style="{ fontSize: '12.5px', lineHeight: 1.7, color: 'var(--ink-2)', display: '-webkit-box', WebkitLineClamp: 8, WebkitBoxOrient: 'vertical', overflow: 'hidden' }"
      >
        <template v-for="(seg, i) in excerptSegs" :key="i">
          <b v-if="seg.hl" :style="{ color: 'var(--primary-deep)' }">{{ seg.text }}</b>
          <template v-else>{{ seg.text }}</template>
        </template>
      </div>
      <div
        v-else
        class="inline-flex items-center"
        :style="{ gap: '7px', fontSize: '12px', color: 'var(--red)', background: 'rgba(216,90,72,.08)', borderRadius: '8px', padding: '7px 10px' }"
      >
        <span :style="{ width: '6px', height: '6px', borderRadius: '999px', background: 'var(--red)' }" />
        本次回答未提及{{ displayBrand }}
      </div>

      <!-- 信源 -->
      <div :style="{ height: '1px', background: 'var(--line)', margin: '13px 0 11px' }" />
      <div :style="{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: '8px' }">AI 采用的信源</div>
      <div
        v-if="platform.cites.length === 0"
        :style="{ fontSize: '11.5px', color: 'var(--ink-3)' }"
      >这次回答未引用可识别的来源。</div>
      <div v-else class="flex flex-col" :style="{ gap: '7px', maxHeight: '160px', overflowY: 'auto', paddingRight: '4px' }">
        <a
          v-for="(c, i) in platform.cites"
          :key="i"
          :href="c.url || undefined"
          target="_blank"
          rel="noopener noreferrer"
          class="flex items-center"
          :style="{ gap: '8px', minWidth: 0, textDecoration: 'none' }"
        >
          <span :style="{ fontSize: '12px', fontWeight: 600, flexShrink: 0, color: 'var(--ink)' }">{{ c.domain }}</span>
          <span
            class="truncate"
            :style="{ fontSize: '11px', color: 'var(--ink-3)' }"
            :title="c.title"
          >{{ c.title }}</span>
        </a>
      </div>
    </div>
  </div>
</template>
