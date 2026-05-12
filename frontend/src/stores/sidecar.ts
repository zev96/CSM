/**
 * Sidecar bridge: holds the {port, token} handshake from the Tauri shell
 * and exposes a typed axios instance that every other store / view uses.
 *
 * Three boot modes, in order of preference:
 *   1. **Tauri** — the Rust shell spawned the sidecar and pre-populated
 *      `window.__SIDECAR__`. We use those values directly.
 *   2. **Tauri (slow start)** — the shell hasn't injected yet but the
 *      `get_sidecar` invoke command will return the handshake once
 *      ready. We poll briefly.
 *   3. **Browser dev** — no Tauri at all (e.g. `npm run dev` in plain
 *      browser). We fall back to VITE_SIDECAR_URL + VITE_SIDECAR_TOKEN
 *      from .env.local so devs can hit a hand-launched
 *      `python -m csm_sidecar.main` directly.
 */
import axios, { type AxiosInstance } from "axios";
import { defineStore } from "pinia";

interface SidecarState {
  ready: boolean;
  mode: "tauri" | "browser-dev" | "uninitialised";
  baseURL: string;
  token: string;
  error: string | null;
}

export const useSidecar = defineStore("sidecar", {
  state: (): SidecarState => ({
    ready: false,
    mode: "uninitialised",
    baseURL: "",
    token: "",
    error: null,
  }),
  getters: {
    /**
     * Lazily-built axios instance. We rebuild it whenever baseURL/token
     * change — the API surface is small enough that the cost is trivial.
     */
    client(state): AxiosInstance {
      const inst = axios.create({
        baseURL: state.baseURL,
        timeout: 60_000,
        headers: state.token ? { Authorization: `Bearer ${state.token}` } : {},
      });
      // Surface 401s loudly — usually means the token rotated and the
      // store wasn't refreshed; calling code can re-bootstrap.
      inst.interceptors.response.use(
        (r) => r,
        (err) => {
          if (err?.response?.status === 401) {
            console.warn("[CSM] sidecar 401 — token may have rotated");
          }
          return Promise.reject(err);
        },
      );
      return inst;
    },
    /**
     * URL builder for SSE endpoints — EventSource doesn't accept custom
     * headers, so we pass the token in a query string. Sidecar's auth
     * middleware accepts Header *or* ``?token=`` for SSE routes only.
     */
    sseURL(state) {
      return (path: string) => {
        const sep = path.includes("?") ? "&" : "?";
        return `${state.baseURL}${path}${sep}token=${encodeURIComponent(state.token)}`;
      };
    },
  },
  actions: {
    async bootstrap(): Promise<void> {
      const inTauri = await isTauriEnv();

      // Path 1: synchronously injected by Tauri Rust shell.
      if (typeof window !== "undefined" && window.__SIDECAR__) {
        this.applyHandshake(window.__SIDECAR__);
        this.mode = "tauri";
        return;
      }

      // Path 2: Tauri but injection hasn't landed — invoke the Rust command.
      if (inTauri) {
        try {
          const { invoke } = await import("@tauri-apps/api/core");
          const handshake = await invoke<SidecarHandshake>("get_sidecar");
          this.applyHandshake(handshake);
          this.mode = "tauri";
          return;
        } catch (e) {
          // ⚠ 关键：在 Tauri 环境下，绝不 fallback 到 VITE_* env 变量。
          // 之前是 fall-through 到 Path 3，那条路径用的是 .env.local 里
          // 的开发模式 URL/token —— vite build 会把这两个变量烙进 release
          // JS bundle，于是 release app 在 Tauri invoke 任何超时/异常时
          // 都会偷偷把请求发到开发机的 dev sidecar 地址，导致 PATCH 等
          // 写操作在用户那边静默失败（"为什么 onboarding 下一步没反应"）。
          this.error = `Tauri sidecar invoke failed: ${e}`;
          return;
        }
      }

      // Path 3: plain browser — read env vars.
      // 仅当 *不在* Tauri 环境时才允许这条路径，避免 release 安装包不
      // 小心走到这里。
      const url = import.meta.env.VITE_SIDECAR_URL;
      const token = import.meta.env.VITE_SIDECAR_TOKEN;
      if (url && token) {
        this.baseURL = url.replace(/\/$/, "");
        this.token = token;
        this.ready = true;
        this.mode = "browser-dev";
        return;
      }
      this.error =
        "no sidecar handshake — set VITE_SIDECAR_URL / VITE_SIDECAR_TOKEN " +
        "in .env.local for browser dev, or launch via Tauri.";
    },
    applyHandshake(h: SidecarHandshake) {
      this.baseURL = `http://127.0.0.1:${h.port}`;
      this.token = h.token;
      this.ready = true;
      this.error = null;
    },
  },
});

async function isTauriEnv(): Promise<boolean> {
  // Tauri 2 sets ``window.__TAURI_INTERNALS__``. Older variants used
  // ``window.__TAURI__``; check both for safety.
  if (typeof window === "undefined") return false;
  // @ts-expect-error — ambient Tauri globals not in our types
  return Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
}
