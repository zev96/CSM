<script setup lang="ts">
/**
 * 手机预览（设计稿 §4.3）—— 纯 computed 渲染，不做 DOM 转图（导出=复制文案）。
 * 笔记页 / 发现页两 tab，布局对齐真实小红书 App。
 *
 * 设备外框用真实 iPhone mockup 图（已裁掉留白，比例 866:1732≈1:2）：图作底层、
 * 内容绝对定位铺在屏幕白区（内边距按 PNG 实测）。外框宽度驱动 + aspect-ratio
 * 锁形 → 任何窗口尺寸都不拉伸。两页内容区滚动但隐藏滚动条（.no-scrollbar）。
 */
import { computed } from "vue";
import { useXhs } from "@/stores/xhs";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import phoneFrame from "@/assets/xhs-phone-frame.png";

const xhs = useXhs();
const cfg = useConfig();
const sidecar = useSidecar();

const coverUrl = computed<string | null>(() => {
  if (!xhs.imageIds.length) return null;
  const idx = xhs.coverIndex >= 0 && xhs.coverIndex < xhs.imageIds.length ? xhs.coverIndex : 0;
  return sidecar.sseURL(`/api/xhs/images/${xhs.imageIds[idx]}`);
});

const nickname = computed<string>(() => String(cfg.data?.user_name ?? "") || "我的小红书");
const avatarLetter = computed<string>(() => (nickname.value || "我").slice(0, 1).toUpperCase());

const displayTitle = computed(() => xhs.title || "添加标题更吸睛～");
const displayBody = computed(() => xhs.body || "正文还没写哦，左侧素材点一点，右侧实时预览～");
const tags = computed(() => xhs.topics.filter((t) => t.trim()));

// ── 发现页：模拟 feed（对齐真实小红书发现页）────────────────────────────────
// 内置仿造图文（自撰、纯 Unicode + 渐变封面，不打包任何站点图片）+ 用户自己的
// 笔记。瀑布流双列、隐藏滚动条。封面用不同 aspectRatio 制造错落感。
interface FeedCard {
  mine: boolean;
  title: string;
  author: string;
  avatar: string;
  likes: string;
  emoji: string;
  grad: string;
  ratio: string;
  cover: string | null;
  badge?: string;
  video?: boolean;
}

const MOCK_CARDS: Omit<FeedCard, "mine" | "avatar" | "cover">[] = [
  { title: "梅开二度！这场也太燃了⚽", author: "体育君", likes: "2021万", emoji: "⚽", grad: "linear-gradient(135deg,#bfe0ff,#a9d3ff)", ratio: "4 / 5", badge: "热点", video: true },
  { title: "同居后才发现的 5 个真相", author: "旺旺饼干", likes: "1908", emoji: "🏠", grad: "linear-gradient(135deg,#fdf3da,#f7e9c8)", ratio: "1 / 1" },
  { title: "美版 vs 国行，差价 1000 怎么选", author: "数码张", likes: "327", emoji: "💻", grad: "linear-gradient(135deg,#dfe4ff,#cdd6ff)", ratio: "3 / 4", video: true },
  { title: "Ins风咖啡店探店｜氛围感拉满", author: "Bella十三", likes: "18", emoji: "☕", grad: "linear-gradient(135deg,#ffe7c2,#ffd0a8)", ratio: "1 / 1" },
  { title: "梨形身材显瘦穿搭公式", author: "小裙子", likes: "642", emoji: "👗", grad: "linear-gradient(135deg,#ffd9e6,#ffc6dd)", ratio: "3 / 4" },
];

const feedCards = computed<FeedCard[]>(() => {
  const mine: FeedCard = {
    mine: true,
    title: displayTitle.value,
    author: nickname.value,
    avatar: avatarLetter.value,
    likes: "1.2k",
    emoji: "📷",
    grad: "linear-gradient(135deg, #ffe3d3, #ffd0b5)",
    ratio: "3 / 4",
    cover: coverUrl.value,
  };
  const others: FeedCard[] = MOCK_CARDS.map((c) => ({
    ...c,
    mine: false,
    avatar: c.author.slice(0, 1).toUpperCase(),
    cover: null,
  }));
  // 把自己的笔记插到第 2 位（首屏可见、又不显得刻意置顶）。
  others.splice(1, 0, mine);
  return others;
});

const DISCOVER_TABS = ["关注", "发现", "世界杯", "广州"];
const SUB_TABS = ["推荐", "RED", "直播", "短剧", "问答", "穿搭"];
const NAV = ["首页", "市集", "+", "消息", "我"];
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <!-- tab 切换 -->
    <div class="flex items-center justify-center" :style="{ gap: '6px', flexShrink: 0 }">
      <button
        v-for="t in (['note', 'discover'] as const)"
        :key="t"
        type="button"
        :style="{
          fontSize: '12px', padding: '4px 12px', borderRadius: '999px',
          border: '1px solid var(--line-2)', cursor: 'pointer',
          background: xhs.previewTab === t ? 'var(--primary)' : 'transparent',
          color: xhs.previewTab === t ? '#fff' : 'var(--ink-2)',
        }"
        @click="xhs.setPreviewTab(t)"
      >
        {{ t === 'note' ? '笔记页' : '发现页' }}
      </button>
    </div>

    <!-- 舞台：居中、可滚（窗口很矮时滚动看全机身），杜绝设备被拉伸 -->
    <div class="phone-stage no-scrollbar">
      <!-- 设备：真机外框图（底层）+ 屏幕内容（铺在白区）。宽度驱动 + 固定比例 → 不拉伸 -->
      <div class="device">
        <img class="device-png" :src="phoneFrame" alt="手机预览外框" />
        <div class="screen">
          <!-- ══ 笔记页 ══ -->
          <template v-if="xhs.previewTab === 'note'">
            <!-- 顶部导航：返回 / 作者 / 关注 / 分享 -->
            <div class="note-nav">
              <span class="note-nav-back">❮</span>
              <span class="mini-avatar" :style="{ width: '24px', height: '24px', fontSize: '11px' }">{{ avatarLetter }}</span>
              <span class="note-nav-name">{{ nickname }}</span>
              <span class="note-follow">关注</span>
              <span class="note-nav-share">↗</span>
            </div>
            <!-- 内容（可滚，隐藏滚动条） -->
            <div class="note-body no-scrollbar">
              <img
                v-if="coverUrl"
                class="xhs-cover-img"
                :src="coverUrl"
                :style="{ width: '100%', aspectRatio: '3 / 4', objectFit: 'cover', display: 'block' }"
              />
              <div
                v-else
                :style="{
                  width: '100%', aspectRatio: '3 / 4',
                  background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'var(--primary)', fontSize: '12px', textAlign: 'center', padding: '0 16px',
                }"
              >暂无封面（左侧「图片」上传）</div>
              <div :style="{ padding: '11px 12px 14px' }">
                <div :style="{ fontSize: '15px', fontWeight: 700, lineHeight: 1.4, marginBottom: '6px', color: xhs.title ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">{{ displayTitle }}</div>
                <div :style="{ fontSize: '13px', lineHeight: 1.7, color: xhs.body ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">{{ displayBody }}</div>
                <div v-if="tags.length" :style="{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px 8px' }">
                  <span v-for="(t, i) in tags" :key="i" :style="{ fontSize: '13px', color: '#3a6fb0' }">#{{ t }}</span>
                </div>
                <div :style="{ marginTop: '12px', fontSize: '11px', color: 'var(--ink-3, #bbb)' }">编辑于 刚刚 · 广州</div>
              </div>
            </div>
            <!-- 底部操作栏：评论框 + 点赞/收藏/评论 计数 -->
            <div class="note-actionbar">
              <span class="note-comment-input">✏️ 说点什么...</span>
              <span class="note-stat">♡ 5322</span>
              <span class="note-stat">☆ 705</span>
              <span class="note-stat">💬 1171</span>
            </div>
          </template>

          <!-- ══ 发现页 ══ -->
          <template v-else>
            <!-- 顶部 tab 条 -->
            <div class="dc-topbar">
              <span class="dc-icon">💬</span>
              <div class="dc-tabs">
                <span
                  v-for="(t, i) in DISCOVER_TABS"
                  :key="t"
                  class="dc-tab"
                  :class="{ 'dc-tab-active': t === '发现' }"
                >{{ t }}<sup v-if="i === 0" class="dc-tab-dot">8</sup></span>
              </div>
              <span class="dc-icon">🔍</span>
            </div>
            <!-- 子分类条 -->
            <div class="dc-subtabs no-scrollbar">
              <span
                v-for="(s, i) in SUB_TABS"
                :key="s"
                class="dc-subtab"
                :class="{ 'dc-subtab-active': i === 0 }"
              >{{ s }}</span>
            </div>
            <!-- 瀑布流 feed（可滚，隐藏滚动条） -->
            <div class="dc-feed no-scrollbar">
              <div
                v-for="(card, i) in feedCards"
                :key="i"
                class="dc-card"
                :class="{ 'dc-mine': card.mine }"
              >
                <div class="dc-cover-wrap" :style="{ aspectRatio: card.ratio }">
                  <img
                    v-if="card.mine && card.cover"
                    class="xhs-cover-img dc-cover"
                    :src="card.cover"
                  />
                  <div v-else class="dc-cover dc-cover-ph" :style="{ background: card.grad }">
                    <span class="dc-emoji">{{ card.emoji }}</span>
                  </div>
                  <span v-if="card.mine" class="dc-badge dc-badge-mine">我的</span>
                  <span v-else-if="card.badge" class="dc-badge dc-badge-hot">{{ card.badge }}</span>
                  <span v-if="card.video" class="dc-play">▶</span>
                </div>
                <div class="dc-meta">
                  <div class="dc-title" :class="{ 'dc-title-empty': card.mine && !xhs.title }">{{ card.title }}</div>
                  <div class="dc-author">
                    <span class="mini-avatar dc-avatar">{{ card.avatar }}</span>
                    <span class="dc-name">{{ card.author }}</span>
                    <span class="dc-likes">♡ {{ card.likes }}</span>
                  </div>
                </div>
              </div>
            </div>
            <!-- 底部导航条 -->
            <div class="dc-nav">
              <span
                v-for="(n, i) in NAV"
                :key="i"
                class="dc-nav-item"
                :class="{ 'dc-nav-home': i === 0, 'dc-nav-plus': n === '+' }"
              >{{ n }}</span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 隐藏滚动条但保留滚动能力 */
.no-scrollbar {
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.no-scrollbar::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

/* ── 设备外框：真机图 + 宽度驱动固定比例，永不拉伸 ── */
.phone-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  overflow-y: auto;
  padding: 2px 0 8px;
}
.device {
  position: relative;
  width: 100%;
  max-width: 262px;
  aspect-ratio: 866 / 1732;
  flex-shrink: 0;
}
.device-png {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
  user-select: none;
  z-index: 0;
}
.screen {
  position: absolute;
  top: 2.66%;
  left: 6.24%;
  right: 6.24%;
  bottom: 2.71%;
  z-index: 1;
  background: #fff;
  border-radius: 24px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.mini-avatar {
  border-radius: 999px;
  background: var(--dark);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex-shrink: 0;
}

/* ── 笔记页 ── */
.note-nav {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 10px;
  border-bottom: 1px solid var(--line-2);
}
.note-nav-back {
  font-size: 16px;
  color: var(--ink);
  flex-shrink: 0;
}
.note-nav-name {
  font-size: 12px;
  color: var(--ink);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note-follow {
  flex-shrink: 0;
  font-size: 11px;
  color: #ff2e4d;
  border: 1px solid #ff2e4d;
  border-radius: 999px;
  padding: 2px 12px;
}
.note-nav-share {
  flex-shrink: 0;
  font-size: 15px;
  color: var(--ink-2);
}
.note-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.note-actionbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px calc(8px + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid var(--line-2);
  background: #fff;
}
.note-comment-input {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: var(--ink-2);
  background: rgba(var(--ink-rgb), 0.05);
  border-radius: 999px;
  padding: 5px 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note-stat {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--ink-2);
}

/* ── 发现页 ── */
.dc-topbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px 4px;
}
.dc-icon {
  font-size: 13px;
  flex-shrink: 0;
}
.dc-tabs {
  flex: 1;
  display: flex;
  justify-content: center;
  gap: 11px;
}
.dc-tab {
  position: relative;
  font-size: 12px;
  color: var(--ink-2);
}
.dc-tab-active {
  color: var(--ink);
  font-weight: 700;
}
.dc-tab-active::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -3px;
  transform: translateX(-50%);
  width: 14px;
  height: 2px;
  border-radius: 2px;
  background: #ff2e4d;
}
.dc-tab-dot {
  font-size: 8px;
  color: #fff;
  background: #ff2e4d;
  border-radius: 999px;
  padding: 0 3px;
  margin-left: 1px;
}
.dc-subtabs {
  flex-shrink: 0;
  display: flex;
  gap: 12px;
  padding: 6px 10px 8px;
  overflow-x: auto;
}
.dc-subtab {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--ink-2);
}
.dc-subtab-active {
  color: var(--ink);
  font-weight: 700;
}
.dc-feed {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  column-count: 2;
  column-gap: 7px;
  padding: 2px 7px 6px;
}
.dc-card {
  break-inside: avoid;
  margin-bottom: 7px;
  border-radius: 9px;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--line-2);
}
.dc-mine {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}
.dc-cover-wrap {
  position: relative;
  width: 100%;
}
.dc-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.dc-cover-ph {
  display: flex;
  align-items: center;
  justify-content: center;
}
.dc-emoji {
  font-size: 26px;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.08));
}
.dc-badge {
  position: absolute;
  top: 5px;
  left: 5px;
  font-size: 9px;
  line-height: 1;
  color: #fff;
  padding: 3px 5px;
  border-radius: 5px;
  font-weight: 600;
}
.dc-badge-mine {
  background: var(--primary);
}
.dc-badge-hot {
  background: rgba(0, 0, 0, 0.45);
}
.dc-play {
  position: absolute;
  right: 6px;
  bottom: 6px;
  font-size: 9px;
  color: #fff;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5));
}
.dc-meta {
  padding: 6px 7px 8px;
}
.dc-title {
  font-size: 11px;
  line-height: 1.35;
  font-weight: 600;
  color: var(--ink);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.dc-title-empty {
  color: #bbb;
  font-weight: 400;
}
.dc-author {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
}
.dc-avatar {
  width: 14px;
  height: 14px;
  font-size: 8px;
}
.dc-name {
  font-size: 10px;
  color: var(--ink-2);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dc-likes {
  font-size: 10px;
  color: var(--ink-2);
  flex-shrink: 0;
}
.dc-nav {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-around;
  border-top: 1px solid var(--line-2);
  padding: 7px 4px calc(7px + env(safe-area-inset-bottom, 0px));
  background: #fff;
}
.dc-nav-item {
  font-size: 11px;
  color: var(--ink-2);
}
.dc-nav-home {
  color: var(--ink);
  font-weight: 700;
}
.dc-nav-plus {
  color: #fff;
  background: #ff2e4d;
  border-radius: 7px;
  padding: 2px 9px;
  font-size: 14px;
  line-height: 1.2;
}
</style>
