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
    sseURL: (p: string) => `MOCK${p}`,
  }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

import ImagePanel from "@/components/xhs/panels/ImagePanel.vue";
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

describe("ImagePanel", () => {
  it("无图时显示空态、有图时渲染缩略图（sseURL）", async () => {
    const store = useXhs();
    let w = mount(ImagePanel);
    expect(w.findAll("img.xhs-thumb-img")).toHaveLength(0);
    w.unmount();

    store.$patch({ imageIds: ["a", "b"], coverIndex: 0 });
    w = mount(ImagePanel);
    const imgs = w.findAll("img.xhs-thumb-img");
    expect(imgs).toHaveLength(2);
    expect(imgs[0].attributes("src")).toBe("MOCK/api/xhs/images/a");
    w.unmount();
  });

  it("选文件 → 逐个 uploadImage", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "uploadImage").mockResolvedValue();
    const w = mount(ImagePanel);
    const input = w.find('input[type="file"]');
    const f1 = new File([new Uint8Array([1])], "a.png", { type: "image/png" });
    const f2 = new File([new Uint8Array([2])], "b.png", { type: "image/png" });
    Object.defineProperty(input.element, "files", { value: [f1, f2], configurable: true });
    await input.trigger("change");
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenNthCalledWith(1, f1);
    expect(spy).toHaveBeenNthCalledWith(2, f2);
    w.unmount();
  });

  it("点删除 → removeImage(i)", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b"], coverIndex: 0 });
    const spy = vi.spyOn(store, "removeImage");
    const w = mount(ImagePanel);
    await w.findAll(".xhs-thumb-del")[1].trigger("click");
    expect(spy).toHaveBeenCalledWith(1);
    w.unmount();
  });

  it("点设为封面 → setCover(i)", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b"], coverIndex: 0 });
    const spy = vi.spyOn(store, "setCover");
    const w = mount(ImagePanel);
    await w.findAll(".xhs-thumb-cover")[1].trigger("click");
    expect(spy).toHaveBeenCalledWith(1);
    w.unmount();
  });

  it("drop 到另一张 → reorderImages(from,to)", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0 });
    const spy = vi.spyOn(store, "reorderImages");
    const w = mount(ImagePanel);
    const thumbs = w.findAll(".xhs-thumb");
    await thumbs[0].trigger("dragstart");
    await thumbs[2].trigger("drop");
    expect(spy).toHaveBeenCalledWith(0, 2);
    w.unmount();
  });
});
