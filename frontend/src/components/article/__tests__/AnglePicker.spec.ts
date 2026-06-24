import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

// 角度受控词表 —— 镜像 GET /api/angle/taxonomy 的响应形状。
const TAXONOMY = {
  tones: [
    { key: "口语", hint: "口语提示" },
    { key: "专业", hint: "专业提示" },
    { key: "极客", hint: "极客提示" },
  ],
  dimensions: [
    { key: "动力系统", label: "吸力·电机" },
    { key: "过滤系统", label: "过滤·HEPA" },
    { key: "防缠绕技术", label: "防缠绕" },
    { key: "绿光显尘", label: "绿光显尘" },
    { key: "机身重量", label: "机身重量" },
    { key: "尘杯容量", label: "尘杯容量" },
    { key: "续航时间", label: "续航" },
    { key: "刷头配置", label: "刷头配件" },
    { key: "噪音大小", label: "噪音·静音" },
    { key: "维护耗材", label: "维护耗材" },
  ],
  audiences: [
    "铲屎官", "过敏人群", "宝妈", "老年人", "大户型用户", "上班族",
    "小户型用户", "租房党", "有地毯家庭", "硬地板用户", "科技爱好者",
    "性价比党", "家居爱好者", "精致生活人群", "多层住宅用户", "通用人群",
  ],
  presets: [
    { name: "宝妈/儿童健康", template_id: null, audience: "宝妈", sellpoints: ["绿光显尘", "过滤系统"], tone: "口语" },
    { name: "测评博主", template_id: null, audience: null, sellpoints: [], tone: "专业" },
    { name: "技术维修视角", template_id: "tpl-geek", audience: null, sellpoints: [], tone: "极客" },
    { name: "选购困难", template_id: null, audience: "通用人群", sellpoints: [], tone: "口语" },
  ],
};

const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock } }),
}));

import AnglePicker from "@/components/article/AnglePicker.vue";

function mountPicker(props: Record<string, any> = {}) {
  return mount(AnglePicker, {
    props: { modelValue: null, title: "", ...props },
    // FormSelect teleports its popover to body — stub teleport so the
    // option rows render inline for findAll traversal.
    global: { stubs: { teleport: true } },
  });
}

describe("AnglePicker", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset();
    getMock.mockResolvedValue({ data: TAXONOMY });
  });

  it("拉词表并渲染 4 预设 / 10 维度 chips / 3 语调 / 16 人群", async () => {
    const w = mountPicker();
    await flushPromises();
    expect(getMock).toHaveBeenCalledWith("/api/angle/taxonomy");
    // 预设按钮
    for (const p of TAXONOMY.presets) expect(w.text()).toContain(p.name);
    // 卖点维度 chips（用 data-attr 数维度数量）
    expect(w.findAll("[data-sellpoint]")).toHaveLength(10);
    // 人群选项 = 16 人群 + 空「不限」= 17（真实选项在 teleport 的 FormSelect
    // 弹层里，组件测试不展开它；直接断言组件的 audienceOptions computed）。
    expect((w.vm as any).audienceOptions).toHaveLength(17);
  });

  it("点预设填充 facet 并 emit update:modelValue", async () => {
    const w = mountPicker();
    await flushPromises();
    // 点「宝妈/儿童健康」预设
    const preset = w.findAll("[data-preset]").find((b) => b.text().includes("宝妈/儿童健康"));
    expect(preset).toBeTruthy();
    await preset!.trigger("click");
    const emitted = w.emitted("update:modelValue");
    expect(emitted).toBeTruthy();
    expect(emitted![emitted!.length - 1][0]).toEqual({
      audience: "宝妈",
      sellpoints: ["绿光显尘", "过滤系统"],
      tone: "口语",
    });
  });

  it("预设有 template_id 时 emit pick-template", async () => {
    const w = mountPicker();
    await flushPromises();
    const preset = w.findAll("[data-preset]").find((b) => b.text().includes("技术维修视角"));
    await preset!.trigger("click");
    expect(w.emitted("pick-template")).toBeTruthy();
    expect(w.emitted("pick-template")![0][0]).toBe("tpl-geek");
  });

  it("预设 template_id 为 null 时不 emit pick-template", async () => {
    const w = mountPicker();
    await flushPromises();
    const preset = w.findAll("[data-preset]").find((b) => b.text().includes("测评博主"));
    await preset!.trigger("click");
    expect(w.emitted("pick-template")).toBeFalsy();
  });

  it("点卖点 chip 切换选中并 emit 含该维度的 angle", async () => {
    const w = mountPicker();
    await flushPromises();
    const chip = w.findAll("[data-sellpoint]").find((c) => c.attributes("data-sellpoint") === "防缠绕技术");
    expect(chip).toBeTruthy();
    await chip!.trigger("click");
    const emitted = w.emitted("update:modelValue");
    expect(emitted).toBeTruthy();
    const last = emitted![emitted!.length - 1][0] as any;
    expect(last.sellpoints).toContain("防缠绕技术");
  });

  it("再点已选卖点 chip 取消选中", async () => {
    const w = mountPicker({
      modelValue: { audience: null, sellpoints: ["防缠绕技术"], tone: null },
    });
    await flushPromises();
    const chip = w.findAll("[data-sellpoint]").find((c) => c.attributes("data-sellpoint") === "防缠绕技术");
    await chip!.trigger("click");
    const emitted = w.emitted("update:modelValue");
    const last = emitted![emitted!.length - 1][0] as any;
    expect(last.sellpoints).not.toContain("防缠绕技术");
  });

  it("标题 input emit update:title", async () => {
    const w = mountPicker();
    await flushPromises();
    const input = w.find("[data-angle-title] input");
    expect(input.exists()).toBe(true);
    await input.setValue("我的标题");
    expect(w.emitted("update:title")).toBeTruthy();
    expect(w.emitted("update:title")!.some((e) => e[0] === "我的标题")).toBe(true);
  });

  it("「生成候选」按钮（showGenTitles）emit gen-titles", async () => {
    // 按钮默认隐藏（Hero 上下文未接线）；显式开启才渲染 + 可点。
    const w = mountPicker({ showGenTitles: true });
    await flushPromises();
    const btn = w.findAll("button").find((b) => b.text().includes("生成候选"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    expect(w.emitted("gen-titles")).toBeTruthy();
  });
});
