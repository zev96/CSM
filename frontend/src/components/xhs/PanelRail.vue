<script setup lang="ts">
/**
 * 左栏素材面板（设计稿 §4.1 左 / §5 九面板）。
 * 左侧 9 个图标 tab；右侧内容区按 activePanel 派发到对应面板组件。
 * 文字面板（模版/主题/表情/标题/文案/话题/装饰）P1 已上线；图片(P2)/AI(P3) 仍占位。
 */
import { computed, type Component } from "vue";
import Icon from "@/components/ui/Icon.vue";
import { useXhs, type XhsPanel } from "@/stores/xhs";
import TemplatePanel from "./panels/TemplatePanel.vue";
import ThemePanel from "./panels/ThemePanel.vue";
import EmojiPanel from "./panels/EmojiPanel.vue";
import TitlePanel from "./panels/TitlePanel.vue";
import CopyPanel from "./panels/CopyPanel.vue";
import TopicPanel from "./panels/TopicPanel.vue";
import DecorationPanel from "./panels/DecorationPanel.vue";
import ImagePanel from "./panels/ImagePanel.vue";

const xhs = useXhs();

interface PanelDef {
  key: XhsPanel;
  icon: string;
  label: string;
  /** 占位说明：该面板将在哪个阶段上线（仅 image/ai 仍占位）。 */
  stage: string;
}

// icon 全部复用 Icon.vue 现有图标，避免新增 SVG。
const PANELS: PanelDef[] = [
  { key: "template", icon: "library", label: "模版", stage: "P1" },
  { key: "theme", icon: "sliders", label: "主题", stage: "P1" },
  { key: "emoji", icon: "heart", label: "表情", stage: "P1" },
  { key: "title", icon: "edit", label: "标题", stage: "P1" },
  { key: "copy", icon: "doc", label: "文案", stage: "P1" },
  { key: "topic", icon: "tag", label: "话题", stage: "P1" },
  { key: "decoration", icon: "skills", label: "装饰", stage: "P1" },
  { key: "image", icon: "image", label: "图片", stage: "P2" },
  { key: "ai", icon: "spark", label: "AI", stage: "P3" },
];

// activePanel → 面板组件；image / ai 不在表内 → 走占位分支。
const PANEL_COMPONENTS: Partial<Record<XhsPanel, Component>> = {
  template: TemplatePanel,
  theme: ThemePanel,
  emoji: EmojiPanel,
  title: TitlePanel,
  copy: CopyPanel,
  topic: TopicPanel,
  decoration: DecorationPanel,
  image: ImagePanel,
};

const activeComponent = computed<Component | null>(() => PANEL_COMPONENTS[xhs.activePanel] ?? null);

function activeDef(): PanelDef {
  return PANELS.find((p) => p.key === xhs.activePanel) ?? PANELS[0];
}
</script>

<template>
  <div class="flex h-full" :style="{ gap: '0' }">
    <!-- 图标 tab 列 -->
    <div
      class="flex flex-col items-center"
      :style="{ width: '64px', gap: '4px', padding: '4px', borderRight: '1px solid var(--line-2)' }"
    >
      <button
        v-for="p in PANELS"
        :key="p.key"
        type="button"
        class="flex flex-col items-center justify-center"
        :title="p.label"
        :style="{
          width: '56px', padding: '8px 0', borderRadius: '10px', cursor: 'pointer',
          gap: '3px',
          background: xhs.activePanel === p.key ? 'rgba(var(--ink-rgb),0.06)' : 'transparent',
          color: xhs.activePanel === p.key ? 'var(--primary)' : 'var(--ink-2)',
        }"
        @click="xhs.setActivePanel(p.key)"
      >
        <Icon :name="p.icon" :size="18" />
        <span :style="{ fontSize: '11px' }">{{ p.label }}</span>
      </button>
    </div>

    <!-- 面板内容区：派发到真实面板；image/ai 仍占位 -->
    <div class="min-h-0 flex-1 overflow-hidden" :style="{ padding: '14px' }">
      <component :is="activeComponent" v-if="activeComponent" />
      <div
        v-else
        class="flex flex-col items-center justify-center"
        :style="{
          gap: '10px', textAlign: 'center', color: 'var(--ink-2)', fontSize: '13px',
          border: '1px dashed var(--line-2)', borderRadius: '12px', padding: '28px 16px',
        }"
      >
        <Icon :name="activeDef().icon" :size="26" />
        <div>「{{ activeDef().label }}」面板将在 {{ activeDef().stage }} 上线</div>
      </div>
    </div>
  </div>
</template>
