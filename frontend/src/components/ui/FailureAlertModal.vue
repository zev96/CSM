<script setup lang="ts">
/**
 * 全局失败弹窗 —— 复用 ConfirmModal 的视觉骨架（anim-up + bg-bg-inner
 * + radius-card），但语义不同：单方向通知，没有"取消会发生什么"的暗
 * 含。两个出口：关闭 / 重试（仅 retryable=true 时显示）。
 *
 * App.vue 挂一份；useFailureAlert.ts 的 failureState 驱动开合。
 */
import Btn from "./Btn.vue";
import Icon from "./Icon.vue";
import { failureState, resolveFailure } from "@/composables/useFailureAlert";

function onClose() {
  resolveFailure("close");
}
function onRetry() {
  resolveFailure("retry");
}
function onBackdrop(e: MouseEvent) {
  if (e.currentTarget === e.target) onClose();
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="failureState.open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      @click="onBackdrop"
    >
      <div
        class="anim-up bg-bg-inner flex flex-col p-6"
        :style="{
          width: '460px',
          maxWidth: '92vw',
          borderRadius: 'var(--radius-card)',
          boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
        }"
        @click.stop
      >
        <!-- 标题区 -->
        <div class="mb-3 flex items-start gap-3">
          <div
            class="flex flex-shrink-0 items-center justify-center"
            :style="{
              width: '32px',
              height: '32px',
              borderRadius: '999px',
              background: 'rgba(220, 76, 60, 0.12)',
              color: 'var(--red)',
            }"
          >
            <Icon name="warn" :size="16" />
          </div>
          <div class="flex-1 pt-0.5">
            <div class="font-display text-[15px] font-semibold leading-tight">
              {{ failureState.title }}
            </div>
            <div
              class="mt-2 text-[12.5px] leading-relaxed"
              :style="{ color: 'var(--ink-2)' }"
            >
              {{ failureState.message }}
            </div>
          </div>
        </div>

        <!-- 技术细节（折叠式）—— 只在有 detail 时渲染。等宽 pre，
             横向 overflow 滚动，免得堆栈把弹窗拉宽。 -->
        <div
          v-if="failureState.detail"
          class="mt-3 overflow-auto"
          :style="{
            background: 'var(--card-2)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner)',
            padding: '10px 12px',
            maxHeight: '160px',
          }"
        >
          <pre
            class="font-mono text-[11.5px] leading-relaxed"
            :style="{
              color: 'var(--ink-3)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              margin: 0,
            }"
          >{{ failureState.detail }}</pre>
        </div>

        <!-- 按钮 -->
        <div class="mt-5 flex justify-end gap-2">
          <Btn variant="ghost" small @click="onClose">关闭</Btn>
          <Btn
            v-if="failureState.retryable"
            variant="solid"
            small
            @click="onRetry"
          >
            <Icon name="refresh" :size="13" />
            <span>重试</span>
          </Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
