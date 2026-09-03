import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import PlatformPickerCard from "../PlatformPickerCard.vue";

const base = { platform: "douyin" as const, picked: false };

describe("PlatformPickerCard", () => {
  it("TikHub 模式：显示「TikHub 就绪」，未登录也可选（点击 emit toggle 不 emit login）", async () => {
    const w = mount(PlatformPickerCard, { props: { ...base, loggedIn: false, tikhubMode: true } });
    expect(w.text()).toContain("TikHub 就绪");
    expect(w.text()).not.toContain("未登录");
    await w.find("button").trigger("click");
    expect(w.emitted("toggle")).toBeTruthy();
    expect(w.emitted("login")).toBeFalsy();
  });

  it("浏览器模式：未登录显示「未登录」，点击 emit login", async () => {
    const w = mount(PlatformPickerCard, { props: { ...base, loggedIn: false, tikhubMode: false } });
    expect(w.text()).toContain("未登录");
    await w.find("button").trigger("click");
    expect(w.emitted("login")).toBeTruthy();
    expect(w.emitted("toggle")).toBeFalsy();
  });

  it("浏览器模式：已登录显示「已登录」，点击 emit toggle", async () => {
    const w = mount(PlatformPickerCard, { props: { ...base, loggedIn: true } });
    expect(w.text()).toContain("已登录");
    await w.find("button").trigger("click");
    expect(w.emitted("toggle")).toBeTruthy();
  });
});
