<script setup lang="ts">
/**
 * Brand-consistent confirmation modal.
 *
 * Singleton — App.vue mounts exactly one of these. `useConfirm.ts` pushes
 * a request into the shared queue and awaits the user's choice. The
 * native OS dialog was visually jarring against the warm paper-card
 * theme; this component reuses the Dialog primitive's chrome (anim-up +
 * bg-bg-inner + radius-card) so the prompt feels in-app.
 *
 * Previously hand-rolled its own Teleport + backdrop + esc handling; now
 * delegates to ``Dialog`` which centralises that boilerplate. Backdrop /
 * Esc dismiss is mapped to "cancel".
 */
import Btn from "./Btn.vue";
import Dialog from "./Dialog.vue";
import Icon from "./Icon.vue";
import { confirmState, resolveConfirm } from "@/composables/useConfirm";

function onCancel() {
  resolveConfirm(false);
}
function onOk() {
  resolveConfirm(true);
}
function onOpenChange(open: boolean) {
  // Dialog emits update:open=false for backdrop click + esc — both
  // map to cancel in confirmation semantics.
  if (!open) onCancel();
}
</script>

<template>
  <!--
    z-[60] 让 confirm 永远盖在普通 Dialog (z-50) 之上 —— 否则在
    CookieManagerModal 里点"登录百度"弹出的确认框会被 cookie 弹窗压住。
    Confirm 是用户决策中断点，本质应该在 modal 栈顶。
  -->
  <Dialog
    :open="confirmState.open"
    size="sm"
    z-class="z-[60]"
    @update:open="onOpenChange"
  >
    <div class="flex items-start gap-3">
      <div
        class="flex flex-shrink-0 items-center justify-center"
        :style="{
          width: '32px',
          height: '32px',
          borderRadius: '999px',
          background:
            confirmState.kind === 'danger'
              ? 'rgba(220, 76, 60, 0.12)'
              : 'var(--primary-soft)',
          color:
            confirmState.kind === 'danger' ? 'var(--red)' : 'var(--primary)',
        }"
      >
        <Icon
          :name="confirmState.kind === 'danger' ? 'trash' : 'warn'"
          :size="16"
        />
      </div>
      <div class="flex-1 pt-0.5">
        <div class="font-display text-[15px] font-semibold leading-tight">
          {{ confirmState.title }}
        </div>
        <div
          class="mt-2 text-[12.5px] leading-relaxed"
          :style="{ color: 'var(--ink-2)' }"
        >
          {{ confirmState.message }}
        </div>
      </div>
    </div>

    <template #footer>
      <Btn variant="ghost" small @click="onCancel">
        {{ confirmState.cancelLabel }}
      </Btn>
      <Btn
        variant="solid"
        small
        :style="
          confirmState.kind === 'danger'
            ? { background: 'var(--red)', color: '#fff' }
            : {}
        "
        @click="onOk"
      >
        {{ confirmState.okLabel }}
      </Btn>
    </template>
  </Dialog>
</template>
