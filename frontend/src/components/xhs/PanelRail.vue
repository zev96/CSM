<script setup lang="ts">
/**
 * 左栏素材面板骨架（设计稿 §4.1 左 / §5 九面板）。
 * P0：9 个 tab 切换 + 占位内容。P1 起逐个面板填真实素材（JSON 驱动）。
 */
import Icon from "@/components/ui/Icon.vue";
import { useXhs, type XhsPanel } from "@/stores/xhs";

const xhs = useXhs();

interface PanelDef {
  key: XhsPanel;
  icon: string;
  label: string;
  /** 占位说明：该面板将在哪个阶段上线。 */
  stage: string;
}

// icon 全部复用 Icon.vue 现有图标，避免新增 9 个 SVG。
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

    <!-- 面板内容区（P0 占位） -->
    <div class="min-h-0 flex-1 overflow-y-auto" :style="{ padding: '16px' }">
      <div :style="{ fontSize: '14px', fontWeight: 600, color: 'var(--ink)', marginBottom: '10px' }">
        {{ activeDef().label }}
      </div>
      <div
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
