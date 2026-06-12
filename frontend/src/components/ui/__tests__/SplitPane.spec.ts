import { describe, it, expect, beforeAll, vi } from "vitest";
import { mount } from "@vue/test-utils";
import SplitPane from "../SplitPane.vue";

beforeAll(() => {
  // jsdom lacks matchMedia; stub it returning matches:true (wide layout).
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true,
    media: q,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    onchange: null,
    dispatchEvent() { return false; },
  }));
});

describe("SplitPane", () => {
  it("renders #left and #right slots", () => {
    const w = mount(SplitPane, {
      slots: { left: "<div class='L'>L</div>", right: "<div class='R'>R</div>" },
    });
    expect(w.find(".L").exists()).toBe(true);
    expect(w.find(".R").exists()).toBe(true);
  });

  it("applies the default GEO column template (340px 1fr) and gap when wide", () => {
    const w = mount(SplitPane, { slots: { left: "l", right: "r" } });
    const style = w.attributes("style") ?? "";
    expect(style).toContain("340px 1fr");
    expect(style).toContain("18px");
  });

  it("honors custom leftWidth / gap props", () => {
    const w = mount(SplitPane, {
      props: { leftWidth: "300px", gap: "12px" },
      slots: { left: "l", right: "r" },
    });
    const style = w.attributes("style") ?? "";
    expect(style).toContain("300px 1fr");
    expect(style).toContain("12px");
  });
});
