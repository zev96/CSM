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

import NoteEditor from "@/components/xhs/NoteEditor.vue";
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

describe("NoteEditor 工具条", () => {
  it("点击「表情」快捷切到 emoji 面板", async () => {
    const store = useXhs();
    const w = mount(NoteEditor);
    const btn = w.findAll(".xhs-tool-btn").find((b) => b.text().includes("表情"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    expect(store.activePanel).toBe("emoji");
    w.unmount();
  });
});
