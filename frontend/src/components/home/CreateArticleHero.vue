<script setup lang="ts">
/**
 * 首页 hero 卡 — 合并旧的 GreetingCard + KeywordHero。
 *
 * 设计稿约定：
 *   - 26px 大标"<greeting>，<name>。今天写点什么？"
 *   - 大标下方 11.5px 系统日期副标（"M/D · 周X"）—— 颜色 --ink-4（最淡）
 *   - 胶囊输入条：放大镜 + input + 黑色"创建 →"按钮
 *   - 两个 dropdown 胶囊：模板 / 风格
 *
 * 数据：
 *   - templates / skills 从 /api/templates、/api/skills 拉，失败 fallback。
 *   - 用户名从 useConfig().data.user_name；问候语本地小时数算出。
 *   - dateLabel 系统当前日期，hero mount 时算一次；日内切换日期不会自动刷新
 *     （工作台 view 切回来会重 mount，跟 greeting 同语义）。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Dropdown from "@/components/ui/Dropdown.vue";
import Icon from "@/components/ui/Icon.vue";
import AnglePicker from "@/components/article/AnglePicker.vue";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import type { Angle } from "@/stores/article";

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

// 角度（人群/卖点/语调）+ 标题 —— 起飞时扁平进 query，由 ArticleView 重建。
// 默认 null/空 = 不传角度 = 今天行为。
const angle = ref<Angle | null>(null);
const title = ref<string>("");
const showAnglePicker = ref(false);

// 角度是否有任一 facet 被设置 —— 控制 chip 的"已设置"高亮 + 摘要文案。
const angleActive = computed(() => {
  const a = angle.value;
  return Boolean(a && (a.audience || a.sellpoints.length > 0 || a.tone));
});
// chip 上显示的角度摘要（如「铲屎官·防缠绕…·口语」），未设置时显示「角度」。
const angleSummary = computed(() => {
  const a = angle.value;
  if (!a) return "角度";
  const parts: string[] = [];
  if (a.audience) parts.push(a.audience);
  if (a.sellpoints.length > 0) parts.push(`${a.sellpoints.length} 卖点`);
  if (a.tone) parts.push(a.tone);
  return parts.length ? parts.join(" · ") : "角度";
});

function onPickTemplate(id: string) {
  // AnglePicker 选了带 template_id 的预设 —— 同步更新模板选择。
  if (templates.value.some((t) => t.id === id)) tplId.value = id;
  else tplId.value = id; // 即便当前列表没有也接受（ArticleView 会再校验）
}

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 6) return "深夜好";
  if (h < 11) return "早安";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
});
const userName = computed(() => cfg.data?.user_name || "你");

// 系统当前日期 —— "5/22 · 周五"。挂载时算一次，hero 不重渲日期就不变；
// 切日期需要 view 跳转触发重 mount，跟 greeting (按小时段) 同语义。
const dateLabel = computed(() => {
  const d = new Date();
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  return `${m}/${day} · ${weekdays[d.getDay()]}`;
});

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

  // 角度扁平进 query —— audience / sellpoints(逗号连) / tone / title，
  // 空的不入 query（保持 URL 干净 + ArticleView 重建时空 facet → null）。
  const query: Record<string, string> = {
    keyword: keyword.value.trim(),
  };
  if (realTpl) query.template_id = realTpl;
  if (realSkill) query.skill_id = realSkill;
  const a = angle.value;
  if (a?.audience) query.audience = a.audience;
  if (a?.sellpoints?.length) query.sellpoints = a.sellpoints.join(",");
  if (a?.tone) query.tone = a.tone;
  if (title.value.trim()) query.title = title.value.trim();

  router.push({ name: "article", query });
}

// 给测试（@vue/test-utils vm）访问内部 state/方法 —— <script setup> 默认
// 闭合，不 expose 测不到 takeoff/angle/title。
defineExpose({ keyword, angle, title, tplId, takeoff, onPickTemplate });
</script>

<template>
  <!--
    平铺版本：去 Card 外框、去暖色 blob、去"创建新文章"小标。
    直接贴在页面背景上，紧凑布局（参考设计：大标 → 输入条 → chip 行）。
    输入条 max-width 让它不撑满整行，看起来更像 hero CTA 而不是表单。
  -->
  <div class="flex flex-col" :style="{ gap: '14px' }">
    <!--
      大标 + 日期副标包在同一 div 里，让两者贴近（mt-1.5 = 6px），不被
      外层 gap:14 撑开。日期颜色 --ink-4 是 token 系统里最淡的灰，符合
      "小字 + 颜色淡"要求。
    -->
    <div>
      <div
        class="font-display font-bold leading-tight"
        :style="{ fontSize: '26px', letterSpacing: '-0.5px' }"
      >
        {{ greeting }}，{{ userName }}。今天写点什么？
      </div>
      <div
        class="mt-1.5 text-[11.5px]"
        :style="{ color: 'var(--ink-4)' }"
      >
        {{ dateLabel }}
      </div>
    </div>

    <!--
      一体胶囊输入条（窄，不撑满）。marginTop 跟外层 gap:14 是 additive，
      "大标块 → 输入框"实际间距 = 14 + 20 = 34px。
    -->
    <div
      class="flex items-center"
      :style="{
        maxWidth: '460px',
        marginTop: '20px',
        background: 'var(--frosted-bg)',
        backdropFilter: 'blur(14px) saturate(140%)',
        WebkitBackdropFilter: 'blur(14px) saturate(140%)',
        border: '1px solid var(--frosted-border)',
        borderRadius: 'var(--radius-pill)',
        padding: '6px',
        paddingLeft: '18px',
        boxShadow: '0 4px 14px rgba(var(--shadow-rgb),0.06), 0 1px 3px rgba(var(--shadow-rgb),0.04)',
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
              background: 'var(--frosted-bg)',
              backdropFilter: 'blur(12px) saturate(140%)',
              WebkitBackdropFilter: 'blur(12px) saturate(140%)',
              border: '1px solid var(--frosted-border)',
              borderRadius: 'var(--radius-pill)',
              fontSize: '12px',
              color: 'var(--ink-2)',
              cursor: 'pointer',
              boxShadow: '0 2px 6px rgba(var(--shadow-rgb),0.04), 0 1px 2px rgba(var(--shadow-rgb),0.03)',
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
              background: 'var(--frosted-bg)',
              backdropFilter: 'blur(12px) saturate(140%)',
              WebkitBackdropFilter: 'blur(12px) saturate(140%)',
              border: '1px solid var(--frosted-border)',
              borderRadius: 'var(--radius-pill)',
              fontSize: '12px',
              color: 'var(--ink-2)',
              cursor: 'pointer',
              boxShadow: '0 2px 6px rgba(var(--shadow-rgb),0.04), 0 1px 2px rgba(var(--shadow-rgb),0.03)',
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

      <!--
        角度 chip —— 与 模板 / 风格 平级，但点击打开 AnglePicker 弹层
        （角度选项多，不适合塞 Dropdown）。已设置任一 facet 时高亮 +
        显示摘要（「铲屎官 · 2 卖点 · 口语」）。
      -->
      <button
        type="button"
        class="inline-flex items-center gap-2"
        :style="{
          height: '32px',
          padding: '0 12px',
          background: angleActive ? 'var(--primary-soft)' : 'var(--frosted-bg)',
          backdropFilter: 'blur(12px) saturate(140%)',
          WebkitBackdropFilter: 'blur(12px) saturate(140%)',
          border: angleActive ? '1px solid var(--primary)' : '1px solid var(--frosted-border)',
          borderRadius: 'var(--radius-pill)',
          fontSize: '12px',
          color: angleActive ? 'var(--primary-deep)' : 'var(--ink-2)',
          cursor: 'pointer',
          boxShadow: '0 2px 6px rgba(var(--shadow-rgb),0.04), 0 1px 2px rgba(var(--shadow-rgb),0.03)',
        }"
        @click="showAnglePicker = true"
      >
        <span :style="{ color: angleActive ? 'var(--primary-deep)' : 'var(--ink-3)' }">角度</span>
        <span class="font-semibold">{{ angleActive ? angleSummary : "不限" }}</span>
        <Icon name="arrowDown" :size="11" />
      </button>
    </div>
  </div>

  <!--
    角度选择弹层 —— 居中模态（与创作区导出弹窗同款 Teleport 结构）。
    AnglePicker 受控：v-model 绑 angle / title。点遮罩或「完成」关闭。
  -->
  <Teleport to="body">
    <div
      v-if="showAnglePicker"
      class="fixed inset-0 z-40 flex items-center justify-center"
      :style="{ background: 'rgba(var(--ink-rgb),0.4)' }"
      @click.self="showAnglePicker = false"
    >
      <div
        class="anim-up flex flex-col"
        :style="{
          width: '560px',
          maxWidth: '92vw',
          maxHeight: '86vh',
          borderRadius: 'var(--radius-card)',
          background: 'var(--bg-inner)',
          border: '1px solid var(--line)',
          boxShadow: '0 18px 50px rgba(var(--shadow-rgb),0.18)',
        }"
      >
        <div
          class="flex flex-shrink-0 items-start justify-between"
          :style="{ padding: '20px 22px 14px' }"
        >
          <div>
            <div :style="{ fontSize: '11.5px', color: 'var(--ink-3)', marginBottom: '4px' }">
              写作角度
            </div>
            <div
              class="font-display"
              :style="{ fontSize: '18px', fontWeight: 700, color: 'var(--ink)' }"
            >
              选人群 / 卖点 / 语调 / 标题
            </div>
          </div>
          <button
            type="button"
            class="inline-flex items-center justify-center transition hover:brightness-95"
            :style="{
              width: '28px',
              height: '28px',
              borderRadius: '999px',
              background: 'var(--card-2)',
              color: 'var(--ink-2)',
              border: '1px solid var(--line)',
            }"
            @click="showAnglePicker = false"
          >
            <Icon name="x" :size="14" />
          </button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto" :style="{ padding: '0 22px 8px' }">
          <AnglePicker
            v-model="angle"
            v-model:title="title"
            @pick-template="onPickTemplate"
          />
        </div>
        <div
          class="flex flex-shrink-0 justify-end"
          :style="{ padding: '14px 22px 20px' }"
        >
          <Btn variant="dark" @click="showAnglePicker = false">完成</Btn>
        </div>
      </div>
    </div>
  </Teleport>
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
  hidden 的 ghost 不占视觉但占布局，撑出 cell 宽度；current 是 source-order
  最后一个，自然在 z-stack 顶层。
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
