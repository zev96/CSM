import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));
vi.mock("@/composables/useConfirm", () => ({
  confirmDialog: vi.fn().mockResolvedValue(true),
}));

import TemplatePanel from "@/components/xhs/panels/TemplatePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.mocked(confirmDialog).mockClear();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("TemplatePanel", () => {
  it("编辑器为空时点击模板直接载入（不弹确认）", async () => {
    const store = useXhs();
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(store.title.length).toBeGreaterThan(0);
    expect(confirmDialog).not.toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器非空时先弹确认，确认后覆盖", async () => {
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(confirmDialog).toHaveBeenCalledTimes(1);
    expect(store.body).not.toBe("已有内容");
    w.unmount();
  });

  it("编辑器非空时取消确认不覆盖", async () => {
    vi.mocked(confirmDialog).mockResolvedValueOnce(false);
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(store.body).toBe("已有内容");
    w.unmount();
  });
});
