import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import ThemePanel from "@/components/xhs/panels/ThemePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";
import { THEMES } from "@/data/xhs/assets";
import { orderedMarker } from "@/utils/xhsTheme";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("ThemePanel", () => {
  it("点击主题卡设激活主题", async () => {
    const store = useXhs();
    const w = mount(ThemePanel);
    await w.find(".xhs-theme-card").trigger("click");
    expect(store.themeId).toBe(THEMES[0].id);
    expect(store.activeTheme?.id).toBe(THEMES[0].id);
    w.unmount();
  });

  it("卡片预览含有序样例（第一个主题样式的序号字形）", () => {
    const w = mount(ThemePanel);
    const firstCard = w.findAll(".xhs-theme-card")[0];
    expect(firstCard.text()).toContain(orderedMarker(1, THEMES[0].ordered));
    w.unmount();
  });
});
