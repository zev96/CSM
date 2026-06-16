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

import EmojiPanel from "@/components/xhs/panels/EmojiPanel.vue";
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

describe("EmojiPanel", () => {
  it("点击 emoji 调 insertAtCursor 插入该字形", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(EmojiPanel);
    const e = w.find(".xhs-emoji");
    await e.trigger("click");
    expect(spy).toHaveBeenCalledWith(e.text());
    w.unmount();
  });

  it("切到「小红书代码」模式，点击插入代码文本（以 [ 开头）", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(EmojiPanel);
    const codeTab = w.findAll("button").find((b) => b.text() === "小红书代码");
    expect(codeTab).toBeTruthy();
    await codeTab!.trigger("click");
    const codeBtn = w.find(".xhs-code");
    await codeBtn.trigger("click");
    expect(spy).toHaveBeenCalledTimes(1);
    expect((spy.mock.calls[0][0] as string).startsWith("[")).toBe(true);
    w.unmount();
  });
});
