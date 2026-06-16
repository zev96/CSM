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
import { EMOJI } from "@/data/xhs/assets";

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

  it("切换模式后保留各自子分组的选择", async () => {
    const w = mount(EmojiPanel);
    const g2 = EMOJI.curatedGroups[1]; // 选第二个常用分组
    // 在「常用分组」模式下点选第二个子分组
    const subTab = w.findAll("button").find((b) => b.text() === g2.name);
    expect(subTab).toBeTruthy();
    await subTab!.trigger("click");
    // 切到「全部」再切回「常用分组」
    await w.findAll("button").find((b) => b.text() === "全部")!.trigger("click");
    await w.findAll("button").find((b) => b.text() === "常用分组")!.trigger("click");
    // 子分组选择应被保留：网格首个 emoji 是第二组的首个 emoji，而非默认首组的
    expect(w.find(".xhs-emoji").text()).toBe(g2.emojis[0]);
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
