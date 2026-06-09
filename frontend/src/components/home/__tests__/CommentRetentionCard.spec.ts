import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn().mockResolvedValue({
        data: {
          platforms: {
            bilibili_comment: {
              label: "B 站",
              current_retained: 8,
              current_total: 14,
              rate_today: 8 / 14,
              rate_prev: 0.7,
              daily_series: [
                { date: "d1", retained: 7, total: 10, rate: 0.7 },
                { date: "d2", retained: 8, total: 14, rate: 8 / 14 },
              ],
            },
          },
        },
      }),
    },
  }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import CommentRetentionCard from "@/components/home/CommentRetentionCard.vue";

describe("CommentRetentionCard", () => {
  it("aggregates retention % and renders a platform tab", async () => {
    // LineChart 内部是 chart.js（canvas），jsdom 无 getContext —— stub 掉，
    // 这个用例只验证留存率聚合 + 平台 tab，不依赖图表渲染。
    const w = mount(CommentRetentionCard, {
      global: { stubs: { LineChart: true } },
    });
    await flushPromises();
    expect(w.text()).toContain("57%"); // 8/14 → 57（默认选中第一个平台 B 站）
    expect(w.text()).toContain("B 站");
    expect(w.text()).not.toContain("全部"); // 「全部」选项已删除
  });
});
