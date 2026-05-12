<script setup lang="ts">
/**
 * Bell-icon dropdown — pinned to the top-right of the App utility row.
 *
 * The bell `<IconBtn>` lives in App.vue; this component is conditionally
 * rendered while it's open, mounted as a sibling so click-outside can
 * close it. We don't Teleport because the dropdown is positioned
 * relative to the bell — keeping it inside the utility row's stacking
 * context is simpler than chasing the icon's bbox.
 *
 * Click handlers:
 *   - Click any notification → mark just that one read.
 *   - 「全部已读」→ mark all.
 *   - 「前往设置」→ closes + emits `goto-settings` so the parent can
 *     navigate to Settings → 监测 (where the «通知» toggle lives).
 */
import { computed } from "vue";
import { useRouter } from "vue-router";

import Icon from "./Icon.vue";
import { useNotifications, type Notification } from "@/composables/useNotifications";

defineProps<{ open: boolean }>();
const emit = defineEmits<{
  (e: "close"): void;
}>();

const router = useRouter();
const n = useNotifications();

const hasItems = computed(() => n.items.value.length > 0);

function relativeTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60_000) return "刚刚";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3600_000)} 小时前`;
  return `${Math.floor(diff / 86_400_000)} 天前`;
}

function toneDot(t: Notification["tone"]): string {
  return (
    {
      info: "var(--ink-3)",
      success: "var(--green, #7a9b5e)",
      warn: "var(--yellow, #f5c042)",
      error: "var(--red)",
    } as const
  )[t];
}

function onClickItem(item: Notification) {
  item.read = true;
}

function gotoSettings() {
  emit("close");
  // Special-purpose hash —— SettingsView's onMounted/hash-watcher
  // detects this sentinel, switches to「通用」section, and pops the
  // NotificationPrefsModal open in one shot. We don't reuse the normal
  // section hashes (e.g. `#general`) because that wouldn't auto-open
  // the modal, and we'd want this affordance even if the user is
  // already on the General section.
  router.push({ name: "settings", hash: "#notify-prefs" }).catch(() => {});
}
</script>

<template>
  <div
    v-if="open"
    class="absolute z-30"
    :style="{
      top: '42px',
      right: '52px',
      width: '320px',
      maxHeight: '420px',
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
      :style="{
        height: '40px',
        borderBottom: '1px solid var(--line)',
      }"
    >
      <div class="font-display text-[13px] font-semibold">通知</div>
      <div class="flex items-center gap-3 text-[11.5px]">
        <button
          v-if="hasItems"
          type="button"
          class="hover:underline"
          :style="{ color: 'var(--ink-3)' }"
          @click="n.markAllRead()"
        >
          全部已读
        </button>
        <button
          v-if="hasItems"
          type="button"
          class="hover:underline"
          :style="{ color: 'var(--ink-3)' }"
          @click="n.clear()"
        >
          清空
        </button>
      </div>
    </div>

    <!-- Body -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-if="!hasItems"
        class="flex flex-col items-center justify-center py-10 text-[12px]"
        :style="{ color: 'var(--ink-3)' }"
      >
        <Icon name="bell" :size="22" />
        <div class="mt-2">暂无新通知</div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          监测任务、导出完成、提示信息会出现在这里
        </div>
      </div>
      <ul v-else class="flex flex-col">
        <li
          v-for="item in n.items.value"
          :key="item.id"
          class="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-[rgba(28,26,23,0.04)]"
          :style="{
            borderBottom: '1px solid var(--line)',
            opacity: item.read ? 0.65 : 1,
          }"
          @click="onClickItem(item)"
        >
          <span
            class="mt-1.5 flex-shrink-0"
            :style="{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: toneDot(item.tone),
            }"
          />
          <div class="min-w-0 flex-1">
            <div class="text-[12.5px] font-medium leading-tight">
              {{ item.title }}
            </div>
            <div
              v-if="item.body"
              class="mt-0.5 truncate text-[11.5px]"
              :style="{ color: 'var(--ink-3)' }"
              :title="item.body"
            >
              {{ item.body }}
            </div>
            <div
              class="mt-1 text-[10.5px]"
              :style="{ color: 'var(--ink-4)' }"
            >
              {{ relativeTime(item.at) }}
            </div>
          </div>
        </li>
      </ul>
    </div>

    <!-- Footer -->
    <button
      type="button"
      class="flex items-center justify-center gap-1.5 text-[11.5px]"
      :style="{
        height: '36px',
        borderTop: '1px solid var(--line)',
        color: 'var(--primary)',
      }"
      @click="gotoSettings"
    >
      <Icon name="settings" :size="12" />
      <span>前往通知设置</span>
    </button>
  </div>
</template>
