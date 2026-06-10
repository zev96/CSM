<script setup lang="ts">
/**
 * 全局任务托盘浮层 —— 定位/视觉范式复刻 NotificationDropdown（侧栏底部
 * 锚定、向 nav 右侧弹出、不 Teleport）。数据全部来自 useTaskTray()，
 * 本组件零拉取、零 SSE。
 */
import { useRouter } from "vue-router";

import Icon from "./Icon.vue";
import ProgressBar from "./ProgressBar.vue";
import { useToast } from "@/composables/useToast";
import { useTaskTray, type TrayFinished, type TrayTask } from "@/stores/taskTray";

defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "close"): void }>();

const router = useRouter();
const tray = useTaskTray();
const toast = useToast();

function gotoTask(t: TrayTask | TrayFinished) {
  emit("close");
  router.push(t.route).catch(() => {});
}

async function onCancel(t: TrayTask) {
  if (tray.cancellingKeys.has(t.key)) return;
  try {
    await tray.cancelTask(t);
    toast.info(`已请求停止 ${t.title}`);
  } catch {
    toast.error("取消失败，请稍后重试");
  }
}

function pct(p: number | null): string {
  return p == null ? "" : `${Math.round(p * 100)}%`;
}

function metaText(t: TrayTask): string {
  if (tray.cancellingKeys.has(t.key)) return "停止中…";
  if (t.state === "waiting") return "排队中";
  return [pct(t.progress), t.etaText].filter(Boolean).join(" · ");
}

function outcomeMeta(o: TrayFinished["outcome"]): { icon: string; color: string; label: string } {
  if (o === "done") return { icon: "check", color: "var(--green)", label: "已完成" };
  if (o === "cancelled") return { icon: "x", color: "var(--ink-3)", label: "已取消" };
  return { icon: "alert", color: "var(--red)", label: "失败" };
}
</script>

<template>
  <div
    v-if="open"
    class="absolute z-50"
    :style="{
      bottom: '0',
      left: '52px',
      width: '340px',
      maxHeight: '480px',
      background: 'var(--bg-inner)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius-card)',
      boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
    }"
    @click.stop
  >
    <!-- Header -->
    <div
      class="flex items-center justify-between px-4"
      :style="{ height: '40px', borderBottom: '1px solid var(--line)' }"
    >
      <div class="font-display text-[13px] font-semibold">
        后台任务<span v-if="tray.runningCount > 0" :style="{ color: 'var(--ink-3)' }">
          · {{ tray.runningCount }}</span>
      </div>
      <button
        v-if="tray.recentFinished.length > 0"
        type="button"
        class="hover:underline text-[11.5px]"
        :style="{ color: 'var(--ink-3)' }"
        @click="tray.clearFinished()"
      >
        清除已完成
      </button>
    </div>

    <!-- Body -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-if="tray.runningTasks.length === 0 && tray.recentFinished.length === 0"
        class="flex flex-col items-center justify-center py-10 text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        <Icon name="zap" :size="22" />
        <div class="mt-2">暂无后台任务</div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          监测 / 引流 / 生成任务运行时会出现在这里
        </div>
      </div>

      <ul v-else class="flex flex-col">
        <!-- 运行中 -->
        <li
          v-for="t in tray.runningTasks"
          :key="t.key"
          class="cursor-pointer px-4 py-3 hover:bg-[rgba(28,26,23,0.04)]"
          :style="{ borderBottom: '1px solid var(--line)' }"
          @click="gotoTask(t)"
        >
          <div class="flex items-start gap-2.5">
            <span
              class="mt-0.5 flex-shrink-0"
              :style="{ color: t.state === 'captcha' ? 'var(--red)' : 'var(--primary)' }"
            >
              <Icon :name="t.icon" :size="15" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="truncate text-[12.5px] font-medium leading-tight" :title="t.title">{{ t.title }}</div>
              <div
                class="mt-0.5 truncate text-[11.5px]"
                :title="t.subtitle"
                :style="{ color: t.state === 'captcha' ? 'var(--red)' : 'var(--ink-3)' }"
              >
                {{ t.subtitle }}
              </div>
            </div>
            <button
              v-if="t.cancellable"
              type="button"
              title="停止任务"
              class="tray-cancel inline-flex flex-shrink-0 items-center justify-center"
              :disabled="tray.cancellingKeys.has(t.key)"
              @click.stop="onCancel(t)"
            >
              <Icon name="x" :size="13" />
            </button>
          </div>
          <div class="mt-2 flex items-center gap-2">
            <div class="flex-1">
              <ProgressBar
                :value="t.state === 'waiting' ? 0 : t.progress"
                :height="5"
                :tone="t.state === 'captcha' ? 'red' : 'primary'"
              />
            </div>
            <div class="flex-shrink-0 text-[10.5px]" :style="{ color: 'var(--ink-4)' }">
              {{ metaText(t) }}
            </div>
          </div>
        </li>

        <!-- 最近完成 -->
        <li
          v-if="tray.recentFinished.length > 0"
          class="px-4 pb-1 pt-2.5 text-[10.5px]"
          :style="{ color: 'var(--ink-4)' }"
        >
          最近完成
        </li>
        <li
          v-for="f in tray.recentFinished"
          :key="`fin-${f.key}-${f.finishedAt}`"
          class="flex cursor-pointer items-center gap-2.5 px-4 py-2.5 hover:bg-[rgba(28,26,23,0.04)]"
          :style="{ borderBottom: '1px solid var(--line)', opacity: 0.75 }"
          @click="gotoTask(f)"
        >
          <span class="flex-shrink-0" :style="{ color: outcomeMeta(f.outcome).color }">
            <Icon :name="outcomeMeta(f.outcome).icon" :size="14" />
          </span>
          <div class="min-w-0 flex-1 truncate text-[12px]" :title="f.title">{{ f.title }}</div>
          <div class="flex-shrink-0 text-[10.5px]" :style="{ color: 'var(--ink-4)' }">
            {{ outcomeMeta(f.outcome).label }}
          </div>
        </li>
      </ul>
    </div>

    <!-- Footer -->
    <div
      class="flex items-center justify-center text-[10.5px]"
      :style="{ height: '32px', borderTop: '1px solid var(--line)', color: 'var(--ink-4)' }"
    >
      切到任何页面任务都继续跑 · 完成后通知
    </div>
  </div>
</template>

<style scoped>
/* 可被 hover 改的属性必须放 scoped CSS（inline style 会压死 :hover）。 */
.tray-cancel {
  width: 22px;
  height: 22px;
  border-radius: 8px;
  color: var(--ink-3);
  transition: background 0.15s ease, color 0.15s ease;
}
.tray-cancel:hover {
  background: rgba(28, 26, 23, 0.06);
  color: var(--red);
}
.tray-cancel:disabled {
  opacity: 0.45;
  cursor: default;
}
.tray-cancel:disabled:hover {
  background: transparent;
  color: var(--ink-3);
}
</style>
