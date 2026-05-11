<script setup lang="ts">
/**
 * 级联文件夹选择器 —— 严格对齐 csm_gui/widgets/cascade_picker.py 的 UX：
 *   - 按钮里显示 [文件夹图标] + 当前路径（或 placeholder）
 *   - 点击后弹出树状菜单，逐级展开
 *   - 叶子节点点击即选中，混合节点（自身可选 + 还有子目录）顶部多一行
 *     「选择「当前节点」」
 *
 * 数据来源由父组件决定 —— 这里只接受一个扁平 `dirs` 字符串数组
 * （形如 ["营销资料库/标题模块", "营销资料库/段落库", "竞品/吸尘器"]），
 * 自己组装成嵌套树。这样可以复用在 vault dirs / future 其他 picker 上。
 */
import { computed, onMounted, onBeforeUnmount, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";
import CascadeNode from "./CascadeNode.vue";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    dirs: string[];
    placeholder?: string;
  }>(),
  { placeholder: "选择数据库文件夹" },
);
const emit = defineEmits<{
  (e: "update:modelValue", v: string): void;
}>();

const open = ref(false);
// 已展开的子菜单路径 — 多级展开时用来记录「悬浮 / 点击哪个父」。
const expanded = ref<Set<string>>(new Set());

interface TreeNode {
  name: string;
  /** 完整相对路径，叶子或可选自身的父节点都有；纯中间目录可能没有 */
  path: string | null;
  children: TreeNode[];
}

const tree = computed<TreeNode[]>(() => {
  // root.children 才是顶级目录数组；root.path 用 null 占位。
  const root: TreeNode = { name: "", path: null, children: [] };
  for (const full of props.dirs) {
    const parts = full.split("/");
    let cursor = root;
    let acc: string[] = [];
    for (const part of parts) {
      acc.push(part);
      let child = cursor.children.find((c) => c.name === part);
      if (!child) {
        child = { name: part, path: null, children: [] };
        cursor.children.push(child);
      }
      cursor = child;
    }
    cursor.path = full;
  }
  return root.children;
});

const display = computed(() => {
  const cur = props.modelValue ?? "";
  if (!cur) return props.placeholder;
  // 紧凑显示最后两段，跟 PyQt 版一致
  const parts = cur.split("/");
  return parts.length > 1 ? parts.slice(-2).join(" / ") : cur;
});

function toggleOpen() {
  open.value = !open.value;
  if (!open.value) expanded.value = new Set();
}

function select(path: string) {
  emit("update:modelValue", path);
  open.value = false;
  expanded.value = new Set();
}

function toggleExpand(key: string) {
  const next = new Set(expanded.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  expanded.value = next;
}

// 点击外部关闭弹层
const wrapperRef = ref<HTMLElement | null>(null);
function onDocumentClick(e: MouseEvent) {
  if (!open.value) return;
  if (!wrapperRef.value) return;
  if (!wrapperRef.value.contains(e.target as Node)) {
    open.value = false;
    expanded.value = new Set();
  }
}
onMounted(() => document.addEventListener("mousedown", onDocumentClick));
onBeforeUnmount(() => document.removeEventListener("mousedown", onDocumentClick));
</script>

<template>
  <div ref="wrapperRef" class="relative">
    <button
      type="button"
      class="flex w-full items-center gap-2 px-3 py-2 text-[12.5px]"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-inner)',
        color: modelValue ? 'var(--ink)' : 'var(--ink-3)',
      }"
      @click="toggleOpen"
    >
      <Icon name="folder" :size="13" :style="{ color: 'var(--ink-3)' }" />
      <span class="flex-1 truncate text-left">{{ display }}</span>
      <Icon name="arrowDown" :size="11" :style="{ opacity: 0.5 }" />
    </button>

    <!--
      皮肤跟 FormSelect / 链接下拉对齐：bg-card-2 + 深色 hover 行。
      hover 样式由 CascadeNode 内的 .cascade-row:hover 提供。
    -->
    <div
      v-if="open"
      class="absolute z-20 mt-1 w-full"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-inner)',
        boxShadow: '0 6px 18px rgba(28,26,23,0.10)',
        maxHeight: '280px',
        overflowY: 'auto',
        padding: '4px',
      }"
      @click.stop
    >
      <div
        v-if="!tree.length"
        class="px-3 py-2 text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        没有可用目录。先到「设置」里指定 Vault 根目录。
      </div>

      <ul v-else>
        <CascadeNode
          v-for="node in tree"
          :key="node.name"
          :node="node"
          :level="0"
          :prefix="''"
          :expanded="expanded"
          :selected="modelValue"
          @toggle="toggleExpand"
          @select="select"
        />
      </ul>
    </div>
  </div>
</template>
