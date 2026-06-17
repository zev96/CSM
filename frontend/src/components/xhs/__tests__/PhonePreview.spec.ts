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

describe("PhonePreview 发现页瀑布流", () => {
  it("渲染瀑布流卡片（mock + 自己的笔记）+ 顶部子分类 + 底部导航", () => {
    const store = useXhs();
    store.$patch({ previewTab: "discover" });
    const w = mount(PhonePreview);
    // 5 条 mock + 自己 1 条 = 6 张卡
    expect(w.findAll(".dc-card").length).toBe(6);
    expect(w.find(".dc-nav").exists()).toBe(true);
    expect(w.find(".dc-subtabs").exists()).toBe(true);
    w.unmount();
  });

  it("自己的笔记带「我的」标记，且只有一张", () => {
    const store = useXhs();
    store.$patch({ previewTab: "discover" });
    const w = mount(PhonePreview);
    const mine = w.findAll(".dc-mine");
    expect(mine.length).toBe(1);
    expect(w.find(".dc-badge-mine").text()).toBe("我的");
    w.unmount();
  });

  it("自己的标题混进 feed", () => {
    const store = useXhs();
    store.$patch({ previewTab: "discover", title: "我的测试标题" });
    const w = mount(PhonePreview);
    expect(w.find(".dc-mine").text()).toContain("我的测试标题");
    w.unmount();
  });
});
