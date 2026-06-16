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

import DecorationPanel from "@/components/xhs/panels/DecorationPanel.vue";
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

describe("DecorationPanel", () => {
  it("点击装饰符号调 insertAtCursor", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(DecorationPanel);
    const first = w.find(".xhs-deco");
    await first.trigger("click");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(typeof spy.mock.calls[0][0]).toBe("string");
    expect((spy.mock.calls[0][0] as string).length).toBeGreaterThan(0);
    w.unmount();
  });
});
