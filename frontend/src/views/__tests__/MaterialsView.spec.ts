import { mount } from "@vue/test-utils";
import { describe, it, expect, vi, beforeAll } from "vitest";

// SplitPane reads window.matchMedia in onMounted; jsdom lacks it. Stub it
// returning matches:true (wide layout) — same idiom as SplitPane.spec.ts.
beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true,
    media: q,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    onchange: null,
    dispatchEvent() { return false; },
  }));
});

const listMock = vi.fn();
const selectMock = vi.fn();
const state: any = {
  models: [
    { model: "CEWEYDS18", brand: "CEWEY", role: "主推", coverage: { has_specs: true, has_tests: false, script_dimensions: 2 } },
    { model: "戴森V12", brand: "戴森", role: "竞品", coverage: { has_specs: true } },
  ],
  loading: false, error: null, selectedModel: null, detail: null, detailLoading: false,
  list: listMock, select: selectMock,
};
vi.mock("@/stores/materials", () => ({ useMaterials: () => state }));
vi.mock("@/stores/factsChanges", () => ({
  useFactsChanges: () => ({ pull: vi.fn().mockResolvedValue([]), isStale: () => false }),
}));

import MaterialsView from "@/views/MaterialsView.vue";

describe("MaterialsView", () => {
  it("挂载即拉列表 + 渲染主推/竞品分组行", () => {
    const w = mount(MaterialsView);
    expect(listMock).toHaveBeenCalled();
    // V2：型号行剥离品牌前缀显示（戴森V12 → 品牌头「戴森」+ 行「V12」），
    // 按 data-model 断言行存在（不依赖跨元素文本连续）。
    expect(w.find("[data-model='CEWEYDS18']").exists()).toBe(true);
    expect(w.find("[data-model='戴森V12']").exists()).toBe(true);
    expect(w.text()).toContain("主推");
    expect(w.text()).toContain("竞品");
  });

  it("点型号行调 select(model)", async () => {
    const w = mount(MaterialsView);
    await w.find("[data-model='CEWEYDS18']").trigger("click");
    expect(selectMock).toHaveBeenCalledWith("CEWEYDS18");
  });

  it("无选中显示空态提示", () => {
    const w = mount(MaterialsView);
    expect(w.text()).toContain("选择左侧型号");
  });
});
