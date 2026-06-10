// frontend/src/composables/__tests__/notifications.spec.ts
import { describe, it, expect, beforeEach, vi } from "vitest";

import {
  NOTIFICATION_CATEGORIES,
  useNotifications,
} from "@/composables/useNotifications";

describe("notification categories — 任务托盘新增", () => {
  beforeEach(() => {
    localStorage.clear();
    const n = useNotifications();
    n.clear();
    n.setEnabled(true);
  });

  it("注册了 monitor_done / mining_done 两个类别", () => {
    const keys = NOTIFICATION_CATEGORIES.map((c) => c.key);
    expect(keys).toContain("monitor_done");
    expect(keys).toContain("mining_done");
  });

  it("旧 localStorage 没有新类别 key 时默认放行（向前兼容）", async () => {
    // loadCategories 在模块加载时执行一次 —— 必须 resetModules + 动态
    // import 才能让它对着「旧版本写的 blob」重跑。
    localStorage.setItem(
      "csm.notify.categories.v1",
      JSON.stringify({ system: true }), // 旧 blob，缺 mining_done key
    );
    vi.resetModules();
    const mod = await import("@/composables/useNotifications");
    const n = mod.useNotifications();
    n.clear();
    n.setEnabled(true);
    const id = n.push("引流任务完成", { category: "mining_done" });
    expect(id).not.toBeNull();
  });
});
