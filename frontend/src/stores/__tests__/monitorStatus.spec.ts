import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";

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
    getMock.mockReset();
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
});
