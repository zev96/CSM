<script setup lang="ts">
/**
 * 通知设置弹窗 — 按类别勾选要不要推送。
 *
 * The master switch lives in Settings → 通用 → 通知 row. This dialog is
 * the "expand" affordance next to that toggle: it shows one row per
 * `NOTIFICATION_CATEGORIES` entry, each bound to a FormToggle that
 * writes through `setCategory` (auto-persisted to localStorage by the
 * composable's deep watch).
 *
 * Disabled when master switch is off — graying out the category toggles
 * makes it visually obvious that they're moot until the master flips on.
 */
import Btn from "./Btn.vue";
import Icon from "./Icon.vue";
import FormToggle from "@/components/forms/FormToggle.vue";
import {
  NOTIFICATION_CATEGORIES,
  useNotifications,
} from "@/composables/useNotifications";

defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "update:open", v: boolean): void }>();

const n = useNotifications();

function close() {
  emit("update:open", false);
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      @click.self="close"
    >
      <div
        class="anim-up bg-bg-inner flex flex-col p-6"
        :style="{
          width: '480px',
          maxWidth: '92vw',
          maxHeight: '85vh',
          borderRadius: 'var(--radius-card)',
          boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
        }"
      >
        <!-- Header -->
        <div class="mb-3 flex items-start justify-between">
          <div>
            <div class="font-display text-[15px] font-semibold">通知设置</div>
            <div
              class="mt-1 text-[11.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              逐项选择要在右上角铃铛收到哪些类型的提醒。
            </div>
          </div>
          <button type="button" @click="close">
            <Icon name="x" :size="16" />
          </button>
        </div>

        <!-- Master switch banner — only visible when OFF, as a reminder. -->
        <div
          v-if="!n.enabled.value"
          class="mb-3 flex items-center gap-2 p-3 text-[11.5px]"
          :style="{
            background: 'rgba(245, 192, 66, 0.12)',
            color: 'var(--ink-2)',
            borderRadius: 'var(--radius-inner)',
            border: '1px solid rgba(245, 192, 66, 0.4)',
          }"
        >
          <Icon name="warn" :size="14" />
          <span>
            通知总开关已关闭 —— 下方的分类设置会被记住，但不会推送，直到
            通用 → 通知 重新打开。
          </span>
        </div>

        <!-- Category rows -->
        <div class="min-h-0 flex-1 overflow-y-auto">
          <div
            v-for="cat in NOTIFICATION_CATEGORIES"
            :key="cat.key"
            class="flex items-center gap-3 py-3"
            :style="{
              borderBottom: '1px solid var(--line)',
              opacity: n.enabled.value ? 1 : 0.55,
            }"
          >
            <div class="min-w-0 flex-1">
              <div class="text-[13px] font-semibold">{{ cat.label }}</div>
              <div
                class="mt-0.5 text-[11.5px]"
                :style="{ color: 'var(--ink-3)' }"
              >
                {{ cat.hint }}
              </div>
            </div>
            <FormToggle
              :model-value="n.categories[cat.key]"
              :disabled="!n.enabled.value"
              @update:model-value="(v) => n.setCategory(cat.key, v)"
            />
          </div>
        </div>

        <!-- Footer -->
        <div class="mt-4 flex justify-end">
          <Btn variant="solid" small @click="close">完成</Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
