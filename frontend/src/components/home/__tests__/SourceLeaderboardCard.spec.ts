import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn().mockResolvedValue({
        data: {
          leaderboard: [
            { domain: "smzdm.com", source_type: "什么值得买", rank: 1, rank_delta: 3 },
            { domain: "zhihu.com", source_type: "知乎", rank: 2, rank_delta: null },
          ],
        },
      }),
    },
  }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import SourceLeaderboardCard from "@/components/home/SourceLeaderboardCard.vue";

describe("SourceLeaderboardCard", () => {
  it("renders ranked domains; rank_delta null shows 新", async () => {
    const w = mount(SourceLeaderboardCard);
    await flushPromises();
    expect(w.text()).toContain("smzdm.com");
    expect(w.text()).toContain("zhihu.com");
    expect(w.text()).toContain("新"); // zhihu rank_delta=null → 新进
    expect(w.text()).toContain("3"); // smzdm rank_delta
    expect(w.text()).toContain("什么值得买"); // source_type
  });
});
