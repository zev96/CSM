import { describe, it, expect, vi, afterEach } from "vitest";
import { mount } from "@vue/test-utils";

import Icon from "../Icon.vue";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Icon", () => {
  it("改变 name 后渲染的图形跟着变", async () => {
    // 历史实现把图形算在 setup 期的普通 const 里，props 变了也不重绘 ——
    // `<Icon :name="ok ? 'check' : 'x'"/>` 这类结果徽标会一直停在第一次
    // 渲染时的那个图标上。
    const w = mount(Icon, { props: { name: "check" } });
    const before = w.html();
    expect(before).toContain("polyline");

    await w.setProps({ name: "x" });
    const after = w.html();
    expect(after).not.toBe(before);
    expect(after).toContain("line");
    expect(after).not.toContain("polyline");
  });

  it("未知名字回落到 home 并只警告一次", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const home = mount(Icon, { props: { name: "home" } }).html();

    const w = mount(Icon, { props: { name: "definitely-not-an-icon" } });
    expect(w.html()).toBe(home.replace(/definitely-not-an-icon/g, ""));

    // 同名反复切换不该刷屏
    await w.setProps({ name: "check" });
    await w.setProps({ name: "definitely-not-an-icon" });
    const hits = warn.mock.calls.filter((c) =>
      String(c[0]).includes("definitely-not-an-icon"),
    );
    expect(hits.length).toBe(1);
  });

  it("已知名字不产生警告", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    mount(Icon, { props: { name: "eye" } });
    mount(Icon, { props: { name: "eyeOff" } });
    expect(warn).not.toHaveBeenCalled();
  });

  it("eye / eyeOff 是两个不同的图形", () => {
    const eye = mount(Icon, { props: { name: "eye" } }).html();
    const eyeOff = mount(Icon, { props: { name: "eyeOff" } }).html();
    expect(eye).not.toBe(eyeOff);
  });

  it("size / stroke 透传到 svg 上", () => {
    const w = mount(Icon, { props: { name: "check", size: 11, stroke: 2 } });
    expect(w.attributes("width")).toBe("11");
    expect(w.attributes("stroke-width")).toBe("2");
  });
});
