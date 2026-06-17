<script setup lang="ts">
/**
 * 手机预览（设计稿 §4.3）—— 纯 computed 渲染，不做 DOM 转图（导出=复制文案）。
 * 笔记页 / 发现页两 tab。封面真实图在 P2 接；发现页瀑布流模拟 feed 在 P3 验收补。
 *
 * 设备外框用「宽度驱动的固定比例」(aspect-ratio) 锁形，避免随窗口高度被拉伸：
 * 舞台居中可滚 → 外框 max-width + aspect-ratio 定形 → 屏幕内部独立滚动内容。
 */
import { computed } from "vue";
import { useXhs } from "@/stores/xhs";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";

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

// 正文按行渲染（white-space: pre-wrap 保留换行与缩进 + emoji）。
const displayTitle = computed(() => xhs.title || "添加标题更吸睛～");
const displayBody = computed(() => xhs.body || "正文还没写哦，左侧素材点一点，右侧实时预览～");
const tags = computed(() => xhs.topics.filter((t) => t.trim()));

// ── 发现页：模拟 feed ──────────────────────────────────────────────────────
// 内置仿造图文（自撰、纯 Unicode + 渐变封面，不打包任何站点图片），用于把用户
// 自己的笔记放进一个像样的瀑布流里预览效果。封面用不同 aspectRatio 制造错落感。
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
  { title: "一眼万年的「梦中情店」✨", author: "米米子", likes: "487", emoji: "🏠", grad: "linear-gradient(135deg,#d6f5e3,#cdefe0)", ratio: "3 / 5" },
  { title: "新手化妆必备清单｜照着买不踩雷", author: "小C同学", likes: "137", emoji: "💄", grad: "linear-gradient(135deg,#ffd9e6,#ffc6dd)", ratio: "4 / 5" },
  { title: "周末去哪儿｜城市漫步路线分享", author: "阿七", likes: "92", emoji: "🌿", grad: "linear-gradient(135deg,#e3f0d9,#d3ead0)", ratio: "3 / 4" },
  { title: "打工人快充包｜通勤好物一次买齐", author: "数码小张", likes: "63", emoji: "🎒", grad: "linear-gradient(135deg,#dfe4ff,#cdd6ff)", ratio: "1 / 1" },
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
          fontSize: '12px',
          padding: '4px 12px',
          borderRadius: '999px',
          border: '1px solid var(--line-2)',
          cursor: 'pointer',
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
      <!-- 设备外框：宽度驱动 + 固定比例 → 任何窗口尺寸都不拉伸 -->
      <div class="phone-frame">
        <!-- 屏幕：内容在此独立滚动 -->
        <div class="phone-screen">
          <!-- ── 笔记页 ── -->
          <div v-if="xhs.previewTab === 'note'" :style="{ paddingBottom: '12px' }">
            <!-- 封面：有图显示真实封面，无图占位 -->
            <img
              v-if="coverUrl"
              class="xhs-cover-img"
              :src="coverUrl"
              :style="{ width: '100%', aspectRatio: '3 / 4', objectFit: 'cover', display: 'block', borderRadius: '14px 14px 0 0' }"
            />
            <div
              v-else
              :style="{
                width: '100%', aspectRatio: '3 / 4',
                background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'var(--primary)', fontSize: '13px', borderRadius: '14px 14px 0 0',
              }"
            >
              暂无封面（左侧「图片」上传）
            </div>
            <div :style="{ padding: '12px 14px' }">
              <!-- 作者条 -->
              <div class="flex items-center" :style="{ gap: '8px', marginBottom: '8px' }">
                <div
                  :style="{
                    width: '28px', height: '28px', borderRadius: '999px',
                    background: 'var(--dark)', color: 'var(--primary)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '12px', fontWeight: 700, flexShrink: 0,
                  }"
                >{{ avatarLetter }}</div>
                <span :style="{ fontSize: '13px', color: 'var(--ink)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ nickname }}</span>
                <span :style="{ fontSize: '12px', color: '#fff', background: '#ff2e4d', padding: '3px 12px', borderRadius: '999px', flexShrink: 0 }">关注</span>
              </div>
              <!-- 标题 -->
              <div
                :style="{
                  fontSize: '16px', fontWeight: 700, lineHeight: 1.4, marginBottom: '6px',
                  color: xhs.title ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }"
              >{{ displayTitle }}</div>
              <!-- 正文 -->
              <div
                :style="{
                  fontSize: '14px', lineHeight: 1.7,
                  color: xhs.body ? 'var(--ink)' : '#bbb',
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }"
              >{{ displayBody }}</div>
              <!-- 话题 -->
              <div v-if="tags.length" :style="{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px 8px' }">
                <span v-for="(t, i) in tags" :key="i" :style="{ fontSize: '14px', color: '#3a6fb0' }">#{{ t }}</span>
              </div>
              <!-- 假互动栏 -->
              <div class="flex items-center" :style="{ gap: '16px', marginTop: '12px', color: 'var(--ink-2)', fontSize: '12px' }">
                <span>♡ 1.2k</span><span>☆ 328</span><span>💬 56</span>
              </div>
            </div>
          </div>

          <!-- ── 发现页：双列瀑布流模拟 feed，自己的笔记混在其中 ── -->
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
                <!-- 封面：自己的卡有图用真实封面，其余用渐变 + emoji 占位 -->
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
                    <span class="discover-avatar">{{ card.avatar }}</span>
                    <span class="discover-name">{{ card.author }}</span>
                    <span class="discover-likes">♡ {{ card.likes }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── 设备外框：宽度驱动 + 固定比例，永不拉伸 ── */
.phone-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  overflow-y: auto;
  padding: 2px 0 8px;
}
.phone-frame {
  width: 100%;
  max-width: 280px;
  aspect-ratio: 9 / 19.5; /* 现代手机比例：高度由宽度推导，比例恒定 */
  flex-shrink: 0;         /* 窗口矮时不被压扁，改由 .phone-stage 滚动 */
  border: 8px solid var(--dark);
  border-radius: 28px;
  background: #fff;
  box-shadow: 0 12px 30px -10px rgba(var(--shadow-rgb), 0.25);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.phone-screen {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: #fff;
}

/* ── 发现页瀑布流 ── */
.discover {
  padding: 8px 8px 12px;
}
.discover-tabs {
  display: flex;
  justify-content: center;
  gap: 16px;
  font-size: 12px;
  color: var(--ink-2);
  padding: 2px 0 10px;
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
  column-count: 2;
  column-gap: 8px;
}
.discover-card {
  position: relative;
  break-inside: avoid;
  margin-bottom: 8px;
  border-radius: 10px;
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
  top: 6px;
  left: 6px;
  z-index: 1;
  font-size: 10px;
  line-height: 1;
  color: #fff;
  background: var(--primary);
  padding: 3px 6px;
  border-radius: 6px;
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
  font-size: 30px;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.08));
}
.discover-meta {
  padding: 7px 8px 9px;
}
.discover-title {
  font-size: 12px;
  line-height: 1.4;
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
  gap: 5px;
  margin-top: 7px;
}
.discover-avatar {
  width: 15px;
  height: 15px;
  border-radius: 999px;
  background: var(--dark);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-weight: 700;
  flex-shrink: 0;
}
.discover-name {
  font-size: 11px;
  color: var(--ink-2);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.discover-likes {
  font-size: 11px;
  color: var(--ink-2);
  flex-shrink: 0;
}
</style>
