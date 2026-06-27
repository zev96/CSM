import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import AtomizePanel from "@/components/materials/AtomizePanel.vue";

describe("AtomizePanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
    getMock.mockResolvedValue({ data: { folders: [] } });   // loadFolders
  });

  it("拆条渲染 N 卡且 low 置顶", async () => {
    postMock.mockResolvedValueOnce({ data: { atoms: [
      { text: "高条", rel_folder: null, material_type: "", product: "", keyword: "", filename: "a.md", confidence: "high", warnings: [] },
      { text: "低条", rel_folder: null, material_type: "", product: "", keyword: "", filename: "b.md", confidence: "low", warnings: [] },
    ] } });
    const w = mount(AtomizePanel);
    await new Promise((r) => setTimeout(r));
    await w.find("[data-atomize-input]").setValue("一些资料");
    await w.find("[data-atomize-run]").trigger("click");
    await new Promise((r) => setTimeout(r));
    const cards = w.findAll("[data-atom-card]");
    expect(cards.length).toBe(2);
    expect(cards[0].attributes("data-confidence")).toBe("low");   // low 置顶
  });

  it("空输入不调拆条", async () => {
    const w = mount(AtomizePanel);
    await new Promise((r) => setTimeout(r));
    await w.find("[data-atomize-run]").trigger("click");
    expect(postMock).not.toHaveBeenCalled();
  });
});
