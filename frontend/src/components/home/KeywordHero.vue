<script setup lang="ts">
/**
 * 工作台首页的 hero 卡片 — 严格按 CSM-RE1（V1）/src/screens/home.jsx
 * 中的 HERO 区域复刻：
 *   - Card soft（--card-2 底）
 *   - 两个模糊 blob 装饰（黄 #f5c042 / 橙 #ee6a2a）
 *   - 标题区
 *   - 一体胶囊输入条：放大镜 + input + 黑色「开始生成」按钮
 *   - 模板 / 风格 chip 行（可点选）
 *   - 4 个快捷卡片（粘贴洗稿 / 模板库 / 监测 / Skill）
 *
 * 模板和 Skill 走 /api/templates 与 /api/skills；如果用户还没有任何
 * 模板（新装机），就退回到本组件里写死的占位示例，UI 不会塌掉。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

interface Chip {
  id: string;
  name: string;
}

// Fallback 占位 chip — 在 sidecar 还没起或者用户没建模板/Skill 时用，
// 这样 UI 始终有 3 个模板 + 3 个风格可选，跟设计稿对齐。
const FALLBACK_TEMPLATES: Chip[] = [
  { id: "_demo_t1", name: "导购 · 场景人群" },
  { id: "_demo_t2", name: "导购 · 科普物品" },
  { id: "_demo_t3", name: "测评 · 长期使用" },
];
const FALLBACK_SKILLS: Chip[] = [
  { id: "_demo_s1", name: "克制 · 克制" },
  { id: "_demo_s2", name: "测评 · 真心话" },
  { id: "_demo_s3", name: "母婴 · 温柔" },
];

const router = useRouter();
const sidecar = useSidecar();
const { whenReady } = useSidecarReady();

const keyword = ref("");
const templates = ref<Chip[]>(FALLBACK_TEMPLATES);
const skills = ref<Chip[]>(FALLBACK_SKILLS);
const tplId = ref<string>(FALLBACK_TEMPLATES[0].id);
const skillId = ref<string>(FALLBACK_SKILLS[0].id);

// 设计稿固定取前 3 项展示，避免 chip 把卡片撑爆。
const tplChips = computed(() => templates.value.slice(0, 3));
const skillChips = computed(() => skills.value.slice(0, 3));

onMounted(async () => {
  try {
    await whenReady();
    const [tplResp, skillResp] = await Promise.all([
      sidecar.client.get("/api/templates"),
      sidecar.client.get("/api/skills"),
    ]);
    const tpls: Chip[] = tplResp.data?.templates ?? [];
    const sks: Chip[] = skillResp.data?.skills ?? [];
    if (tpls.length > 0) {
      templates.value = tpls;
      tplId.value = tpls[0].id;
    }
    if (sks.length > 0) {
      skills.value = sks;
      skillId.value = sks[0].id;
    }
  } catch {
    /* 静默失败 — 占位 chip 保持显示 */
  }
});

function takeoff() {
  if (!keyword.value.trim()) return;
  // 用 _demo_ 前缀的占位 id 不应该传给 sidecar，否则 ArticleView
  // 那边会找不到模板。带前缀就当成"未指定"。
  const realTpl = tplId.value.startsWith("_demo_") ? undefined : tplId.value;
  const realSkill = skillId.value.startsWith("_demo_") ? undefined : skillId.value;
  router.push({
    name: "article",
    query: {
      keyword: keyword.value.trim(),
      template_id: realTpl,
      skill_id: realSkill,
    },
  });
}

// 模板库和 Skill 都落到 TemplatesView，但 Skill 必须带 ?tab=skills query
// 才能直接定位到 Skill 列表 —— TemplatesView 里有 watcher 监听这个 query。
const QUICK_TILES = [
  { name: "copy", label: "粘贴洗稿", desc: "原文 → Skill", to: "article", query: {} },
  {
    name: "library",
    label: "模板库",
    desc: "复用已有写作框架",
    to: "templates",
    query: { tab: "templates" },
  },
  { name: "radar", label: "监测", desc: "排名 / 评论看板", to: "monitor", query: {} },
  {
    name: "skills",
    label: "Skill",
    desc: "风格 · 语气",
    to: "templates",
    query: { tab: "skills" },
  },
] as const;
</script>

<template>
  <!--
    自带 min-height 确保和右侧 CalendarCard 视觉等高。两张卡都设
    同一个 min-height 而不是依赖 grid stretch + h-full 类穿透 ——
    后者跨组件层级不可靠，之前出过空白页问题。
  -->
  <Card muted padless class="h-full" :style="{ minHeight: '340px' }">
    <div
      class="relative flex h-full flex-col overflow-hidden"
      :style="{ borderRadius: 'var(--radius-card)', padding: '22px', minHeight: '340px' }"
    >
      <!-- 暖色 blob 装饰 — 黄叠橙，pointer-events:none 不挡交互 -->
      <div
        class="blur-blob"
        :style="{
          position: 'absolute',
          width: '300px',
          height: '300px',
          top: '-80px',
          left: '-50px',
          borderRadius: '50%',
          background: 'var(--yellow)',
          opacity: 0.55,
          zIndex: 0,
        }"
      />
      <div
        class="blur-blob"
        :style="{
          position: 'absolute',
          width: '260px',
          height: '260px',
          top: '140px',
          left: '300px',
          borderRadius: '50%',
          background: 'var(--primary)',
          opacity: 0.4,
          zIndex: 0,
        }"
      />

      <div class="relative flex h-full flex-col" :style="{ zIndex: 2 }">
        <!-- 标题区 -->
        <div class="text-[10.5px] font-medium uppercase tracking-[1.5px] text-ink-3">
          写一篇 · 输入关键词
        </div>
        <div
          class="font-display mt-1.5 font-bold leading-snug"
          :style="{ fontSize: '22px', letterSpacing: '-0.5px' }"
        >
          输入一个关键词，让 CSM 帮你起一篇。
        </div>

        <!-- 一体胶囊输入条：搜索图标 + 输入 + 黑色按钮 -->
        <div
          class="mt-4 flex items-center"
          :style="{
            background: 'var(--card-white)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-pill)',
            padding: '6px',
            paddingLeft: '18px',
            boxShadow: '0 1px 0 rgba(28,26,23,0.04)',
          }"
        >
          <Icon name="search" :size="16" class="opacity-60" />
          <input
            v-model="keyword"
            placeholder="例如：宠物家庭吸尘器推荐"
            class="hero-input flex-1 bg-transparent px-3 outline-none"
            :style="{ fontSize: '14.5px', color: 'var(--ink)', height: '40px' }"
            @keyup.enter="takeoff"
          />
          <Btn variant="dark" :disabled="!keyword.trim()" @click="takeoff">
            <Icon name="play" :size="13" />
            开始生成
          </Btn>
        </div>

        <!-- 模板 + 风格 chip 行 -->
        <div class="mt-3 flex flex-wrap items-center gap-1.5">
          <span class="text-[11px] text-ink-3">模板</span>
          <button
            v-for="t in tplChips"
            :key="t.id"
            type="button"
            :style="{
              height: '26px',
              padding: '0 11px',
              borderRadius: '999px',
              fontSize: '11.5px',
              fontWeight: 500,
              background: tplId === t.id ? 'var(--dark)' : 'rgba(255,255,255,0.65)',
              color: tplId === t.id ? '#fbf7ec' : 'var(--ink-2)',
              border: tplId === t.id ? 'none' : '1px solid var(--line)',
            }"
            @click="tplId = t.id"
          >
            {{ t.name }}
          </button>

          <span class="ml-2 text-[11px] text-ink-3">风格</span>
          <button
            v-for="s in skillChips"
            :key="s.id"
            type="button"
            :style="{
              height: '26px',
              padding: '0 11px',
              borderRadius: '999px',
              fontSize: '11.5px',
              fontWeight: 500,
              background: skillId === s.id ? 'var(--primary)' : 'rgba(255,255,255,0.65)',
              color: skillId === s.id ? '#fff' : 'var(--ink-2)',
              border: skillId === s.id ? 'none' : '1px solid var(--line)',
            }"
            @click="skillId = s.id"
          >
            {{ s.name }}
          </button>
        </div>

        <!-- 4 个快捷卡片 — 嵌在 hero 内部，半透明白底 -->
        <!-- pt-6 (24px) 给 chip 行和快捷卡之间留出呼吸感，对齐 V1 设计稿 -->
        <div class="mt-auto grid grid-cols-2 gap-2.5 pt-6 sm:grid-cols-4">
          <button
            v-for="tile in QUICK_TILES"
            :key="tile.label"
            type="button"
            class="text-left transition hover:brightness-[0.98]"
            :style="{
              background: 'rgba(255,255,255,0.6)',
              border: '1px solid rgba(28,26,23,0.06)',
              borderRadius: '12px',
              padding: '11px',
              backdropFilter: 'blur(6px)',
            }"
            @click="router.push({ name: tile.to, query: tile.query })"
          >
            <span
              class="inline-flex items-center justify-center"
              :style="{
                width: '28px',
                height: '28px',
                borderRadius: '9px',
                background: 'var(--dark)',
                color: 'var(--primary)',
              }"
            >
              <Icon :name="tile.name" :size="13" />
            </span>
            <div class="font-display mt-2 text-[12.5px] font-semibold">
              {{ tile.label }}
            </div>
            <div class="mt-0.5 text-[10.5px] text-ink-3">{{ tile.desc }}</div>
          </button>
        </div>
      </div>
    </div>
  </Card>
</template>

<style scoped>
/*
  全局 :focus-visible 会给所有可聚焦元素套一圈 2px 橙色 outline，做键盘
  访问性提示。但 hero 这个胶囊输入框的视觉焦点已经由外层 pill 的边框
  + 白底承担了，再叠一圈橙框会变成"双重描边"很脏。这里把这一个 input
  的 focus ring 关掉，其他地方（设置、表单）继续保留无障碍提示。
*/
.hero-input:focus,
.hero-input:focus-visible {
  outline: none !important;
  box-shadow: none;
}
</style>
