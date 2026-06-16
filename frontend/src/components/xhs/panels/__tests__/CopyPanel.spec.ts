import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

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

import CopyPanel from "@/components/xhs/panels/CopyPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("CopyPanel", () => {
  it("点击文案片段调 insertAtCursor", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(CopyPanel);
    const first = w.find(".xhs-row");
    await first.trigger("click");
    expect(spy).toHaveBeenCalledWith(first.text().trim());
    w.unmount();
  });
});
