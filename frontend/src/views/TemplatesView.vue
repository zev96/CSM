<script setup lang="ts">
/**
 * 模板库 —— 简化为纯卡片网格（3 列）+ tab 切换。
 *
 * 用户大改要求（替代旧 V1 设计稿同款"卡片 + 右侧预览"双栏）：
 *   1. 删 eyebrow + 副标段落，header 只剩 H1 标题 + 右侧 tab + 新建按钮
 *   2. 删右侧预览面板。原来"删除/编辑/用此模板"三个按钮收进每张卡的
 *      右上角 ⋯ 菜单（点击弹三按钮）
 *   3. 卡片信息加 tags + 使用次数（不再用预览面板交代细节）
 *   4. 点卡 = 跳详情/编辑页（/templates/edit/:id 或 /templates/skills/edit/:id），
 *      跟 Skill 编辑页同款 view-as-page 体验
 *
 * 移除：
 *   - selectedTemplate / selectedSkill / templateDetail / skillDetail（无预览）
 *   - inBuilder / builderTemplateId / TemplateBuilder mount（路由化）
 *   - SkillEditModal mount（→ SkillEditView 独立页）
 *   - 预览相关 computed (slotList, slotCount, skillMdLines, skillFileName)
 */
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import CreateTemplateModal from "@/components/templates/CreateTemplateModal.vue";

import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const sidecar = useSidecar();
const toast = useToast();
const route = useRoute();
const router = useRouter();
const { whenReady } = useSidecarReady();

const initialTab = route.query.tab === "skills" ? "skills" : "templates";
const tab = ref<"templates" | "skills">(initialTab);

watch(
  () => route.query.tab,
  (q) => {
    if (q === "skills") tab.value = "skills";
    else if (q === "templates") tab.value = "templates";
  },
);

const createModalOpen = ref(false);

function openCreateModal() {
  createModalOpen.value = true;
}

// 提交"新建模板"弹窗 → 跳到 builder 页带 query 初值。原来的"开 inBuilder
// 模式"现在改成 router.push，让 builder 跟编辑共用同一条路由。
function onCreateSubmit(payload: { name: string; product: string }) {
  router.push({
    name: "template-edit",
    params: { id: "new" },
    query: { name: payload.name, product: payload.product },
  });
}

interface Template {
  id: string;
  name: string;
  path?: string;
  /** 槽位数 — 由 blocks.length 推导，列表接口里通常没有 */
  slots?: number;
  /** 标签 — 列表接口若返回 template_type 等可填，否则为空 */
  tags?: string[];
  /** 用过次数 — 后端目前无统计，保持 undefined */
  used?: number;
}
interface Skill {
  id: string;
  name: string;
  desc: string;
  tone?: string;
  uses?: number;
}

const templates = ref<Template[]>([]);
const skills = ref<Skill[]>([]);
const loaded = ref(false);
const loading = ref(false);

async function loadTemplates() {
  loading.value = true;
  try {
    const r = await sidecar.client.get("/api/templates");
    templates.value = r.data.templates ?? [];
  } catch (e: any) {
    toast.error(`模板加载失败：${e?.message ?? e}`);
  } finally {
    loading.value = false;
    loaded.value = true;
  }
}

async function loadSkills() {
  loading.value = true;
  try {
    const r = await sidecar.client.get("/api/skills");
    skills.value = r.data.skills ?? [];
  } catch (e: any) {
    toast.error(`Skill 加载失败：${e?.message ?? e}`);
  } finally {
    loading.value = false;
  }
}

// ── 卡片操作 ──────────────────────────────────────────────
function goEditTemplate(t: Template) {
  router.push({ name: "template-edit", params: { id: t.id } });
}
function useTemplate(t: Template) {
  router.push({ name: "article", query: { template: t.id } });
}
async function deleteTemplate(t: Template) {
  if (!(await confirmDialog(`确定删除模板「${t.name}」？`, { title: "删除模板", okLabel: "删除" }))) return;
  try {
    await sidecar.client.delete(`/api/templates/${t.id}`);
    toast.success(`已删除：${t.name}`);
    await loadTemplates();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

function goEditSkill(s: Skill) {
  router.push({ name: "skill-edit", params: { id: s.id } });
}
function openCreateSkill() {
  router.push({ name: "skill-edit", params: { id: "new" } });
}
async function deleteSkill(s: Skill) {
  if (!(await confirmDialog(`确定删除 Skill「${s.name}」？`, { title: "删除 Skill", okLabel: "删除" }))) return;
  try {
    await sidecar.client.delete(`/api/skills/${s.id}`);
    toast.success(`已删除：${s.name}`);
    await loadSkills();
  } catch (e: any) {
    toast.error(`删除失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

// ── 卡片 ⋯ 菜单状态（全局单例 —— 同一时间只展开一张） ─────
// menuOpenFor 存当前打开菜单的卡 id；位置存 menuPos（fixed 坐标）。
// 跳出父级 overflow:hidden 用 <Teleport to="body"> 渲染菜单本体。
const menuOpenFor = ref<string | null>(null);
const menuPos = ref({ top: 0, right: 0 });

function openCardMenu(ev: MouseEvent, cardId: string) {
  ev.stopPropagation();
  const btn = ev.currentTarget as HTMLElement;
  const rect = btn.getBoundingClientRect();
  menuPos.value = {
    top: rect.bottom + 4,
    right: window.innerWidth - rect.right,
  };
  menuOpenFor.value = menuOpenFor.value === cardId ? null : cardId;
}
function closeCardMenu() { menuOpenFor.value = null; }
function onWindowChange() { if (menuOpenFor.value) menuOpenFor.value = null; }

watch(menuOpenFor, (open) => {
  if (open) {
    setTimeout(() => window.addEventListener("click", closeCardMenu), 0);
    window.addEventListener("scroll", onWindowChange, true);
    window.addEventListener("resize", onWindowChange);
  } else {
    window.removeEventListener("click", closeCardMenu);
    window.removeEventListener("scroll", onWindowChange, true);
    window.removeEventListener("resize", onWindowChange);
  }
});

watch(tab, async (t) => {
  if (t === "templates" && !templates.value.length && !loaded.value) await loadTemplates();
  if (t === "skills" && !skills.value.length) await loadSkills();
});

onMounted(async () => {
  try {
    await whenReady();
    await loadTemplates();
    await loadSkills();
  } catch {
    /* already toasted */
  }
});
</script>

<template>
  <div class="flex h-full flex-col" style="gap: var(--density-gap)">
    <!-- 新建模板模态：只问名字 + 产品，提交后跳进 builder 编辑页 -->
    <CreateTemplateModal
      v-model:open="createModalOpen"
      @submit="onCreateSubmit"
    />

    <!--
      header —— 按用户要求改成小字 eyebrow 样式（跟 MiningView "评论视频" /
      MonitorView / DataCenterView 顶部统一风格），不再用 30px H1。
    -->
    <div class="flex flex-shrink-0 items-center justify-between gap-4">
      <div
        class="text-[11px] uppercase"
        :style="{ letterSpacing: '1.5px', color: 'var(--ink-3)' }"
      >
        模板库
      </div>
      <div class="flex flex-shrink-0 items-center gap-2">
        <!-- 胶囊 tab 切换 -->
        <div
          class="flex items-center"
          :style="{
            background: 'var(--card)',
            borderRadius: '999px',
            padding: '4px',
            border: '1px solid var(--line)',
          }"
        >
          <button
            v-for="x in [
              { id: 'templates', label: '结构模板', icon: 'library' },
              { id: 'skills', label: '风格 Skill', icon: 'skills' },
            ]"
            :key="x.id"
            type="button"
            class="inline-flex items-center gap-1.5 transition"
            :style="{
              height: '32px',
              padding: '0 16px',
              borderRadius: '999px',
              fontSize: '12.5px',
              fontWeight: 500,
              background: tab === x.id ? 'var(--dark)' : 'transparent',
              color: tab === x.id ? '#fbf7ec' : 'var(--ink-3)',
            }"
            @click="tab = x.id as any"
          >
            <Icon :name="x.icon" :size="13" />
            {{ x.label }}
          </button>
        </div>
        <Btn
          v-if="tab === 'templates'"
          variant="solid"
          @click="openCreateModal"
        >
          <Icon name="plus" :size="13" />
          <span>新建模板</span>
        </Btn>
        <Btn v-else variant="solid" @click="openCreateSkill">
          <Icon name="plus" :size="13" />
          <span>新建 Skill</span>
        </Btn>
      </div>
    </div>

    <!-- body —— 3 列卡片网格，吃满宽度 -->
    <div
      v-if="tab === 'templates'"
      class="grid auto-rows-min min-h-0 flex-1 overflow-y-auto pr-1"
      :style="{
        gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
        gap: 'var(--density-gap)',
        alignContent: 'start',
      }"
    >
      <div
        v-if="loading && !templates.length"
        class="col-span-3 flex justify-center p-6"
      >
        <Spinner :size="14" />
      </div>
      <div
        v-else-if="!templates.length"
        class="col-span-3 flex flex-col items-center text-center"
        :style="{
          padding: '60px 30px',
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          color: 'var(--ink-3)',
        }"
      >
        <span
          :style="{
            width: '54px', height: '54px', borderRadius: '16px',
            background: 'var(--card-2)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            marginBottom: '14px',
          }"
        >
          <Icon name="library" :size="22" />
        </span>
        <div class="font-display font-bold text-[16px]" :style="{ color: 'var(--ink-2)' }">
          还没有模板
        </div>
        <div class="text-[12px] mt-1.5" :style="{ maxWidth: '360px' }">
          点右上角「新建模板」开一个，模板决定文章的骨架与槽位。
        </div>
      </div>

      <!-- ── 结构模板 卡片 ─────────────────────────────────── -->
      <div
        v-for="t in templates"
        :key="t.id"
        class="relative cursor-pointer transition"
        :style="{
          minHeight: '160px',
          padding: '18px',
          borderRadius: 'var(--radius-card)',
          background: 'var(--card)',
          border: '1px solid var(--line)',
        }"
        @click="goEditTemplate(t)"
        @mouseenter="(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--line-2)'; (e.currentTarget as HTMLElement).style.boxShadow = '0 6px 16px -8px rgba(var(--ink-rgb),0.18)'; }"
        @mouseleave="(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--line)'; (e.currentTarget as HTMLElement).style.boxShadow = 'none'; }"
      >
        <!-- ⋯ 菜单按钮（右上角） -->
        <button
          type="button"
          class="absolute inline-flex items-center justify-center transition"
          :style="{
            top: '12px', right: '12px',
            width: '26px', height: '26px', borderRadius: '999px',
            background: menuOpenFor === t.id ? 'var(--card-2)' : 'transparent',
            color: 'var(--ink-3)',
            border: '1px solid ' + (menuOpenFor === t.id ? 'var(--line-2)' : 'transparent'),
            cursor: 'pointer',
          }"
          title="更多"
          @click="openCardMenu($event, t.id)"
          @mouseenter="(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
          @mouseleave="(e) => { if (menuOpenFor !== t.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
        >
          <Icon name="more" :size="13" />
        </button>

        <div class="flex h-full flex-col" :style="{ paddingRight: '32px' }">
          <!-- 名字 -->
          <div
            class="font-display font-bold"
            :style="{ fontSize: '16px', lineHeight: 1.3, color: 'var(--ink)' }"
            :title="t.name"
          >
            {{ t.name }}
          </div>
          <!-- 槽位 meta（如有）-->
          <div
            v-if="t.slots"
            class="mt-1 text-[11.5px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            {{ t.slots }} 个槽位
          </div>
          <div class="flex-1" />
          <!-- tags chips（取前 3） -->
          <div v-if="t.tags?.length" class="flex flex-wrap gap-1.5 mt-3">
            <span
              v-for="tag in t.tags.slice(0, 3)"
              :key="tag"
              class="inline-flex items-center text-[10.5px]"
              :style="{
                padding: '2px 8px',
                borderRadius: '999px',
                background: 'var(--card-2)',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
              }"
            >#{{ tag }}</span>
          </div>
          <!-- 使用次数 -->
          <div
            v-if="t.used !== undefined"
            class="mt-2 text-[11px]"
            :style="{ color: 'var(--ink-4)' }"
          >
            用过 <b :style="{ color: 'var(--ink-2)' }">{{ t.used }}</b> 次
          </div>
        </div>
      </div>
    </div>

    <!-- skills 卡片网格（同款，但 ⋯ 菜单的 "用此模板" 项隐藏 —— Skill
         不能像模板那样"用此 Skill → 进创作区"，那是模板的功能） -->
    <div
      v-else
      class="grid auto-rows-min min-h-0 flex-1 overflow-y-auto pr-1"
      :style="{
        gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
        gap: 'var(--density-gap)',
        alignContent: 'start',
      }"
    >
      <div
        v-if="loading && !skills.length"
        class="col-span-3 flex justify-center p-6"
      >
        <Spinner :size="14" />
      </div>
      <div
        v-else-if="!skills.length"
        class="col-span-3 flex flex-col items-center text-center"
        :style="{
          padding: '60px 30px',
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-card)',
          color: 'var(--ink-3)',
        }"
      >
        <span
          :style="{
            width: '54px', height: '54px', borderRadius: '16px',
            background: 'var(--card-2)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            marginBottom: '14px',
          }"
        >
          <Icon name="skills" :size="22" />
        </span>
        <div class="font-display font-bold text-[16px]" :style="{ color: 'var(--ink-2)' }">
          还没有 Skill
        </div>
        <div class="text-[12px] mt-1.5" :style="{ maxWidth: '360px' }">
          点右上角「新建 Skill」开一个，Skill 决定写作的语气与收口。
        </div>
      </div>
      <div
        v-for="s in skills"
        :key="s.id"
        class="relative cursor-pointer transition"
        :style="{
          minHeight: '160px',
          padding: '18px',
          borderRadius: 'var(--radius-card)',
          background: 'var(--card)',
          border: '1px solid var(--line)',
        }"
        @click="goEditSkill(s)"
        @mouseenter="(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--line-2)'; (e.currentTarget as HTMLElement).style.boxShadow = '0 6px 16px -8px rgba(var(--ink-rgb),0.18)'; }"
        @mouseleave="(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--line)'; (e.currentTarget as HTMLElement).style.boxShadow = 'none'; }"
      >
        <button
          type="button"
          class="absolute inline-flex items-center justify-center transition"
          :style="{
            top: '12px', right: '12px',
            width: '26px', height: '26px', borderRadius: '999px',
            background: menuOpenFor === s.id ? 'var(--card-2)' : 'transparent',
            color: 'var(--ink-3)',
            border: '1px solid ' + (menuOpenFor === s.id ? 'var(--line-2)' : 'transparent'),
            cursor: 'pointer',
          }"
          title="更多"
          @click="openCardMenu($event, s.id)"
          @mouseenter="(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--card-2)'; }"
          @mouseleave="(e) => { if (menuOpenFor !== s.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }"
        >
          <Icon name="more" :size="13" />
        </button>

        <div class="flex h-full flex-col" :style="{ paddingRight: '32px' }">
          <div
            class="font-display font-bold"
            :style="{ fontSize: '16px', lineHeight: 1.3, color: 'var(--ink)' }"
            :title="s.name"
          >
            {{ s.name }}
          </div>
          <div
            v-if="s.desc"
            class="mt-1 text-[11.5px]"
            :style="{ color: 'var(--ink-3)', lineHeight: 1.5 }"
          >
            {{ s.desc }}
          </div>
          <div class="flex-1" />
          <div v-if="s.tone" class="flex flex-wrap gap-1.5 mt-3">
            <span
              class="inline-flex items-center text-[10.5px]"
              :style="{
                padding: '2px 8px',
                borderRadius: '999px',
                background: 'var(--card-2)',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
              }"
            >#{{ s.tone }}</span>
          </div>
          <div
            v-if="s.uses !== undefined"
            class="mt-2 text-[11px]"
            :style="{ color: 'var(--ink-4)' }"
          >
            用过 <b :style="{ color: 'var(--ink-2)' }">{{ s.uses }}</b> 次
          </div>
        </div>
      </div>
    </div>

    <!--
      ⋯ 菜单 Teleport 到 body —— 防止被卡片父级 overflow / transform 裁切。
      根据 menuOpenFor 是 templates 还是 skills 类型的 id 分别渲染。
      tab 切换时菜单自动关（v-if 跟当前 tab 联动）。
    -->
    <Teleport to="body">
      <div
        v-if="menuOpenFor && tab === 'templates'"
        :style="{
          position: 'fixed',
          top: menuPos.top + 'px',
          right: menuPos.right + 'px',
          minWidth: '160px',
          background: 'var(--card-white)',
          border: '1px solid var(--line-2)',
          borderRadius: '10px',
          boxShadow: '0 10px 30px -8px rgba(var(--ink-rgb),0.25)',
          padding: '4px',
          zIndex: 9999,
        }"
        @click.stop
      >
        <button
          type="button"
          class="flex w-full items-center gap-2 text-left"
          :style="{
            height: '30px', padding: '0 10px', borderRadius: '7px',
            fontSize: '12px', color: 'var(--ink)', background: 'transparent', cursor: 'pointer',
          }"
          @mouseenter="($event.currentTarget as HTMLElement).style.background = 'var(--card-2)'"
          @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
          @click="() => { const t = templates.find((x) => x.id === menuOpenFor); if (t) { closeCardMenu(); useTemplate(t); } }"
        >
          <Icon name="play" :size="12" />
          <span>用此模板</span>
        </button>
        <button
          type="button"
          class="flex w-full items-center gap-2 text-left"
          :style="{
            height: '30px', padding: '0 10px', borderRadius: '7px',
            fontSize: '12px', color: 'var(--ink)', background: 'transparent', cursor: 'pointer',
          }"
          @mouseenter="($event.currentTarget as HTMLElement).style.background = 'var(--card-2)'"
          @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
          @click="() => { const t = templates.find((x) => x.id === menuOpenFor); if (t) { closeCardMenu(); goEditTemplate(t); } }"
        >
          <Icon name="edit" :size="12" />
          <span>编辑模板</span>
        </button>
        <button
          type="button"
          class="flex w-full items-center gap-2 text-left"
          :style="{
            height: '30px', padding: '0 10px', borderRadius: '7px',
            fontSize: '12px', color: 'var(--red, #c0392b)', background: 'transparent', cursor: 'pointer',
          }"
          @mouseenter="($event.currentTarget as HTMLElement).style.background = 'rgba(192,57,43,0.08)'"
          @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
          @click="() => { const t = templates.find((x) => x.id === menuOpenFor); if (t) { closeCardMenu(); deleteTemplate(t); } }"
        >
          <Icon name="trash" :size="12" />
          <span>删除模板</span>
        </button>
      </div>
      <div
        v-else-if="menuOpenFor && tab === 'skills'"
        :style="{
          position: 'fixed',
          top: menuPos.top + 'px',
          right: menuPos.right + 'px',
          minWidth: '140px',
          background: 'var(--card-white)',
          border: '1px solid var(--line-2)',
          borderRadius: '10px',
          boxShadow: '0 10px 30px -8px rgba(var(--ink-rgb),0.25)',
          padding: '4px',
          zIndex: 9999,
        }"
        @click.stop
      >
        <button
          type="button"
          class="flex w-full items-center gap-2 text-left"
          :style="{
            height: '30px', padding: '0 10px', borderRadius: '7px',
            fontSize: '12px', color: 'var(--ink)', background: 'transparent', cursor: 'pointer',
          }"
          @mouseenter="($event.currentTarget as HTMLElement).style.background = 'var(--card-2)'"
          @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
          @click="() => { const s = skills.find((x) => x.id === menuOpenFor); if (s) { closeCardMenu(); goEditSkill(s); } }"
        >
          <Icon name="edit" :size="12" />
          <span>编辑 Skill</span>
        </button>
        <button
          type="button"
          class="flex w-full items-center gap-2 text-left"
          :style="{
            height: '30px', padding: '0 10px', borderRadius: '7px',
            fontSize: '12px', color: 'var(--red, #c0392b)', background: 'transparent', cursor: 'pointer',
          }"
          @mouseenter="($event.currentTarget as HTMLElement).style.background = 'rgba(192,57,43,0.08)'"
          @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
          @click="() => { const s = skills.find((x) => x.id === menuOpenFor); if (s) { closeCardMenu(); deleteSkill(s); } }"
        >
          <Icon name="trash" :size="12" />
          <span>删除 Skill</span>
        </button>
      </div>
    </Teleport>
  </div>
</template>
