import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";

const { patchMock, loadMock, state } = vi.hoisted(() => {
  const state: any = {
    data: { brand_memory: { inject: false, factcheck: false, own_brands: ["CEWEY"], inject_variant_cap: 3, inject_endorsement_cap: 5 } },
    loading: false, error: null,
  };
  return { patchMock: vi.fn(), loadMock: vi.fn(), state };
});
vi.mock("@/stores/config", () => ({
  useConfig: () => ({ ...state, load: loadMock, patch: patchMock }),
}));
const { toastSuccess, toastError } = vi.hoisted(() => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError, warn: vi.fn() }),
}));

import BrandMemoryCard from "@/components/settings/BrandMemoryCard.vue";

describe("BrandMemoryCard", () => {
  beforeEach(() => { patchMock.mockReset().mockResolvedValue(undefined); toastSuccess.mockClear(); });

  it("挂载反映 config 的 inject/own_brands", async () => {
    const w = mount(BrandMemoryCard);
    await flushPromises();
    // own_brands 输入框含 CEWEY
    expect(w.html()).toContain("CEWEY");
  });

  it("打开 inject 开关 → patch({brand_memory:{inject:true}})", async () => {
    const w = mount(BrandMemoryCard);
    await flushPromises();
    await w.find("[data-test='toggle-inject'] button").trigger("click");
    await flushPromises();
    expect(patchMock).toHaveBeenCalledWith({ brand_memory: { inject: true } });
  });

  it("own_brands 改「CEWEY、希喂」commit → patch own_brands 为 list", async () => {
    const w = mount(BrandMemoryCard);
    await flushPromises();
    const inp = w.find("[data-test='own-brands'] input");
    await inp.setValue("CEWEY、希喂");
    await inp.trigger("blur");
    await flushPromises();
    expect(patchMock).toHaveBeenCalledWith({ brand_memory: { own_brands: ["CEWEY", "希喂"] } });
  });
});
