import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import Card from "../Card.vue";

describe("Card", () => {
  it("默认 = 纸面卡 + 边框 + density 内边距", () => {
    const c = mount(Card).classes();
    expect(c).toContain("bg-card");
    expect(c).toContain("border");
    expect(c).toContain("pad-d");
  });
  it("muted → 深一档卡底", () => {
    expect(mount(Card, { props: { muted: true } }).classes()).toContain("bg-card-2");
  });
  it("dark → 暗底亮字、且不画 1px 边框", () => {
    const c = mount(Card, { props: { dark: true } }).classes();
    expect(c).toContain("bg-dark");
    expect(c).toContain("text-card");
    expect(c).not.toContain("border");
  });
  it("padless → 去内边距", () => {
    expect(mount(Card, { props: { padless: true } }).classes()).not.toContain("pad-d");
  });
});
