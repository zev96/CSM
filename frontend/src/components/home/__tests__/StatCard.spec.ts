import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";

import StatCard from "@/components/home/StatCard.vue";

// jsdom 把内联 :style 的 hex 归一化成 rgb，所以断言 rgb 数字而非 hex 字面。
const GREEN = "221, 231, 210"; // #dde7d2
const RED = "243, 211, 205"; // #f3d3cd

describe("StatCard", () => {
  it("shows value and a green up pill when delta>0", () => {
    const w = mount(StatCard, {
      props: { category: "百度 SEO", value: 5, delta: 2, loaded: true },
    });
    expect(w.text()).toContain("5");
    expect(w.text()).toContain("2");
    expect(w.html()).toContain(GREEN);
  });

  it("shows a red pill when delta<0", () => {
    const w = mount(StatCard, {
      props: { category: "x", value: 3, delta: -1, loaded: true },
    });
    expect(w.html()).toContain(RED);
    expect(w.text()).toContain("1");
  });

  it("hides the pill when delta is null", () => {
    const w = mount(StatCard, {
      props: { category: "x", value: 0, delta: null, loaded: true },
    });
    expect(w.html()).not.toContain(GREEN);
    expect(w.html()).not.toContain(RED);
  });

  it("shows dash before loaded", () => {
    const w = mount(StatCard, {
      props: { category: "x", value: 9, delta: null, loaded: false },
    });
    expect(w.text()).toContain("—");
  });
});
