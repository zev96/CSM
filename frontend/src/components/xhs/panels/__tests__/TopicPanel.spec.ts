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

import TopicPanel from "@/components/xhs/panels/TopicPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("TopicPanel", () => {
  it("点击话题加入 topics，重复点击不重复", async () => {
    const store = useXhs();
    const w = mount(TopicPanel);
    const first = w.find(".xhs-tag");
    const tag = first.text().replace(/^#/, "").trim();
    await first.trigger("click");
    expect(store.topics).toContain(tag);
    await first.trigger("click"); // 再点一次
    expect(store.topics.filter((t) => t === tag)).toHaveLength(1);
    w.unmount();
  });
});
