<script setup lang="ts">
/**
 * 首页 hero 卡 — 合并旧的 GreetingCard + KeywordHero。
 *
 * 设计稿约定：
 *   - 顶部 10.5px UPPERCASE 小标"创建新文章"
 *   - 26px 大标"<greeting>，<name>。今天写点什么？"
 *   - 胶囊输入条：放大镜 + input + 黑色"创建 →"按钮
 *   - 两个 dropdown 胶囊：模板 / 风格（取代 V1 的 chip 行 + 4 个 quick tile）
 *
 * 不再渲染：
 *   - 旧 quick tiles（粘贴洗稿 / 模板库 / 监测 / Skill）—— 入口已迁到右栏
 *     ShortcutColumn + LeftNav。
 *   - 字数小计（昨日 / 本周）—— 放在 hero 内信息密度过低，等后续监测中心
 *     接入。
 *
 * 数据：
 *   - templates / skills 从 /api/templates、/api/skills 拉，失败 fallback。
 *   - 用户名从 useConfig().data.user_name；问候语本地小时数算出。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Dropdown from "@/components/ui/Dropdown.vue";
import Icon from "@/components/ui/Icon.vue";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";

interface Chip {
  id: string;
  name: string;
}

const FALLBACK_TEMPLATES: Chip[] = [{ id: "_demo_default", name: "默认模板" }];
const FALLBACK_SKILLS: Chip[] = [{ id: "_demo_default", name: "默认 Skill" }];

const router = useRouter();
const cfg = useConfig();
const sidecar = useSidecar();
const { whenReady } = useSidecarReady();

const keyword = ref("");
const templates = ref<Chip[]>(FALLBACK_TEMPLATES);
const skills = ref<Chip[]>(FALLBACK_SKILLS);
const tplId = ref<string>(FALLBACK_TEMPLATES[0].id);
const skillId = ref<string>(FALLBACK_SKILLS[0].id);

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 6) return "深夜好";
  if (h < 11) return "早安";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
});
const userName = computed(() => cfg.data?.user_name || "你");

const tplLabel = computed(
  () => templates.value.find((t) => t.id === tplId.value)?.name ?? "未指定",
);
const skillLabel = computed(
  () => skills.value.find((s) => s.id === skillId.value)?.name ?? "未指定",
);

const tplItems = computed(() =>
  templates.value.map((t) => ({ key: t.id, label: t.name })),
);
const skillItems = computed(() =>
  skills.value.map((s) => ({ key: s.id, label: s.name })),
);

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
    /* 静默失败 — 占位仍可点击 takeoff，到 ArticleView 那边会再拉一次 */
  }
});

function takeoff() {
  if (!keyword.value.trim()) return;
  // _demo_ 前缀仅用于占位，不要传给 sidecar，否则 ArticleView 找不到模板。
  const realTpl = tplId.value.startsWith("_demo_") ? undefined : tplId.value;
  const realSkill = skillId.value.startsWith("_demo_")
    ? undefined
    : skillId.value;
  router.push({
    name: "article",
    query: {
      keyword: keyword.value.trim(),
      template_id: realTpl,
      skill_id: realSkill,
    },
  });
}
</script>

<template>
  <!--
    平铺版本：去 Card 外框、去暖色 blob、去"创建新文章"小标。
    直接贴在页面背景上，紧凑布局（参考设计：大标 → 输入条 → chip 行）。
    输入条 max-width 让它不撑满整行，看起来更像 hero CTA 而不是表单。
  -->
  <div class="flex flex-col" :style="{ gap: '14px' }">
    <!-- 问候 + CTA 大标 -->
    <div
      class="font-display font-bold leading-tight"
      :style="{ fontSize: '26px', letterSpacing: '-0.5px' }"
    >
      {{ greeting }}，{{ userName }}。今天写点什么？
    </div>

    <!-- 一体胶囊输入条（窄，不撑满） -->
    <div
      class="flex items-center"
      :style="{
        maxWidth: '460px',
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
        placeholder="输入关键词，例如「宠物家庭吸尘器」"
        class="hero-input flex-1 bg-transparent px-3 outline-none"
        :style="{
          fontSize: '14.5px',
          color: 'var(--ink)',
          height: '36px',
        }"
        @keyup.enter="takeoff"
      />
      <Btn variant="dark" :disabled="!keyword.trim()" @click="takeoff">
        创建
        <Icon name="arrowRight" :size="13" />
      </Btn>
    </div>

    <!--
      模板 / 风格 dropdown 胶囊。胶囊宽度按所有候选选项中最宽的那项
      锁死 —— 切换风格时不会跳。用 CSS grid stacking：每个候选 name
      以 visibility:hidden 占位铺在同一 grid cell（grid-column/row:1），
      column 宽度自动取所有 children 的 max-content；可见 label 也
      落在同一 cell，叠在 hidden 上面正常显示。纯 CSS，无 JS measure。
    -->
    <div class="flex flex-wrap items-center gap-2">
      <Dropdown :items="tplItems" @select="(k: string) => (tplId = k)">
        <template #trigger>
          <button
            type="button"
            class="inline-flex items-center gap-2"
            :style="{
              height: '32px',
              padding: '0 12px',
              background: 'var(--card-white)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-pill)',
              fontSize: '12px',
              color: 'var(--ink-2)',
              cursor: 'pointer',
            }"
          >
            <span :style="{ color: 'var(--ink-3)' }">模板</span>
            <span
              class="dd-label-stack font-semibold"
              :style="{ color: 'var(--ink)' }"
            >
              <span
                v-for="t in templates"
                :key="t.id"
                aria-hidden="true"
                class="dd-label-ghost"
                >{{ t.name }}</span
              >
              <span class="dd-label-current">{{ tplLabel }}</span>
            </span>
            <Icon name="arrowDown" :size="11" />
          </button>
        </template>
      </Dropdown>

      <Dropdown :items="skillItems" @select="(k: string) => (skillId = k)">
        <template #trigger>
          <button
            type="button"
            class="inline-flex items-center gap-2"
            :style="{
              height: '32px',
              padding: '0 12px',
              background: 'var(--card-white)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-pill)',
              fontSize: '12px',
              color: 'var(--ink-2)',
              cursor: 'pointer',
            }"
          >
            <span :style="{ color: 'var(--ink-3)' }">风格</span>
            <span
              class="dd-label-stack font-semibold"
              :style="{ color: 'var(--ink)' }"
            >
              <span
                v-for="s in skills"
                :key="s.id"
                aria-hidden="true"
                class="dd-label-ghost"
                >{{ s.name }}</span
              >
              <span class="dd-label-current">{{ skillLabel }}</span>
            </span>
            <Icon name="arrowDown" :size="11" />
          </button>
        </template>
      </Dropdown>
    </div>
  </div>
</template>

<style scoped>
/*
  胶囊输入条已用外层 border + 白底作视觉聚焦反馈，input 自身再加
  全局 :focus-visible 的 2px 橙色 outline 会变成双重描边，关掉。
*/
.hero-input:focus,
.hero-input:focus-visible {
  outline: none !important;
  box-shadow: none;
}

/*
  下拉胶囊的 label 宽度锁死到最长选项 —— grid cell 宽度 = 所有 children
  的 max-content max。ghost 与 current 都落在 row 1 / col 1，visibility:
  hidden 的 ghost 不占视觉但占布局，撑出 cell 宽度；current 叠在上面正常
  显示。current 是 source-order 最后一个，自然在 z-stack 顶层。
*/
.dd-label-stack {
  display: inline-grid;
}
.dd-label-stack > * {
  grid-column: 1;
  grid-row: 1;
  white-space: nowrap;
}
.dd-label-ghost {
  visibility: hidden;
  pointer-events: none;
  user-select: none;
}
</style>
