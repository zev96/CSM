<script setup lang="ts">
/**
 * Menu-style dropdown — anchored under a trigger, lists items, fires
 * @select with the chosen key. Use for action menus ("More" buttons,
 * row context menus). Don't use for forms — that's Select.
 *
 * Floating positioning: tracks the trigger element's bounding rect and
 * places the panel just below it. Click-outside or escape dismisses.
 * Teleported to body so parent ``overflow: hidden`` containers can't
 * clip the panel.
 *
 * Example
 *   &lt;Dropdown
 *     :items="[
 *       { key: 'edit', label: '编辑', icon: 'edit' },
 *       { key: 'delete', label: '删除', icon: 'trash', tone: 'danger' },
 *     ]"
 *     @select="(k) =&gt; handle(k)"
 *   &gt;
 *     &lt;template #trigger&gt;
 *       &lt;IconBtn name="more" /&gt;
 *     &lt;/template&gt;
 *   &lt;/Dropdown&gt;
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";

import Icon from "./Icon.vue";

interface DropdownItem {
  key: string;
  label: string;
  icon?: string;
  disabled?: boolean;
  tone?: "default" | "danger";
}

const props = withDefaults(
  defineProps<{
    items: DropdownItem[];
    /** Anchor side — "right" aligns panel right edge to trigger right edge. */
    align?: "left" | "right";
    /** Minimum panel width in px. Default 160. */
    minWidth?: number;
  }>(),
  { align: "left", minWidth: 160 },
);

const emit = defineEmits<{
  (e: "select", key: string): void;
  (e: "update:open", v: boolean): void;
}>();

const open = ref(false);
const triggerEl = ref<HTMLElement | null>(null);
const panelEl = ref<HTMLElement | null>(null);
const rect = ref<{ top: number; left: number; right: number; bottom: number; width: number } | null>(null);

function toggle() {
  if (open.value) {
    close();
  } else {
    showAt();
  }
}

function showAt() {
  if (!triggerEl.value) return;
  const r = triggerEl.value.getBoundingClientRect();
  rect.value = {
    top: r.top,
    left: r.left,
    right: r.right,
    bottom: r.bottom,
    width: r.width,
  };
  open.value = true;
  emit("update:open", true);
}

function close() {
  open.value = false;
  emit("update:open", false);
}

function onPick(item: DropdownItem) {
  if (item.disabled) return;
  emit("select", item.key);
  close();
}

function onDocClick(e: MouseEvent) {
  if (!open.value) return;
  const target = e.target as Node;
  if (panelEl.value?.contains(target)) return;
  if (triggerEl.value?.contains(target)) return;
  close();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) close();
}

watch(open, (v) => {
  if (v) {
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeydown);
  } else {
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKeydown);
  }
});

onBeforeUnmount(() => {
  document.removeEventListener("click", onDocClick);
  document.removeEventListener("keydown", onKeydown);
});

const panelStyle = computed(() => {
  if (!rect.value) return { display: "none" };
  const top = rect.value.bottom + 6;
  // align="left": panel left = trigger left
  // align="right": panel right = trigger right (so left = right - panelWidth, but we don't
  //                know panelWidth before render; use right + transform via CSS)
  if (props.align === "right") {
    return {
      position: "fixed",
      top: `${top}px`,
      right: `${window.innerWidth - rect.value.right}px`,
      minWidth: `${props.minWidth}px`,
      zIndex: 60,
    } as const;
  }
  return {
    position: "fixed",
    top: `${top}px`,
    left: `${rect.value.left}px`,
    minWidth: `${props.minWidth}px`,
    zIndex: 60,
  } as const;
});
</script>

<template>
  <span ref="triggerEl" class="inline-flex" @click.stop="toggle">
    <slot name="trigger" />
  </span>

  <Teleport to="body">
    <div
      v-if="open"
      ref="panelEl"
      class="anim-up"
      :style="{
        ...panelStyle,
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: '10px',
        boxShadow: '0 12px 32px rgba(0,0,0,0.16)',
        padding: '4px',
      }"
      role="menu"
      @click.stop
    >
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        :disabled="item.disabled"
        class="flex w-full items-center gap-2 px-3 text-left"
        :style="{
          height: '32px',
          borderRadius: '6px',
          fontSize: '12.5px',
          color: item.tone === 'danger' ? 'var(--red)' : 'var(--ink)',
          cursor: item.disabled ? 'not-allowed' : 'pointer',
          opacity: item.disabled ? 0.5 : 1,
          background: 'transparent',
        }"
        role="menuitem"
        @click="onPick(item)"
        @mouseenter="(e) => ((e.currentTarget as HTMLButtonElement).style.background = 'var(--card-2)')"
        @mouseleave="(e) => ((e.currentTarget as HTMLButtonElement).style.background = 'transparent')"
      >
        <Icon v-if="item.icon" :name="item.icon" :size="13" />
        <span class="flex-1 truncate">{{ item.label }}</span>
      </button>
    </div>
  </Teleport>
</template>
