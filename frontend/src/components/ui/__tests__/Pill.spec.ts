import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import Pill from "../Pill.vue";

describe("Pill", () => {
  it("默认 = info tone（中性）", () => {
    const w = mount(Pill, { slots: { default: () => "x" } });
    expect(w.classes()).toContain("bg-card-2");
    expect(w.classes()).toContain("text-ink-3");
  });
  it("ok tone → 绿", () => {
    expect(mount(Pill, { props: { tone: "ok" } }).classes()).toContain("text-green");
  });
  it("warn tone → 黄底 + tokenized 深黄字（不再硬编码 #a07a18）", () => {
    const c = mount(Pill, { props: { tone: "warn" } }).classes();
    expect(c).toContain("bg-yellow-soft");
    expect(c).toContain("text-yellow-deep");
  });
  it("alert / primary tone", () => {
    expect(mount(Pill, { props: { tone: "alert" } }).classes()).toContain("text-red");
    expect(mount(Pill, { props: { tone: "primary" } }).classes()).toContain("text-primary-deep");
  });
  it("保留基础排版 class", () => {
    expect(mount(Pill, { props: { tone: "ok" } }).classes()).toContain("inline-flex");
  });
});
