/**
 * Toast / snack-bar notifications.
 *
 * Lives as a Pinia-style store but kept tiny enough that we just expose
 * a singleton ref array — components wire up via the matching
 * ``ToastContainer`` component which renders pinned to the bottom of
 * the paper card.
 */
import { ref } from "vue";

export interface Toast {
  id: number;
  message: string;
  tone: "info" | "success" | "warn" | "error";
  // Auto-dismiss in ms. 0 = sticky.
  ttl: number;
}

const _toasts = ref<Toast[]>([]);
let _seq = 1;

function push(message: string, tone: Toast["tone"], ttl = 3200): number {
  const id = _seq++;
  _toasts.value.push({ id, message, tone, ttl });
  if (ttl > 0) {
    window.setTimeout(() => dismiss(id), ttl);
  }
  return id;
}

function dismiss(id: number) {
  _toasts.value = _toasts.value.filter((t) => t.id !== id);
}

export function useToast() {
  return {
    toasts: _toasts,
    info: (m: string, ttl?: number) => push(m, "info", ttl),
    success: (m: string, ttl?: number) => push(m, "success", ttl),
    warn: (m: string, ttl?: number) => push(m, "warn", ttl),
    error: (m: string, ttl?: number) => push(m, "error", ttl ?? 5000),
    dismiss,
  };
}
