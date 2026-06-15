import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";

import Select from "../Select.vue";

const OPTIONS = [
  { value: "douyin", label: "抖音" },
  { value: "kuaishou", label: "快手" },
];

describe("Select", () => {
  it("默认 min-width 120px —— 不破坏既有使用方（表单等宽下拉）", () => {
    const w = mount(Select, {
      props: { modelValue: "douyin", options: OPTIONS },
    });
    expect(w.find("select").element.style.minWidth).toBe("120px");
  });

  it("minWidth prop 覆盖默认 —— 窄左栏工具栏（评论页平台下拉）防溢出", () => {
    const w = mount(Select, {
      props: { modelValue: "douyin", options: OPTIONS, minWidth: "76px" },
    });
    expect(w.find("select").element.style.minWidth).toBe("76px");
  });
});
