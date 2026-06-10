// frontend/src/components/ui/__tests__/TaskTrayPanel.spec.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
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
vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined) }),
}));

import TaskTrayPanel from "@/components/ui/TaskTrayPanel.vue";
import { useMonitorStatus } from "@/stores/monitorStatus";

describe("TaskTrayPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    getMock.mockReset().mockResolvedValue({ data: { tasks: [] } });
    postMock.mockReset().mockResolvedValue({ data: {} });
  });

  it("open=false 不渲染", () => {
    const w = mount(TaskTrayPanel, { props: { open: false } });
    expect(w.find("div").exists()).toBe(false);
  });

  it("空态显示「暂无后台任务」+ footer 文案", () => {
    const w = mount(TaskTrayPanel, { props: { open: true } });
    expect(w.text()).toContain("暂无后台任务");
    expect(w.text()).toContain("切到任何页面任务都继续跑");
  });

  it("有任务时渲染卡片 + 计数 + 取消按钮；点 ✕ 进入停止中并防重入", async () => {
    const monitor = useMonitorStatus();
    monitor.markRunning(99);
    const w = mount(TaskTrayPanel, { props: { open: true } });
    await flushPromises();
    expect(w.text()).toContain("后台任务");
    expect(w.text()).toContain("任务 #99");
    const btn = w.find("button[title='停止任务']");
    expect(btn.exists()).toBe(true);
    await btn.trigger("click");
    await flushPromises();
    expect(postMock).toHaveBeenCalledWith("/api/monitor/tasks/99/cancel");
    expect(w.text()).toContain("停止中");
    // 防重入：再点不再发请求
    postMock.mockClear();
    const btn2 = w.find("button[title='停止任务']");
    expect(btn2.exists()).toBe(true);
    expect(btn2.attributes("disabled")).toBeDefined();
    await btn2.trigger("click");
    await flushPromises();
    expect(postMock).not.toHaveBeenCalled();
  });
});
