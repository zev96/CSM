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
  it("固定 4 张卡（3 竞品 + 自己）+ 子分类 + 底部导航", () => {
    const store = useXhs();
    store.$patch({ previewTab: "discover" });
    const w = mount(PhonePreview);
    // 3 竞品 + 自己 1 条 = 4 张卡，均匀双列网格
    expect(w.findAll(".dc-card").length).toBe(4);
    expect(w.findAll(".dc-mine").length).toBe(1);
    expect(w.find(".dc-nav").exists()).toBe(true);
    expect(w.find(".dc-subtabs").exists()).toBe(true);
    w.unmount();
  });

  it("竞品按正文品类词匹配（吸尘器→吸尘器竞品）", () => {
    const store = useXhs();
    store.$patch({ previewTab: "discover", body: "求推荐一款好用的吸尘器" });
    const w = mount(PhonePreview);
    expect(w.find(".dc-feed").text()).toContain("吸尘器");
    w.unmount();
  });

  it("无品类词时默认显示空气净化器竞品", () => {
    const store = useXhs();
    store.$patch({ previewTab: "discover" });
    const w = mount(PhonePreview);
    expect(w.find(".dc-feed").text()).toContain("空气净化器");
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

describe("PhonePreview 笔记页多图", () => {
  it("多图时显示页数角标 + 轮播圆点", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0, previewTab: "note" });
    const w = mount(PhonePreview);
    expect(w.find(".note-pager").text()).toBe("1/3");
    expect(w.findAll(".note-dot").length).toBe(3);
    w.unmount();
  });

  it("封面为第2张时，页数与高亮圆点同步", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b", "c"], coverIndex: 1, previewTab: "note" });
    const w = mount(PhonePreview);
    expect(w.find(".note-pager").text()).toBe("2/3");
    expect(w.findAll(".note-dot-active").length).toBe(1);
    w.unmount();
  });

  it("单图/无图不显示页数和圆点", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a"], previewTab: "note" });
    const w = mount(PhonePreview);
    expect(w.find(".note-pager").exists()).toBe(false);
    expect(w.find(".note-dots").exists()).toBe(false);
    w.unmount();
  });

  it("点右箭头翻到下一张，页数同步（鼠标可翻看）", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0, previewTab: "note" });
    const w = mount(PhonePreview);
    expect(w.find(".note-pager").text()).toBe("1/3");
    await w.find(".note-arrow-r").trigger("click");
    expect(w.find(".note-pager").text()).toBe("2/3");
    await w.find(".note-arrow-r").trigger("click");
    expect(w.find(".note-pager").text()).toBe("3/3");
    w.unmount();
  });

  it("点圆点直接跳到对应图", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0, previewTab: "note" });
    const w = mount(PhonePreview);
    await w.findAll(".note-dot")[2].trigger("click");
    expect(w.find(".note-pager").text()).toBe("3/3");
    w.unmount();
  });
});
