<script setup lang="ts">
/**
 * Generic dialog primitive — backdrop + panel + esc/backdrop dismiss +
 * body-scroll lock. Matches the existing ConfirmModal / FailureAlertModal
 * chrome (var(--radius-card), bg-bg-inner, anim-up) so a Dialog reads
 * visually identical to the hand-rolled modals already in the app.
 *
 * Replaces the "every modal hand-rolls fixed inset-0 + backdrop + esc
 * handler" pattern called out in the v0.5.2 audit. New modals should
 * just slot their content into Dialog instead of redoing the chrome.
 *
 * Example
 *   &lt;Dialog v-model:open="show" title="新建任务" size="lg"&gt;
 *     &lt;FormField&gt;...&lt;/FormField&gt;
 *     &lt;template #footer&gt;
 *       &lt;Btn variant="ghost" @click="show = false"&gt;取消&lt;/Btn&gt;
 *       &lt;Btn variant="solid" @click="save"&gt;保存&lt;/Btn&gt;
 *     &lt;/template&gt;
 *   &lt;/Dialog&gt;
 */
import { onUnmounted, watch } from "vue";

import Icon from "./Icon.vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title?: string;
    /** sm = 360 / md = 460 / lg = 640 / xl = 760. Default md. */
    size?: "sm" | "md" | "lg" | "xl";
    /** false disables backdrop click + escape key. Default true. */
    closable?: boolean;
    /**
     * Render the header X button. Default false: most adopters drive
     * dismiss through their own footer buttons (Confirm/Cancel) and don't
     * want the extra X. Set true when you do want it (one-click escape
     * with no decision attached).
     */
    showClose?: boolean;
  }>(),
  { size: "md", closable: true, showClose: false },
);

const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
}>();

const SIZES = { sm: "360px", md: "460px", lg: "640px", xl: "760px" } as const;

function close() {
  if (props.closable) emit("update:open", false);
}

function onBackdrop(e: MouseEvent) {
  // Same pattern as ConfirmModal — only the outermost backdrop fires
  // close; clicks inside the panel are stopped by @click.stop.
  if (e.currentTarget === e.target) close();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && props.open) close();
}

// Body-scroll lock + esc listener mounted lazily when open flips on, so
// the listener overhead is zero when no Dialog is showing.
watch(
  () => props.open,
  (v) => {
    if (v) {
      document.body.style.overflow = "hidden";
      document.addEventListener("keydown", onKeydown);
    } else {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", onKeydown);
    }
  },
);

onUnmounted(() => {
  // Defensive: a Dialog that unmounts while still open (parent v-if'd
  // it away) would otherwise leave body scroll locked forever.
  document.body.style.overflow = "";
  document.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      role="dialog"
      aria-modal="true"
      @click="onBackdrop"
    >
      <div
        class="anim-up bg-bg-inner flex flex-col overflow-hidden p-6"
        :style="{
          width: SIZES[size],
          maxWidth: '92vw',
          maxHeight: '90vh',
          borderRadius: 'var(--radius-card)',
          boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
        }"
        @click.stop
      >
        <div v-if="title || showClose" class="mb-4 flex items-center justify-between gap-3">
          <div v-if="title" class="font-display flex-1 text-[15px] font-semibold leading-tight">
            {{ title }}
          </div>
          <button
            v-if="showClose"
            type="button"
            class="inline-flex flex-shrink-0 items-center justify-center"
            :style="{
              width: '28px',
              height: '28px',
              borderRadius: '8px',
              color: 'var(--ink-3)',
            }"
            aria-label="关闭"
            @click="close"
          >
            <Icon name="x" :size="14" />
          </button>
        </div>

        <div class="flex-1 overflow-y-auto">
          <slot />
        </div>

        <div v-if="$slots.footer" class="mt-5 flex justify-end gap-2">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
