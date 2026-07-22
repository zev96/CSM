import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import BlockEditor from "../BlockEditor.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

/**
 * 用户真实素材形态：一个目录下的笔记 素材类型 全都一样（产品推荐格式），
 * 区分小节靠「模块」。所以「素材类型」这个默认值在这里是错的。
 */
const ATTRS = [
  { key: "素材类型", note_count: 8, value_count: 1, sample_values: ["产品推荐格式"] },
  {
    key: "模块", note_count: 8, value_count: 3,
    sample_values: ["品牌实力", "核心参数", "核心技术"],
  },
];

function heroCard(sections: any[]) {
  return {
    kind: "hero_brand",
    id: "hero_1",
    title: "DARZ D9",
    source: { type: "notes_query", module: "模板二/DARZD9", filter: {} },
    sections,
    heading_template: "### {tier} TOP{n}. {title}",
  };
}

function mountEditor(block: Record<string, any>) {
  return mount(BlockEditor, {
    props: { modelValue: block, index: 0, total: 1, vaultDirs: [] },
    global: { stubs: { CascadePicker: true } },
  });
}

/** 小节筛选的「字段」下拉 —— 块级筛选那格 hero 不渲染，所以取第一个。 */
function keySelect(w: any) {
  return w
    .findAllComponents(FormSelect)
    .find((c: any) => (c.props("placeholder") ?? "").includes("筛选字段"));
}
function valueSelect(w: any) {
  return w
    .findAllComponents(FormSelect)
    .find((c: any) => (c.props("placeholder") ?? "").includes("筛选值"));
}

describe("BlockEditor — 主推卡小节的筛选", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue({ data: { attributes: ATTRS } });
  });

  it("空筛选显示「不筛选」，不预设「素材类型」这个幽灵默认", async () => {
    // 过去这里默认显示「素材类型」：用户没选过，却会随他填的值一起落库，
    // 配出一个恒空的筛选 —— 生成时报「没有符合条件的素材」。
    const w = mountEditor(heroCard([{ label: "品牌实力", filter: {} }]));
    await flushPromises();
    expect(keySelect(w)!.props("modelValue")).toBe("");
  });

  it("主推卡也会拉 vault 属性 —— 字段下拉列出真实字段", async () => {
    const w = mountEditor(heroCard([{ label: "品牌实力", filter: {} }]));
    await flushPromises();
    expect(getMock).toHaveBeenCalledWith(
      "/api/vault/attributes",
      { params: { module: "模板二/DARZD9" } },
    );
    const values = keySelect(w)!.props("options").map((o: any) => o.value);
    expect(values).toContain("模块");
    expect(values).toContain("__custom__");     // 素材还没写时的手填出口
  });

  it("选中字段后，值下拉给的是该字段的真实取值", async () => {
    const w = mountEditor(heroCard([{ label: "品牌实力", filter: { 模块: "" } }]));
    await flushPromises();
    const opts = valueSelect(w)!.props("options").map((o: any) => o.value);
    expect(opts).toEqual(["品牌实力", "核心参数", "核心技术"]);
  });

  it("换字段要清掉旧值 —— 否则留下一个永远筛不出东西的组合", async () => {
    const w = mountEditor(
      heroCard([{ label: "品牌实力", filter: { 素材类型: "产品推荐格式" } }]),
    );
    await flushPromises();
    keySelect(w)!.vm.$emit("update:modelValue", "模块");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    expect(last.sections[0].filter).toEqual({ 模块: "" });
  });

  it("选中值后按「字段: 值」落库", async () => {
    const w = mountEditor(heroCard([{ label: "品牌实力", filter: { 模块: "" } }]));
    await flushPromises();
    valueSelect(w)!.vm.$emit("update:modelValue", "品牌实力");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    expect(last.sections[0].filter).toEqual({ 模块: "品牌实力" });
  });
});
