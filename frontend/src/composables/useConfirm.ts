/**
 * Brand-consistent "are you sure?" prompt — promise API.
 *
 * Why not the native OS dialog: Tauri 2's `plugin-dialog.ask()` renders
 * a stock Win32 MessageBox that visually clashes with the warm paper-card
 * theme (grey chrome, system font). Users flagged it as off-brand, so we
 * render an in-app modal instead via `<ConfirmModal>` mounted once in
 * App.vue.
 *
 * Why not bare `window.confirm`: Tauri 2's WebView intercepts
 * `window.confirm()` and tries to route it to the retired `dialog|confirm`
 * IPC command (replaced by `message` in plugin-dialog 2.x), throwing
 * "Command not found". The destructive-action branch then silently bails.
 *
 * Singleton pattern: only one prompt can be open at a time. A second
 * `confirmDialog()` call while one is already showing is queued — it
 * resolves once the current prompt closes and the queued one is shown.
 */
import { reactive } from "vue";

type ConfirmKind = "danger" | "info";

interface ConfirmRequest {
  title: string;
  message: string;
  okLabel: string;
  cancelLabel: string;
  kind: ConfirmKind;
  resolve: (v: boolean) => void;
}

interface ConfirmState {
  open: boolean;
  title: string;
  message: string;
  okLabel: string;
  cancelLabel: string;
  kind: ConfirmKind;
}

// Reactive — bound directly by ConfirmModal.vue.
export const confirmState = reactive<ConfirmState>({
  open: false,
  title: "确认",
  message: "",
  okLabel: "删除",
  cancelLabel: "取消",
  kind: "danger",
});

const queue: ConfirmRequest[] = [];
let current: ConfirmRequest | null = null;

function showNext() {
  if (current || queue.length === 0) return;
  current = queue.shift()!;
  confirmState.title = current.title;
  confirmState.message = current.message;
  confirmState.okLabel = current.okLabel;
  confirmState.cancelLabel = current.cancelLabel;
  confirmState.kind = current.kind;
  confirmState.open = true;
}

/** Called by ConfirmModal when the user clicks a button or backdrop. */
export function resolveConfirm(value: boolean) {
  if (!current) return;
  const c = current;
  current = null;
  confirmState.open = false;
  c.resolve(value);
  // Defer next prompt one tick so the exit transition (if any) finishes.
  Promise.resolve().then(showNext);
}

export interface ConfirmOptions {
  title?: string;
  okLabel?: string;
  cancelLabel?: string;
  kind?: ConfirmKind;
}

export function confirmDialog(
  message: string,
  opts: ConfirmOptions = {},
): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    queue.push({
      title: opts.title ?? "确认",
      message,
      okLabel: opts.okLabel ?? "删除",
      cancelLabel: opts.cancelLabel ?? "取消",
      kind: opts.kind ?? "danger",
      resolve,
    });
    showNext();
  });
}
