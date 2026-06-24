import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";

import SkillChainPicker from "@/components/article/SkillChainPicker.vue";

const SKILLS = [
  { id: "p1", name: "人设A", role: "persona" },
  { id: "p2", name: "人设B", role: "persona" },
  { id: "h1", name: "去味A", role: "humanize" },
  { id: "plat1", name: "小红书", role: "platform" },
  { id: "plat2", name: "知乎", role: "platform" },
  // unknown role 落到 persona 兜底（后端 role 缺省即 persona）
  { id: "x1", name: "杂项", role: "weird" },
];

function mountPicker(modelValue: string[] = []) {
  return mount(SkillChainPicker, {
    props: { modelValue, skills: SKILLS },
    global: { stubs: { teleport: true } },
  });
}

describe("SkillChainPicker", () => {
  it("每个 role 槽只列对应 role 的 skill + 空「不用」选项", () => {
    const w = mountPicker();
    const vm = w.vm as any;
    const opts = vm.roleOptions as Record<string, Array<{ label: string; value: string }>>;

    // persona 槽：空 + 人设A/人设B（不含 humanize/platform）
    expect(opts.persona[0].value).toBe(""); // 「不用」总在首位
    const personaVals = opts.persona.map((o: any) => o.value);
    expect(personaVals).toContain("p1");
    expect(personaVals).toContain("p2");
    expect(personaVals).not.toContain("h1");
    expect(personaVals).not.toContain("plat1");

    // humanize 槽
    const humVals = opts.humanize.map((o: any) => o.value);
    expect(humVals).toEqual(["", "h1"]);

    // platform 槽
    const platVals = opts.platform.map((o: any) => o.value);
    expect(platVals).toEqual(["", "plat1", "plat2"]);
  });

  it("选出的 skill 按 人设→去AI味→平台 顺序 emit skill_chain（跳过空槽）", async () => {
    const w = mountPicker();
    const vm = w.vm as any;
    // 模拟用户在 FormSelect 上乱序选择：先平台、再人设、humanize 留空。
    // onSlotChange 是 FormSelect @update:model-value 真正调用的处理器。
    vm.onSlotChange("platform", "plat2");
    vm.onSlotChange("persona", "p1");
    await w.vm.$nextTick();

    const emits = w.emitted("update:modelValue");
    expect(emits).toBeTruthy();
    // 末次 emit 是有序链：persona 在前、platform 在后、humanize 空被跳过
    expect(emits!.at(-1)![0]).toEqual(["p1", "plat2"]);
  });

  it("全空槽 → emit []", async () => {
    const w = mountPicker(["p1"]);
    const vm = w.vm as any;
    vm.onSlotChange("persona", "");
    await w.vm.$nextTick();
    expect(w.emitted("update:modelValue")!.at(-1)![0]).toEqual([]);
  });

  it("modelValue 初值回填到对应 role 槽", () => {
    const w = mountPicker(["p2", "h1", "plat1"]);
    const vm = w.vm as any;
    expect(vm.selected.persona).toBe("p2");
    expect(vm.selected.humanize).toBe("h1");
    expect(vm.selected.platform).toBe("plat1");
  });

  it("未知 role 的 skill 兜底进 persona 槽", () => {
    const w = mountPicker();
    const vm = w.vm as any;
    const personaVals = vm.roleOptions.persona.map((o: any) => o.value);
    expect(personaVals).toContain("x1");
  });

  it("渲染 3 个 FormSelect 槽", () => {
    const w = mountPicker();
    // FormSelect 自绘 trigger 是 .form-select-trigger button —— 三槽三个
    expect(w.findAll(".form-select-trigger")).toHaveLength(3);
  });
});
