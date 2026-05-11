<script setup lang="ts">
/**
 * Traffic-light window controls (macOS style).
 *
 * Three colored circles in a row — red close, yellow minimize, green
 * maximize-or-restore — placed at top-right of the app. Hover reveals
 * the conventional ×/-/+ symbol inside each dot.
 *
 * Close calls window.close() which triggers our Rust CloseRequested
 * hook (lib.rs) — that intercepts and hides to tray instead of exiting.
 * Actual quit only via Tray → 退出.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";

const isMaximized = ref(false);
const hovering = ref(false);
let unlisten: (() => void) | null = null;

// 浏览器 dev 模式下 (npm run dev 不走 Tauri shell) `window.__TAURI_INTERNALS__`
// 不存在 —— `getCurrentWindow()` 内部读 `__TAURI_INTERNALS__.metadata.currentWindow`
// 会抛 "Cannot read properties of undefined (reading 'metadata')"。
// 直接抛出来会被 main.ts 的全局 errorHandler 转成阻塞式 alert，体验崩坏。
// 这里整体做一层 isTauri 守卫：纯浏览器下窗口控件成纯装饰 (不接 IPC)，
// 在 Tauri shell 里才接真实窗口 API。
function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  // @ts-expect-error — ambient Tauri 2 internals not in our types
  return Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
}

async function refresh() {
  if (!isTauri()) return;
  try {
    isMaximized.value = await getCurrentWindow().isMaximized();
  } catch {
    /* 即使 isTauri() 为 true，IPC 也可能尚未就绪 —— 静默忽略，
       下一次 resize 事件会重试 */
  }
}

onMounted(async () => {
  if (!isTauri()) return;
  await refresh();
  try {
    unlisten = await getCurrentWindow().onResized(() => {
      void refresh();
    });
  } catch {
    /* IPC 不可用就不挂监听 */
  }
});

onBeforeUnmount(() => {
  if (unlisten) unlisten();
});

function minimize() {
  if (!isTauri()) return;
  void getCurrentWindow().minimize();
}
async function toggleMax() {
  if (!isTauri()) return;
  const win = getCurrentWindow();
  if (await win.isMaximized()) await win.unmaximize();
  else await win.maximize();
  await refresh();
}
function close() {
  // CloseRequested handler in Rust intercepts and hides to tray.
  if (!isTauri()) {
    // 浏览器模式下没有真窗口可关 —— 友好降级：关 tab 由用户自己点
    // 浏览器的 ×。这里什么都不做，避免误操作。
    return;
  }
  void getCurrentWindow().close();
}
</script>

<template>
  <div
    class="csm-traffic absolute z-30 flex items-center"
    :class="{ 'is-hover': hovering }"
    :style="{ top: '14px', right: '18px', gap: '8px' }"
    @mouseenter="hovering = true"
    @mouseleave="hovering = false"
  >
    <button
      class="csm-dot csm-dot-close"
      title="关闭"
      @click="close"
    >
      <svg viewBox="0 0 10 10" class="csm-glyph">
        <path d="M2.5 2.5 L7.5 7.5 M7.5 2.5 L2.5 7.5" />
      </svg>
    </button>
    <button
      class="csm-dot csm-dot-min"
      title="最小化"
      @click="minimize"
    >
      <svg viewBox="0 0 10 10" class="csm-glyph">
        <path d="M2 5 L8 5" />
      </svg>
    </button>
    <button
      class="csm-dot csm-dot-max"
      :title="isMaximized ? '还原' : '最大化'"
      @click="toggleMax"
    >
      <svg viewBox="0 0 10 10" class="csm-glyph">
        <template v-if="isMaximized">
          <!-- Restore: two slim arrows pointing toward each other (mac convention is two triangles) -->
          <path d="M3 7 L7 3 M7 7 L3 3" stroke-width="1.4" />
        </template>
        <template v-else>
          <path d="M2 5 L8 5 M5 2 L5 8" />
        </template>
      </svg>
    </button>
  </div>
</template>

<style scoped>
.csm-traffic {
  /* Subtle padding so the hover surface extends a bit beyond the dots. */
  padding: 4px 6px;
  border-radius: 999px;
}

.csm-dot {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(0, 0, 0, 0.12);
  /* Glyph hidden by default — group hover reveals it. */
  position: relative;
  transition: transform 0.08s ease, filter 0.12s ease;
}

.csm-dot:active {
  transform: scale(0.94);
}

.csm-dot-close { background: #ff5f57; }
.csm-dot-min   { background: #febc2e; }
.csm-dot-max   { background: #28c840; }

.csm-glyph {
  width: 10px;
  height: 10px;
  opacity: 0;
  fill: none;
  stroke: rgba(0, 0, 0, 0.55);
  stroke-width: 1.2;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: opacity 0.1s ease;
  pointer-events: none;
}

.csm-traffic.is-hover .csm-glyph {
  opacity: 1;
}
</style>
