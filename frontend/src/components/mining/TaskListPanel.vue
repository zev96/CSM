<script setup lang="ts">
/**
 * 左栏：抓取任务列表面板。
 *
 * - 顶部 sticky header: 「抓取任务」标题 + 钥匙 icon(开 cookie 管理器) +
 *   橙色 + 按钮(新建任务,主入口)
 * - 中间内部独立滚动的任务列表
 * - 空态:点点提示去新建
 *
 * 父组件(MiningView)负责把 store.jobs / currentJobId 和 activeJob.id 传进
 * 来,以及监听 select/new/open-cookies 三个事件。
 */
import Icon from "@/components/ui/Icon.vue";
import TaskListItem from "./TaskListItem.vue";
import type { MiningJob } from "@/stores/mining";

defineProps<{
  jobs: MiningJob[];
  currentJobId: number | null;
  /** id of the running job (SSE-driven), so the item can show progress bar. */
  runningJobId: number | null;
  hasRunningJob: boolean;
}>();

defineEmits<{
  (e: "select", id: number): void;
  (e: "new"): void;
}>();
</script>

<template>
  <aside
    :style="{
      width: '260px',
      flexShrink: 0,
      background: 'var(--card)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-card)',
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
      overflow: 'hidden',
    }"
  >
    <!-- Header -->
    <header
      class="flex items-center justify-between"
      :style="{
        padding: '14px 14px 12px',
        borderBottom: '1px solid var(--line)',
        flexShrink: 0,
      }"
    >
      <div class="font-display font-bold text-[14px]" style="letter-spacing: -0.3px;">
        抓取任务
      </div>
      <button
        type="button"
        :disabled="hasRunningJob"
        @click="$emit('new')"
        class="inline-flex items-center justify-center"
        :style="{
          width: '28px', height: '28px', borderRadius: '8px',
          background: hasRunningJob ? 'rgba(238,106,42,0.40)' : 'var(--primary)',
          color: '#fbf7ec',
          border: 'none',
          cursor: hasRunningJob ? 'not-allowed' : 'pointer',
        }"
        :title="hasRunningJob ? '当前有任务运行中' : '新建抓取任务'"
      >
        <Icon name="plus" :size="14" />
      </button>
    </header>

    <!-- List body (internal scroll) -->
    <div
      :style="{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        padding: '8px',
      }"
    >
      <template v-if="jobs.length > 0">
        <TaskListItem
          v-for="j in jobs"
          :key="j.id"
          :job="j"
          :selected="j.id === currentJobId"
          :running="j.id === runningJobId"
          @select="$emit('select', j.id)"
        />
      </template>

      <!-- Empty state -->
      <div
        v-else
        class="flex flex-col items-center text-center"
        :style="{
          padding: '40px 14px',
          color: 'var(--ink-3)',
        }"
      >
        <span
          :style="{
            width: '40px', height: '40px', borderRadius: '12px',
            background: 'var(--card-2)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            marginBottom: '12px',
          }"
        >
          <Icon name="search" :size="16" />
        </span>
        <div class="font-display font-semibold text-[12.5px]" style="color: var(--ink-2)">
          还没有任务
        </div>
        <div class="text-[11px] mt-1" style="color: var(--ink-3); line-height: 1.5;">
          点上方 + 起一个吧
        </div>
      </div>
    </div>
  </aside>
</template>
