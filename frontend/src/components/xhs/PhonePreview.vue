<script setup lang="ts">
/**
 * 手机预览（设计稿 §4.3）—— 纯 computed 渲染，不做 DOM 转图（导出=复制文案）。
 * 笔记页 / 发现页两 tab。
 *
 * 设备外框用真实 iPhone mockup 图（已裁掉留白，比例 866:1732≈1:2）：图作底层、
 * 内容绝对定位铺在屏幕白区（内边距按 PNG 实测）。外框宽度驱动 + aspect-ratio
 * 锁形 → 任何窗口尺寸都不拉伸。
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

// ── 发现页：模拟 feed（参考小红书发现页）──────────────────────────────────
// 内置仿造图文（自撰、纯 Unicode + 渐变封面，不打包任何站点图片）+ 用户自己的
// 笔记，共 4 张铺满一屏、不滚动。封面用不同 aspectRatio 制造瀑布流错落感。
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
}

const MOCK_CARDS: Omit<FeedCard, "mine" | "avatar" | "cover">[] = [
  { title: "绝绝子！这个手机支架也太好用了吧", author: "吃西瓜吧", likes: "220", emoji: "📱", grad: "linear-gradient(135deg,#cfe3ff,#e7d3ff)", ratio: "3 / 4" },
  { title: "探店｜Ins风咖啡店，专门招待懂咖啡的人", author: "Bella十三", likes: "18", emoji: "☕", grad: "linear-gradient(135deg,#ffe7c2,#ffd0a8)", ratio: "1 / 1" },
  { title: "一眼万年的「梦中情店」✨", author: "米米子", likes: "487", emoji: "🏠", grad: "linear-gradient(135deg,#d6f5e3,#cdefe0)", ratio: "3 / 4" },
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
    ratio: "1 / 1",
    cover: coverUrl.value,
  };
  const others: FeedCard[] = MOCK_CARDS.map((c) => ({
    ...c,
    mine: false,
    avatar: c.author.slice(0, 1).toUpperCase(),
    cover: null,
  }));
  // 把自己的笔记插到第 2 位（首屏可见、又不显得刻意置顶）。共 4 张。
  others.splice(1, 0, mine);
  return others;
});

const NAV = ["首页", "购物", "+", "消息", "我"];
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
    <div class="phone-stage">
      <!-- 设备：真机外框图（底层）+ 屏幕内容（铺在白区）。宽度驱动 + 固定比例 → 不拉伸 -->
      <div class="device">
        <img class="device-png" :src="phoneFrame" alt="手机预览外框" />
        <div class="screen">
          <!-- ── 笔记页（内容可滚动）── -->
          <div v-if="xhs.previewTab === 'note'" class="screen-scroll">
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
            <div :style="{ padding: '12px 12px 16px' }">
              <!-- 作者条 -->
              <div class="flex items-center" :style="{ gap: '8px', marginBottom: '8px' }">
                <div class="mini-avatar" :style="{ width: '26px', height: '26px', fontSize: '11px' }">{{ avatarLetter }}</div>
                <span :style="{ fontSize: '13px', color: 'var(--ink)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ nickname }}</span>
                <span :style="{ fontSize: '12px', color: '#fff', background: '#ff2e4d', padding: '3px 12px', borderRadius: '999px', flexShrink: 0 }">关注</span>
              </div>
              <!-- 标题 -->
              <div :style="{ fontSize: '15px', fontWeight: 700, lineHeight: 1.4, marginBottom: '6px', color: xhs.title ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">{{ displayTitle }}</div>
              <!-- 正文 -->
              <div :style="{ fontSize: '13px', lineHeight: 1.7, color: xhs.body ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">{{ displayBody }}</div>
              <!-- 话题 -->
              <div v-if="tags.length" :style="{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px 8px' }">
                <span v-for="(t, i) in tags" :key="i" :style="{ fontSize: '13px', color: '#3a6fb0' }">#{{ t }}</span>
              </div>
              <!-- 假互动栏 -->
              <div class="flex items-center" :style="{ gap: '16px', marginTop: '12px', color: 'var(--ink-2)', fontSize: '12px' }">
                <span>♡ 1.2k</span><span>☆ 328</span><span>💬 56</span>
              </div>
            </div>
          </div>

          <!-- ── 发现页（4 张卡铺满一屏，不滚动；底部导航）── -->
          <div v-else class="discover">
            <div class="discover-tabs">
              <span>关注</span><span class="discover-tab-active">发现</span><span>本地</span>
            </div>
            <div class="discover-feed">
              <div
                v-for="(card, i) in feedCards"
                :key="i"
                class="discover-card"
                :class="{ 'discover-mine': card.mine }"
              >
                <span v-if="card.mine" class="discover-badge">我的</span>
                <img
                  v-if="card.mine && card.cover"
                  class="xhs-cover-img discover-cover"
                  :src="card.cover"
                  :style="{ aspectRatio: card.ratio }"
                />
                <div
                  v-else
                  class="discover-cover discover-cover-ph"
                  :style="{ aspectRatio: card.ratio, background: card.grad }"
                >
                  <span class="discover-emoji">{{ card.emoji }}</span>
                </div>
                <div class="discover-meta">
                  <div class="discover-title" :class="{ 'discover-title-empty': card.mine && !xhs.title }">{{ card.title }}</div>
                  <div class="discover-author">
                    <span class="mini-avatar discover-avatar">{{ card.avatar }}</span>
                    <span class="discover-name">{{ card.author }}</span>
                    <span class="discover-likes">♡ {{ card.likes }}</span>
                  </div>
                </div>
              </div>
            </div>
            <!-- 底部导航条（仿小红书） -->
            <div class="discover-nav">
              <span
                v-for="(n, i) in NAV"
                :key="i"
                class="discover-nav-item"
                :class="{ 'discover-nav-home': i === 0, 'discover-nav-plus': n === '+' }"
              >{{ n }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
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
  aspect-ratio: 866 / 1732; /* 裁剪后真机图比例：高度由宽度推导，恒定不拉伸 */
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
/* 屏幕白区：按 PNG 实测内边距铺内容（top 2.66% / 左右 6.24% / bottom 2.71%） */
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
.screen-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 8px;
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

/* ── 发现页 ── */
.discover {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.discover-tabs {
  display: flex;
  justify-content: center;
  gap: 16px;
  font-size: 12px;
  color: var(--ink-2);
  padding: 8px 0 8px;
  flex-shrink: 0;
}
.discover-tab-active {
  color: var(--ink);
  font-weight: 700;
  position: relative;
}
.discover-tab-active::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -4px;
  transform: translateX(-50%);
  width: 16px;
  height: 2px;
  border-radius: 2px;
  background: var(--primary);
}
.discover-feed {
  flex: 1;
  min-height: 0;
  overflow: hidden; /* 只显示 4 张、不出滚动条 */
  column-count: 2;
  column-gap: 7px;
  padding: 0 7px;
}
.discover-card {
  position: relative;
  break-inside: avoid;
  margin-bottom: 7px;
  border-radius: 9px;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--line-2);
}
.discover-mine {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}
.discover-badge {
  position: absolute;
  top: 5px;
  left: 5px;
  z-index: 1;
  font-size: 9px;
  line-height: 1;
  color: #fff;
  background: var(--primary);
  padding: 3px 5px;
  border-radius: 5px;
  font-weight: 600;
}
.discover-cover {
  width: 100%;
  object-fit: cover;
  display: block;
}
.discover-cover-ph {
  display: flex;
  align-items: center;
  justify-content: center;
}
.discover-emoji {
  font-size: 26px;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.08));
}
.discover-meta {
  padding: 6px 7px 8px;
}
.discover-title {
  font-size: 11px;
  line-height: 1.35;
  font-weight: 600;
  color: var(--ink);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.discover-title-empty {
  color: #bbb;
  font-weight: 400;
}
.discover-author {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
}
.discover-avatar {
  width: 14px;
  height: 14px;
  font-size: 8px;
}
.discover-name {
  font-size: 10px;
  color: var(--ink-2);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.discover-likes {
  font-size: 10px;
  color: var(--ink-2);
  flex-shrink: 0;
}
.discover-nav {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-around;
  border-top: 1px solid var(--line-2);
  padding: 7px 4px calc(7px + env(safe-area-inset-bottom, 0px));
  background: #fff;
}
.discover-nav-item {
  font-size: 11px;
  color: var(--ink-2);
}
.discover-nav-home {
  color: var(--ink);
  font-weight: 700;
}
.discover-nav-plus {
  color: #fff;
  background: var(--primary);
  border-radius: 7px;
  padding: 2px 9px;
  font-size: 14px;
  line-height: 1.2;
}
</style>
