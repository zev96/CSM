import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ sseURL: (p: string) => `MOCK${p}` }),
}));
vi.mock("@/stores/config", () => ({
  useConfig: () => ({ data: { user_name: "测试号" } }),
}));

import PhonePreview from "@/components/xhs/PhonePreview.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("PhonePreview 封面", () => {
  it("无图时不渲染封面 img", () => {
    useXhs();
    const w = mount(PhonePreview);
    expect(w.find("img.xhs-cover-img").exists()).toBe(false);
    w.unmount();
  });

  it("笔记页有图时封面渲染真实 img（按 coverIndex）", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b"], coverIndex: 1, previewTab: "note" });
    const w = mount(PhonePreview);
    const img = w.find("img.xhs-cover-img");
    expect(img.exists()).toBe(true);
    expect(img.attributes("src")).toBe("MOCK/api/xhs/images/b");
    w.unmount();
  });

  it("coverIndex 越界时回退首张", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a"], coverIndex: 5, previewTab: "note" });
    const w = mount(PhonePreview);
    expect(w.find("img.xhs-cover-img").attributes("src")).toBe("MOCK/api/xhs/images/a");
    w.unmount();
  });

  it("发现页有图时封面也渲染真实 img", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b"], coverIndex: 1, previewTab: "discover" });
    const w = mount(PhonePreview);
    const img = w.find("img.xhs-cover-img");
    expect(img.exists()).toBe(true);
    expect(img.attributes("src")).toBe("MOCK/api/xhs/images/b");
    w.unmount();
  });
});
