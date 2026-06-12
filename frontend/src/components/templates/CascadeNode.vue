<script setup lang="ts">
/**
 * 级联文件夹的单行节点 — 抽出来递归用。
 * 叶子（没有子目录、自己有 path）→ 直接是个可选 row。
 * 中间或混合（有子目录）→ 折叠/展开 row + 子树；自身可选时顶部插入「选择「name」」。
 */
import { computed } from "vue";

import Icon from "@/components/ui/Icon.vue";

defineOptions({ name: "CascadeNode" });

interface TreeNode {
  name: string;
  path: string | null;
  children: TreeNode[];
}

const props = defineProps<{
  node: TreeNode;
  level: number;
  /** 父节点累计的 key 前缀，用于让 expanded set 唯一识别每个内部节点。 */
  prefix: string;
  expanded: Set<string>;
  selected: string;
}>();
const emit = defineEmits<{
  (e: "toggle", key: string): void;
  (e: "select", path: string): void;
}>();

const fullKey = computed(() =>
  props.prefix ? `${props.prefix}/${props.node.name}` : props.node.name,
);
const isLeaf = computed(
  () => props.node.children.length === 0 && props.node.path !== null,
);
const isOpen = computed(() => props.expanded.has(fullKey.value));
const isSelected = computed(
  () => props.node.path !== null && props.selected === props.node.path,
);

function onClick() {
  if (isLeaf.value && props.node.path) {
    emit("select", props.node.path);
  } else {
    emit("toggle", fullKey.value);
  }
}
</script>

<template>
  <li>
    <button
      type="button"
      class="cascade-row flex w-full items-center gap-2 px-2 py-1.5 text-[12.5px]"
      :style="{
        paddingLeft: `${level * 12 + 8}px`,
        borderRadius: '6px',
        background: isSelected ? 'var(--primary-soft)' : 'transparent',
        color: isSelected ? 'var(--primary-deep)' : 'var(--ink)',
      }"
      @click="onClick"
    >
      <Icon
        v-if="!isLeaf"
        name="arrowRight"
        :size="10"
        :style="{
          opacity: 0.5,
          transition: 'transform 120ms',
          transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
        }"
      />
      <Icon
        name="folder"
        :size="12"
        :style="{ color: isSelected ? 'var(--primary-deep)' : 'var(--ink-3)' }"
      />
      <span class="flex-1 truncate text-left">{{ node.name }}</span>
      <Icon
        v-if="isSelected"
        name="check"
        :size="11"
        :style="{ color: 'var(--primary-deep)' }"
      />
    </button>

    <ul v-if="isOpen && !isLeaf">
      <!-- 自身可选（混合）→ 顶部加「选择「name」」 -->
      <li v-if="node.path">
        <button
          type="button"
          class="cascade-row flex w-full items-center gap-2 px-2 py-1.5 text-[11.5px]"
          :style="{
            paddingLeft: `${(level + 1) * 12 + 8}px`,
            borderRadius: '6px',
            color: 'var(--primary-deep)',
          }"
          @click="emit('select', node.path!)"
        >
          <Icon name="check" :size="10" />
          <span>选择「{{ node.name }}」</span>
        </button>
      </li>

      <CascadeNode
        v-for="child in node.children"
        :key="child.name"
        :node="child"
        :level="level + 1"
        :prefix="fullKey"
        :expanded="expanded"
        :selected="selected"
        @toggle="(k) => emit('toggle', k)"
        @select="(p) => emit('select', p)"
      />
    </ul>
  </li>
</template>

<style scoped>
/*
 * 级联节点 hover —— 跟 FormSelect / 链接下拉行同款深色 hover：
 * --dark 底 + cream 字，覆盖选中态的 primary-soft 内联底色。
 */
.cascade-row:hover {
  background: var(--dark) !important;
  color: var(--card) !important;
}
.cascade-row:hover :deep(svg) {
  color: var(--card) !important;
}
</style>
