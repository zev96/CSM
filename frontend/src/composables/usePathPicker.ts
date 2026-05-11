/**
 * Tauri-aware file/directory picker.
 *
 * In a Tauri build, calls the dialog plugin (native OS dialog).
 * In plain browser dev (no Tauri), uses ``window.prompt`` as a tolerable
 * stand-in so devs can still wire up settings UIs without the full
 * shell — the prompt accepts a typed path.
 */
import { useToast } from "./useToast";

interface PickOptions {
  /** Window title for the dialog. */
  title?: string;
  /** Pre-fill the picker with this path if present. */
  defaultPath?: string;
  /** Pick a directory rather than a single file. */
  directory?: boolean;
  /** File-mode: comma-separated extension list (no dots) — e.g. "json,md" */
  extensions?: string[];
}

export function usePathPicker() {
  const toast = useToast();

  async function pick(opts: PickOptions = {}): Promise<string | null> {
    if (await isTauri()) {
      try {
        const { open } = await import("@tauri-apps/plugin-dialog");
        const result = await open({
          title: opts.title,
          defaultPath: opts.defaultPath,
          directory: opts.directory ?? false,
          multiple: false,
          filters:
            opts.extensions && !opts.directory
              ? [{ name: "files", extensions: opts.extensions }]
              : undefined,
        });
        // Tauri 2 returns a string for single-pick, null when cancelled.
        if (typeof result === "string") return result;
        return null;
      } catch (e: any) {
        toast.error(`无法打开选择器：${e?.message ?? e}`);
        return null;
      }
    }
    // Browser fallback — manual entry.
    const ans = window.prompt(
      `${opts.title ?? "选择路径"}（在浏览器开发模式下手动填写）`,
      opts.defaultPath ?? "",
    );
    return ans?.trim() || null;
  }

  return { pick };
}

async function isTauri(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  // @ts-expect-error — ambient Tauri global
  return Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
}
