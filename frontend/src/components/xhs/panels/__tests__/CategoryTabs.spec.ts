import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import CategoryTabs from "@/components/xhs/panels/CategoryTabs.vue";

const tabs = [
  { key: "a", name: "甲" },
  { key: "b", name: "乙" },
];

describe("CategoryTabs", () => {
  it("渲染所有分类名", () => {
    const w = mount(CategoryTabs, { props: { tabs, modelValue: "a" } });
    expect(w.text()).toContain("甲");
    expect(w.text()).toContain("乙");
  });

  it("点击分类 emit update:modelValue 带该 key", async () => {
    const w = mount(CategoryTabs, { props: { tabs, modelValue: "a" } });
    await w.findAll("button")[1].trigger("click");
    expect(w.emitted("update:modelValue")?.[0]).toEqual(["b"]);
  });
});
