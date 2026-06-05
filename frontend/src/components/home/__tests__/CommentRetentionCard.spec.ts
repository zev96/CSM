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
    const w = mount(CommentRetentionCard);
    await flushPromises();
    expect(w.text()).toContain("57%"); // 8/14 → 57
    expect(w.text()).toContain("B 站");
    expect(w.text()).toContain("全部");
  });
});
