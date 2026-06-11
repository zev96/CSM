import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";

import StatCard from "@/components/home/StatCard.vue";

// pillStyle 现在输出 CSS token，断言变量名而非字面 rgb。
const GREEN_TOKEN = "var(--green-soft)";
const RED_TOKEN = "var(--red-soft)";

describe("StatCard", () => {
  it("shows value and a green up pill when delta>0", () => {
    const w = mount(StatCard, {
      props: { category: "百度 SEO", value: 5, delta: 2, loaded: true },
    });
    expect(w.text()).toContain("5");
    expect(w.text()).toContain("2");
    expect(w.html()).toContain(GREEN_TOKEN);
  });

  it("shows a red pill when delta<0", () => {
    const w = mount(StatCard, {
      props: { category: "x", value: 3, delta: -1, loaded: true },
    });
    expect(w.html()).toContain(RED_TOKEN);
    expect(w.text()).toContain("1");
  });

  it("hides the pill when delta is null", () => {
    const w = mount(StatCard, {
      props: { category: "x", value: 0, delta: null, loaded: true },
    });
    expect(w.html()).not.toContain(GREEN_TOKEN);
    expect(w.html()).not.toContain(RED_TOKEN);
  });

  it("shows dash before loaded", () => {
    const w = mount(StatCard, {
      props: { category: "x", value: 9, delta: null, loaded: false },
    });
    expect(w.text()).toContain("—");
  });
});
