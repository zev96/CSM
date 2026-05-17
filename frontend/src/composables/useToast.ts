/**
 * Toast / snack-bar notifications.
 *
 * Lives as a Pinia-style store but kept tiny enough that we just expose
 * a singleton ref array — components wire up via the matching
 * ``ToastContainer`` component which renders pinned to the bottom of
 * the paper card.
 *
 * Optional ``actionLabel`` + ``onAction`` add an inline button (used e.g.
 * by mining flows: "AI 未配置 [去设置]"). Clicking the action triggers
 * the callback **and** dismisses the toast.
 */
import { ref } from "vue";

export interface ToastOptions {
  /** Auto-dismiss in ms. 0 = sticky. */
  ttl?: number;
  /** Label for an inline action button (right side of the pill). */
  actionLabel?: string;
  /** Callback fired when the action button is clicked. */
  onAction?: () => void;
}

export interface Toast {
  id: number;
  message: string;
  tone: "info" | "success" | "warn" | "error";
  ttl: number;
  actionLabel?: string;
  onAction?: () => void;
}

const _toasts = ref<Toast[]>([]);
let _seq = 1;

function push(
  message: string,
  tone: Toast["tone"],
  opts: ToastOptions = {},
  defaultTtl = 3200,
): number {
  const id = _seq++;
  const ttl = opts.ttl ?? defaultTtl;
  _toasts.value.push({
    id, message, tone, ttl,
    actionLabel: opts.actionLabel,
    onAction: opts.onAction,
  });
  if (ttl > 0) {
    window.setTimeout(() => dismiss(id), ttl);
  }
  return id;
}

function dismiss(id: number) {
  _toasts.value = _toasts.value.filter((t) => t.id !== id);
}

/**
 * Normalise the second arg: legacy callers pass a bare ``ttl`` number,
 * while new callers pass a ``ToastOptions`` object with an action.
 */
function _coerce(arg?: number | ToastOptions): ToastOptions {
  if (arg == null) return {};
  if (typeof arg === "number") return { ttl: arg };
  return arg;
}

export function useToast() {
  return {
    toasts: _toasts,
    info: (m: string, arg?: number | ToastOptions) => push(m, "info", _coerce(arg)),
    success: (m: string, arg?: number | ToastOptions) => push(m, "success", _coerce(arg)),
    warn: (m: string, arg?: number | ToastOptions) => push(m, "warn", _coerce(arg)),
    error: (m: string, arg?: number | ToastOptions) => push(m, "error", _coerce(arg), 5000),
    dismiss,
  };
}
