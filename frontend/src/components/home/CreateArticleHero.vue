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
import Card from "@/components/ui/Card.vue";
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
  <Card muted padless class="h-full">
    <div
      class="relative flex h-full flex-col overflow-hidden"
      :style="{
        borderRadius: 'var(--radius-card)',
        padding: 'var(--density-pad)',
      }"
    >
      <!-- 暖色 blob 装饰：黄 + 橙叠加，pointer-events:none 不挡交互 -->
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
        <!-- 小标 -->
        <div
          class="text-[10.5px] font-medium uppercase tracking-[1.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          创建新文章
        </div>

        <!-- 问候 + CTA 大标 -->
        <div
          class="font-display mt-2 font-bold leading-tight"
          :style="{ fontSize: '26px', letterSpacing: '-0.5px' }"
        >
          {{ greeting }}，{{ userName }}。今天写点什么？
        </div>

        <!-- 一体胶囊输入条 -->
        <div
          class="mt-5 flex items-center"
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
            placeholder="输入关键词，例如「宠物家庭吸尘器」"
            class="hero-input flex-1 bg-transparent px-3 outline-none"
            :style="{
              fontSize: '14.5px',
              color: 'var(--ink)',
              height: '40px',
            }"
            @keyup.enter="takeoff"
          />
          <Btn variant="dark" :disabled="!keyword.trim()" @click="takeoff">
            创建
            <Icon name="arrowRight" :size="13" />
          </Btn>
        </div>

        <!-- 模板 / 风格 dropdown 胶囊 -->
        <div class="mt-4 flex flex-wrap items-center gap-2">
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
                <span class="font-semibold" :style="{ color: 'var(--ink)' }">{{
                  tplLabel
                }}</span>
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
                <span class="font-semibold" :style="{ color: 'var(--ink)' }">{{
                  skillLabel
                }}</span>
                <Icon name="arrowDown" :size="11" />
              </button>
            </template>
          </Dropdown>
        </div>
      </div>
    </div>
  </Card>
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
</style>
