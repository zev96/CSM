<script setup lang="ts">
/**
 * Brand-consistent confirmation modal.
 *
 * Singleton — App.vue mounts exactly one of these. `useConfirm.ts` pushes
 * a request into the shared queue and awaits the user's choice. The
 * native OS dialog was visually jarring against the warm paper-card
 * theme; this component reuses the same panel chrome as SkillEditModal
 * (anim-up + bg-bg-inner + radius-card) so the prompt feels in-app.
 */
import Btn from "./Btn.vue";
import Icon from "./Icon.vue";
import { confirmState, resolveConfirm } from "@/composables/useConfirm";

function onCancel() {
  resolveConfirm(false);
}
function onOk() {
  resolveConfirm(true);
}
function onBackdrop(e: MouseEvent) {
  // Click outside the panel = cancel. Use `currentTarget === target` so
  // clicks inside the panel don't bubble up and dismiss it.
  if (e.currentTarget === e.target) onCancel();
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="confirmState.open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      @click="onBackdrop"
    >
      <div
        class="anim-up bg-bg-inner flex flex-col p-6"
        :style="{
          width: '420px',
          maxWidth: '92vw',
          borderRadius: 'var(--radius-card)',
          boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
        }"
        @click.stop
      >
        <!-- Icon + title row -->
        <div class="mb-3 flex items-start gap-3">
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

        <!-- Buttons -->
        <div class="mt-4 flex justify-end gap-2">
          <Btn variant="ghost" small @click="onCancel">
            {{ confirmState.cancelLabel }}
          </Btn>
          <Btn
            :variant="confirmState.kind === 'danger' ? 'solid' : 'solid'"
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
        </div>
      </div>
    </div>
  </Teleport>
</template>
