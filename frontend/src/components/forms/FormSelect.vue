<script setup lang="ts">
/**
 * 单选下拉 —— 自绘按钮 + popover，外观对齐 BlockEditor 链接 / 跟随下拉：
 *   - 触发按钮：bg-card-2 + line border + ▾，跟原生 select 等高
 *   - 弹层：bg-card-2 + 软阴影
 *   - 选中行：primary-soft 底 + primary-deep 字 + 右侧 ✓
 *   - 任意 hover 行：--dark 底 + cream 字（覆盖选中态）
 *
 * 保留旧 API：modelValue / options / width / disabled / @update:modelValue。
 * 这样上游 9 个引用点不用改就能换皮肤。
 *
 * Teleport popover 到 body —— 避免被父容器 overflow:hidden 裁掉；位置用
 * getBoundingClientRect 计算。点外面 / ESC 关闭。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";

const props = withDefaults(
  defineProps<{
    modelValue: string | number;
    options: Array<{ label: string; value: string | number }>;
    width?: string | number;
    disabled?: boolean;
    placeholder?: string;
  }>(),
  {},
);
const emit = defineEmits<{
  (e: "update:modelValue", v: string | number): void;
}>();

const open = ref(false);
const triggerRef = ref<HTMLButtonElement | null>(null);
const menuRef = ref<HTMLDivElement | null>(null);
const menuPos = ref({ top: 0, left: 0, width: 0, dropUp: false });

const currentLabel = computed(() => {
  const opt = props.options.find((o) => o.value === props.modelValue);
  return opt?.label ?? props.placeholder ?? "";
});

function recomputePos() {
  const el = triggerRef.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  // 估算菜单高度：每项 ~28px，max 280；如果下方剩余空间不够就向上弹。
  const estHeight = Math.min(280, props.options.length * 28 + 8);
  const spaceBelow = window.innerHeight - rect.bottom;
  const dropUp = spaceBelow < estHeight + 8 && rect.top > estHeight + 8;
  menuPos.value = {
    top: dropUp ? rect.top - estHeight - 4 : rect.bottom + 4,
    left: rect.left,
    width: rect.width,
    dropUp,
  };
}

async function toggleOpen() {
  if (props.disabled) return;
  open.value = !open.value;
  if (open.value) {
    await nextTick();
    recomputePos();
  }
}

function close() {
  open.value = false;
}

function select(v: string | number) {
  emit("update:modelValue", v);
  close();
}

function onDocumentMouseDown(e: MouseEvent) {
  if (!open.value) return;
  const t = e.target as Node;
  if (triggerRef.value?.contains(t)) return;
  if (menuRef.value?.contains(t)) return;
  close();
}

function onKey(e: KeyboardEvent) {
  if (!open.value) return;
  if (e.key === "Escape") {
    close();
    e.preventDefault();
  }
}

function onWindowChange() {
  if (open.value) recomputePos();
}

onMounted(() => {
  document.addEventListener("mousedown", onDocumentMouseDown);
  document.addEventListener("keydown", onKey);
  window.addEventListener("scroll", onWindowChange, true);
  window.addEventListener("resize", onWindowChange);
});
onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onDocumentMouseDown);
  document.removeEventListener("keydown", onKey);
  window.removeEventListener("scroll", onWindowChange, true);
  window.removeEventListener("resize", onWindowChange);
});

// modelValue 外部变化时不需要做啥 —— currentLabel 已经响应式。
watch(
  () => props.disabled,
  (d) => {
    if (d) close();
  },
);
</script>

<template>
  <button
    ref="triggerRef"
    type="button"
    :disabled="disabled"
    class="form-select-trigger flex items-center justify-between gap-2 px-3 py-2 text-[13px] outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-60"
    :style="{
      background: 'var(--card-2)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-inner)',
      width: typeof width === 'number' ? `${width}px` : width || 'auto',
      minWidth: width ? '0' : '180px',
      color: currentLabel ? 'var(--ink)' : 'var(--ink-3)',
      textAlign: 'left',
    }"
    @click="toggleOpen"
  >
    <span class="flex-1 truncate text-left">{{ currentLabel || "请选择" }}</span>
    <Icon
      name="arrowDown"
      :size="11"
      :style="{
        opacity: 0.5,
        transition: 'transform 120ms',
        transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
      }"
    />
  </button>

  <Teleport to="body">
    <div
      v-if="open"
      ref="menuRef"
      class="form-select-menu"
      :style="{
        position: 'fixed',
        top: `${menuPos.top}px`,
        left: `${menuPos.left}px`,
        width: `${menuPos.width}px`,
        maxHeight: '280px',
        overflowY: 'auto',
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-inner)',
        boxShadow: '0 6px 18px rgba(28,26,23,0.10)',
        padding: '4px',
        zIndex: 9999,
      }"
      @click.stop
    >
      <button
        v-for="o in options"
        :key="String(o.value)"
        type="button"
        class="form-select-row flex w-full cursor-pointer items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px]"
        :style="{
          borderRadius: '6px',
          background: o.value === modelValue ? 'var(--primary-soft)' : 'transparent',
          color: o.value === modelValue ? 'var(--primary-deep)' : 'var(--ink)',
        }"
        @click="select(o.value)"
      >
        <span class="flex-1 truncate">{{ o.label }}</span>
        <Icon
          v-if="o.value === modelValue"
          name="check"
          :size="11"
          :style="{ color: 'var(--primary-deep)' }"
        />
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.form-select-trigger:hover:not(:disabled) {
  background: var(--card-white, var(--card)) !important;
}
.form-select-trigger:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}
/*
 * 弹层行 hover —— 对齐原生 <select> 的深色 hover；用 !important 压住
 * 选中态的内联 primary-soft 底色。
 */
.form-select-row:hover {
  background: var(--dark) !important;
  color: #fbf7ec !important;
}
.form-select-row:hover :deep(svg) {
  color: #fbf7ec !important;
}
</style>
