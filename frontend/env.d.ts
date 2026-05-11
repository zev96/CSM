/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<{}, {}, any>;
  export default component;
}

interface SidecarHandshake {
  port: number;
  token: string;
  version: number;
}

interface Window {
  // Populated by Tauri Rust shell on app boot. Browser-only dev (no Tauri)
  // leaves this undefined and the sidecar store falls back to a env-driven
  // dev URL.
  __SIDECAR__?: SidecarHandshake;
}
