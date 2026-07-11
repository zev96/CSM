import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { subscribe } from "@/api/client";
import { useNotifications } from "@/composables/useNotifications";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("@/composables/useSystemNotify", () => ({
  useSystemNotify: () => ({ notify: vi.fn().mockResolvedValue(undefined) }),
}));
vi.mock("@/api/client", () => ({ subscribe: vi.fn(() => () => {}) }));

import { useMonitorStatus } from "@/stores/monitorStatus";

describe("monitorStatus — phase / outcome", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset().mockResolvedValue({ data: { running_task_ids: [] } });
    postMock.mockReset();
  });

  it("waiting_chrome_close → phaseOf=waiting_chrome；chrome_closed 清除", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("waiting_chrome_close", { task_id: 7, remaining_s: 60 });
    expect(m.phaseOf(7)).toBe("waiting_chrome");
    m._dispatchSse("chrome_closed", { task_id: 7 });
    expect(m.phaseOf(7)).toBeNull();
  });

  it("captcha_required → phase=captcha；started 清 phase", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("captcha_required", { task_id: 7 });
    expect(m.phaseOf(7)).toBe("captcha");
    m._dispatchSse("started", { task_id: 7 });
    expect(m.phaseOf(7)).toBeNull();
  });

  it("finished → 记 outcome=done、清 running/phase", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("waiting_chrome_close", { task_id: 7 });
    m._dispatchSse("finished", { task_id: 7, progress_total: 10 });
    expect(m.isRunning(7)).toBe(false);
    expect(m.phaseOf(7)).toBeNull();
    expect(m.lastOutcomes[7]).toBe("done");
  });

  it("failed(cancelled by user) → outcome=cancelled；其他 failed → failed", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("failed", { task_id: 7, error: "cancelled by user" });
    expect(m.lastOutcomes[7]).toBe("cancelled");
    m.markRunning(8);
    m._dispatchSse("failed", { task_id: 8, error: "boom" });
    expect(m.lastOutcomes[8]).toBe("failed");
  });

  it("needs_captcha(task_id>0) → phase=captcha；task_id=0（登录窗口复用）忽略", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("needs_captcha", { task_id: 7, keyword: "kw" });
    expect(m.phaseOf(7)).toBe("captcha");
    m._dispatchSse("needs_captcha", { task_id: 0, keyword: "" });
    expect(m.phaseOf(0)).toBeNull();
  });

  it("progress → 清 phase（卡死恢复路径）", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("waiting_chrome_close", { task_id: 7 });
    m._dispatchSse("progress", { task_id: 7, progress_current: 2, progress_total: 10 });
    expect(m.phaseOf(7)).toBeNull();
    expect(m.progressOf(7)).toEqual({ current: 2, total: 10 });
  });

  it("start() 把同一张处理表绑给 subscribe（防再内联漂移）", () => {
    const m = useMonitorStatus();
    m.start();
    const calls = vi.mocked(subscribe).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const handlers = calls[calls.length - 1][1] as Record<string, (d: any) => void>;
    handlers.started({ task_id: 5 });
    expect(m.isRunning(5)).toBe(true);
    m.stop();
  });

  it("hydrate 后不再 running 的任务 phase 被剪掉", async () => {
    const m = useMonitorStatus();
    m._dispatchSse("started", { task_id: 7 }); // started 会清 optimistic grace 戳
    m._dispatchSse("waiting_chrome_close", { task_id: 7 });
    expect(m.phaseOf(7)).toBe("waiting_chrome");
    getMock.mockResolvedValue({ data: { running_task_ids: [] } });
    await m.hydrate();
    expect(m.isRunning(7)).toBe(false);
    expect(m.phaseOf(7)).toBeNull();
  });

  it("重跑（started）清掉上一轮终态记录", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("failed", { task_id: 7, error: "boom" });
    expect(m.lastOutcomes[7]).toBe("failed");
    m._dispatchSse("started", { task_id: 7 });
    expect(m.lastOutcomes[7]).toBeUndefined();
  });
});

describe("monitorStatus — 铃铛通知", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    const n = useNotifications();
    n.clear();
    n.setEnabled(true);
  });

  it("finished → 推 monitor_done 铃铛通知", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m._dispatchSse("finished", { task_id: 7, progress_total: 10 });
    const n = useNotifications();
    expect(n.items.value[0]?.category).toBe("monitor_done");
    expect(n.items.value[0]?.tone).toBe("success");
  });

  it("failed(cancelled by user) → 不推铃铛；普通 failed → 推 monitor_alert", () => {
    const m = useMonitorStatus();
    const n = useNotifications();
    m.markRunning(7);
    m._dispatchSse("failed", { task_id: 7, error: "cancelled by user" });
    expect(n.items.value.length).toBe(0);
    m.markRunning(8);
    m._dispatchSse("failed", { task_id: 8, error: "boom" });
    expect(n.items.value[0]?.category).toBe("monitor_alert");
  });

  it("finished 不带 progress_total 时用 store 里的 progress total 兜底", () => {
    const m = useMonitorStatus();
    m.markRunning(7);
    m.setProgress(7, 3, 10);
    m._dispatchSse("finished", { task_id: 7 });
    const n = useNotifications();
    expect(n.items.value[0]?.body).toContain("共 10 项");
  });

  it("baidu_login_saved(已登录) → 成功铃铛，不弹验证码", () => {
    const m = useMonitorStatus();
    const n = useNotifications();
    m._dispatchSse("baidu_login_saved", { task_id: 0 });
    expect(n.items.value[0]?.tone).toBe("success");
    expect(n.items.value[0]?.title).toContain("登录");
    expect(m.phaseOf(0)).toBeNull();
  });

  it("baidu_login_saved(未检测到登录态) → 警告铃铛", () => {
    const m = useMonitorStatus();
    const n = useNotifications();
    m._dispatchSse("baidu_login_saved", {
      task_id: 0,
      error: "未检测到登录态（副本里没有 BDUSS）",
    });
    expect(n.items.value[0]?.tone).toBe("warn");
  });

  it("risk_control → 清 running + 警告铃铛（带断点进度）", () => {
    const m = useMonitorStatus();
    const n = useNotifications();
    m.markRunning(7);
    m._dispatchSse("risk_control", {
      task_id: 7,
      last_resumed_keyword: 50,
      total_keywords: 93,
    });
    expect(m.isRunning(7)).toBe(false);
    expect(n.items.value[0]?.category).toBe("monitor_alert");
    expect(n.items.value[0]?.body).toContain("93");
  });
});
