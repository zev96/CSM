/**
 * Mirrors the sidecar's AppConfig. We don't bother re-typing every nested
 * field — keeping it loose lets us add a field server-side without
 * having to touch the frontend type, and views read the bits they care
 * about with optional chaining.
 */
import { defineStore } from "pinia";

import { getConfig, patchConfig } from "@/api/client";

interface ConfigState {
  data: Record<string, any> | null;
  loading: boolean;
  error: string | null;
}

export const useConfig = defineStore("config", {
  state: (): ConfigState => ({
    data: null,
    loading: false,
    error: null,
  }),
  actions: {
    // load / patch 都 **重抛** —— 之前的版本只把错存进 this.error 就吃
     // 掉了，导致 caller 拿不到失败信号：
     //   await cfg.patch({user_name: "x"});  // 永远成功
     //   toast.success("已保存");             // 但盘上其实没写
     // 这种 silent-success 是最坑的 UX：用户看到绿色提示，刷新发现没存。
     // 重抛之后 caller 的 try/catch 才有机会 surface 真实错误。
    async load() {
      this.loading = true;
      this.error = null;
      try {
        this.data = await getConfig();
      } catch (e: any) {
        this.error = e?.message ?? String(e);
        throw e;
      } finally {
        this.loading = false;
      }
    },
    async patch(updates: Record<string, unknown>) {
      this.loading = true;
      this.error = null;
      try {
        this.data = await patchConfig(updates);
      } catch (e: any) {
        this.error = e?.message ?? String(e);
        throw e;
      } finally {
        this.loading = false;
      }
    },
  },
});
