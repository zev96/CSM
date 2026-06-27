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

  it("全部入库只提交 high/med，跳过 low", async () => {
    getMock.mockResolvedValue({ data: { folders: [
      { rel_folder: "科普模块/吸尘器/挑选攻略", frontmatter_keys: [],
        defaults: {}, body_shape: "variants", sample_count: 1, material_types: [] },
    ] } });
    postMock.mockResolvedValueOnce({ data: { atoms: [
      { text: "高条", rel_folder: "科普模块/吸尘器/挑选攻略", material_type: "", product: "", keyword: "", filename: "a.md", confidence: "high", warnings: [] },
      { text: "低条", rel_folder: "科普模块/吸尘器/挑选攻略", material_type: "", product: "", keyword: "", filename: "b.md", confidence: "low", warnings: [] },
    ] } });
    postMock.mockResolvedValue({ data: { created_rel: "科普模块/吸尘器/挑选攻略/a.md", content_sha: "s", index_rel: null, index_line: null } });
    const w = mount(AtomizePanel);
    await new Promise((r) => setTimeout(r));
    await w.find("[data-atomize-input]").setValue("一些资料");
    await w.find("[data-atomize-run]").trigger("click");
    await new Promise((r) => setTimeout(r));
    await w.find("[data-atomize-commit-all]").trigger("click");
    await new Promise((r) => setTimeout(r));
    const commitCalls = postMock.mock.calls.filter((c) => c[0] === "/api/vault/commit");
    expect(commitCalls.length).toBe(1);   // 只有 high 卡提交，low 被跳过
  });
});
