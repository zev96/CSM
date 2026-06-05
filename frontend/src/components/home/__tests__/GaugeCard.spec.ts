import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: { get: vi.fn().mockResolvedValue({ data: { soc: 0.6, delta: 0.08, band: "strong" } }) },
  }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import GaugeCard from "@/components/home/GaugeCard.vue";

describe("GaugeCard", () => {
  it("renders soc as 0-100 + band label + week delta", async () => {
    const w = mount(GaugeCard);
    await flushPromises();
    expect(w.text()).toContain("60"); // soc 0.6 → 60
    expect(w.text()).toContain("高曝光"); // band strong
    expect(w.text()).toContain("8%"); // delta 0.08
  });
});
