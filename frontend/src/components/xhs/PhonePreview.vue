<script setup lang="ts">
/**
 * 手机预览（设计稿 §4.3）—— 纯 computed 渲染，不做 DOM 转图（导出=复制文案）。
 * 笔记页 / 发现页两 tab，布局对齐真实小红书 App。
 *
 * 设备外框用真实 iPhone mockup 图（已裁掉留白，比例 866:1732≈1:2）：图作底层、
 * 内容绝对定位铺在屏幕白区（内边距按 PNG 实测）。外框宽度驱动 + aspect-ratio
 * 锁形 → 任何窗口尺寸都不拉伸。两页内容区滚动但隐藏滚动条（.no-scrollbar）。
 *
 * 发现页的仿造 feed 封面图为用户自备素材（放 src/assets/xhs-feed），随包打进；
 * 笔记页多图时右上角显示页数、封面下方显示轮播圆点（对齐小红书图集笔记）。
 */
import { computed } from "vue";
import { useXhs } from "@/stores/xhs";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import phoneFrame from "@/assets/xhs-phone-frame.png";
import purifier1 from "@/assets/xhs-feed/purifier1.jpg";
import purifier2 from "@/assets/xhs-feed/purifier2.jpg";
import purifier3 from "@/assets/xhs-feed/purifier3.jpg";
import catfood1 from "@/assets/xhs-feed/catfood1.jpg";
import catfood2 from "@/assets/xhs-feed/catfood2.jpg";
import catfood3 from "@/assets/xhs-feed/catfood3.jpg";
import vacuum1 from "@/assets/xhs-feed/vacuum1.jpg";
import vacuum2 from "@/assets/xhs-feed/vacuum2.jpg";
import vacuum3 from "@/assets/xhs-feed/vacuum3.jpg";
import dogfood1 from "@/assets/xhs-feed/dogfood1.jpg";
import dogfood2 from "@/assets/xhs-feed/dogfood2.jpg";
import dogfood3 from "@/assets/xhs-feed/dogfood3.jpg";

const xhs = useXhs();
const cfg = useConfig();
const sidecar = useSidecar();

const imgCount = computed(() => xhs.imageIds.length);
const hasMulti = computed(() => imgCount.value > 1);
const clampedCover = computed(() => {
  const n = imgCount.value;
  if (n === 0) return 0;
  return xhs.coverIndex >= 0 && xhs.coverIndex < n ? xhs.coverIndex : 0;
});
const coverUrl = computed<string | null>(() => {
  if (!imgCount.value) return null;
  return sidecar.sseURL(`/api/xhs/images/${xhs.imageIds[clampedCover.value]}`);
});

const nickname = computed<string>(() => String(cfg.data?.user_name ?? "") || "我的小红书");
const avatarLetter = computed<string>(() => (nickname.value || "我").slice(0, 1).toUpperCase());

const displayTitle = computed(() => xhs.title || "添加标题更吸睛～");
const displayBody = computed(() => xhs.body || "正文还没写哦，左侧素材点一点，右侧实时预览～");
const tags = computed(() => xhs.topics.filter((t) => t.trim()));

// ── 发现页：模拟 feed（数码/萌宠好物分享，对齐真实小红书发现页）──────────────
// 封面为用户自备图片素材；文案自撰。封面统一裁成 3:4（小红书笔记标准比例），
// 均匀双列网格、隐藏滚动条。用户自己的笔记混在其中（橙框「我的」）。
interface FeedCard {
  mine: boolean;
  title: string;
  author: string;
  avatar: string;
  likes: string;
  cover: string | null;
}

const MOCK_CARDS: Omit<FeedCard, "mine" | "avatar">[] = [
  { title: "除甲醛空气净化器选购指南｜避坑必看", author: "科技博薯", likes: "89", cover: purifier1 },
  { title: "猫粮怎么选？配料表避雷指南", author: "撸猫日常", likes: "421", cover: catfood1 },
  { title: "吸尘器哪款值得买？三款真实横评", author: "数码张", likes: "327", cover: vacuum1 },
  { title: "狗粮红黑榜｜这几款放心囤", author: "狗子饭堂", likes: "509", cover: dogfood1 },
  { title: "新房入住前，这台空气净化器真没白买", author: "暖暖家", likes: "312", cover: purifier2 },
  { title: "主子吃了不软便的猫粮，已回购", author: "三只猫", likes: "88", cover: catfood2 },
  { title: "养宠家庭的吸尘器，吸毛是真的强", author: "毛孩子妈", likes: "175", cover: vacuum2 },
  { title: "幼犬狗粮怎么选？新手养狗必看", author: "柴犬团子", likes: "142", cover: dogfood2 },
  { title: "母婴家庭怎么选空气净化器？一篇讲透", author: "萌妈日记", likes: "156", cover: purifier3 },
  { title: "平价猫粮测评｜学生养猫也能冲", author: "穷养也幸福", likes: "203", cover: catfood3 },
  { title: "无线吸尘器选购｜别再交智商税", author: "居家好物", likes: "64", cover: vacuum3 },
  { title: "天然粮 vs 商品粮，差别真有这么大？", author: "科学养宠", likes: "97", cover: dogfood3 },
];

const feedCards = computed<FeedCard[]>(() => {
  const mine: FeedCard = {
    mine: true,
    title: displayTitle.value,
    author: nickname.value,
    avatar: avatarLetter.value,
    likes: "1.2k",
    cover: coverUrl.value,
  };
  const others: FeedCard[] = MOCK_CARDS.map((c) => ({
    ...c,
    mine: false,
    avatar: c.author.slice(0, 1).toUpperCase(),
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
              <!-- 封面 + 多图页数角标 -->
              <div class="note-cover-wrap">
                <img
                  v-if="coverUrl"
                  class="xhs-cover-img note-cover"
                  :src="coverUrl"
                />
                <div v-else class="note-cover note-cover-ph">暂无封面（左侧「图片」上传）</div>
                <span v-if="hasMulti" class="note-pager">{{ clampedCover + 1 }}/{{ imgCount }}</span>
              </div>
              <!-- 多图轮播圆点（与下方标题留出间距） -->
              <div v-if="hasMulti" class="note-dots">
                <span
                  v-for="n in imgCount"
                  :key="n"
                  class="note-dot"
                  :class="{ 'note-dot-active': n - 1 === clampedCover }"
                />
              </div>
              <div class="note-content">
                <div :style="{ fontSize: '15px', fontWeight: 700, lineHeight: 1.4, marginBottom: '6px', color: xhs.title ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">{{ displayTitle }}</div>
                <div :style="{ fontSize: '13px', lineHeight: 1.7, color: xhs.body ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">{{ displayBody }}</div>
                <div v-if="tags.length" :style="{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px 8px' }">
                  <span v-for="(t, i) in tags" :key="i" :style="{ fontSize: '13px', color: '#3a6fb0' }">#{{ t }}</span>
                </div>
                <div :style="{ marginTop: '12px', fontSize: '11px', color: '#bbb' }">编辑于 刚刚 · 广州</div>
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
            <div class="dc-subtabs no-scrollbar">
              <span
                v-for="(s, i) in SUB_TABS"
                :key="s"
                class="dc-subtab"
                :class="{ 'dc-subtab-active': i === 0 }"
              >{{ s }}</span>
            </div>
            <!-- 瀑布流 feed（均匀双列网格，可滚，隐藏滚动条） -->
            <div class="dc-feed no-scrollbar">
              <div
                v-for="(card, i) in feedCards"
                :key="i"
                class="dc-card"
                :class="{ 'dc-mine': card.mine }"
              >
                <div class="dc-cover-wrap">
                  <img
                    v-if="card.cover"
                    class="dc-cover"
                    :class="{ 'xhs-cover-img': card.mine }"
                    :src="card.cover"
                  />
                  <div v-else class="dc-cover dc-cover-ph"><span class="dc-emoji">📷</span></div>
                  <span v-if="card.mine" class="dc-badge dc-badge-mine">我的</span>
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
.note-cover-wrap {
  position: relative;
  width: 100%;
}
.note-cover {
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  display: block;
}
.note-cover-ph {
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #ffe3d3, #ffd0b5);
  color: var(--primary);
  font-size: 12px;
  text-align: center;
  padding: 0 16px;
}
.note-pager {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 10px;
  line-height: 1;
  color: #fff;
  background: rgba(0, 0, 0, 0.42);
  padding: 3px 7px;
  border-radius: 999px;
}
.note-dots {
  display: flex;
  justify-content: center;
  gap: 4px;
  padding: 9px 0 7px; /* 与下方标题留出间距 */
}
.note-dot {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: rgba(var(--ink-rgb), 0.22);
}
.note-dot-active {
  background: var(--ink-2);
}
.note-content {
  padding: 4px 12px 14px;
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
  font-size: 11px;
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
  font-size: 10px;
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
  display: grid;
  grid-template-columns: 1fr 1fr; /* 平均双列网格 */
  gap: 7px;
  align-content: start;
  padding: 2px 7px 6px;
}
.dc-card {
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
  aspect-ratio: 3 / 4; /* 统一小红书笔记封面比例 */
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
  background: linear-gradient(135deg, #ffe3d3, #ffd0b5);
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
.dc-meta {
  padding: 6px 7px 8px;
}
.dc-title {
  font-size: 10px;
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
  font-size: 9px;
  color: var(--ink-2);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dc-likes {
  font-size: 9px;
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
