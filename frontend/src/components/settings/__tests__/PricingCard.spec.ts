import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const patchMock = vi.fn().mockResolvedValue(undefined);
vi.mock("@/stores/config", () => ({
  useConfig: () => ({
    data: { pricing: {}, default_model: { deepseek: "deepseek-chat" } },
    load: vi.fn(), patch: patchMock, error: null,
  }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));

import PricingCard from "@/components/settings/PricingCard.vue";

describe("PricingCard", () => {
  beforeEach(() => { patchMock.mockClear(); });

  it("列出已知 model 行", async () => {
    const w = mount(PricingCard, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect(w.text()).toContain("deepseek-chat");
    expect(w.text()).toContain("qwen-plus");
  });

  it("改 input+output 单价 → commit patch {pricing:{model:{input,output}}}", async () => {
    const w = mount(PricingCard, { global: { stubs: { teleport: true } } });
    await flushPromises();
    // FormInput inheritAttrs=true 把 data-price-* 透传到根 <input>，直接定位
    const inEl = w.find("[data-price-input='deepseek-chat']");
    const outEl = w.find("[data-price-output='deepseek-chat']");
    expect(inEl.exists()).toBe(true);
    expect(outEl.exists()).toBe(true);
    // 找到内部 input 填值 + blur（debounce="blur" → blur 触发 commit）
    const inInput = inEl.element.tagName === "INPUT" ? inEl : inEl.find("input");
    const outInput = outEl.element.tagName === "INPUT" ? outEl : outEl.find("input");
    await (inInput as any).setValue("1.5");
    await (outInput as any).setValue("3.0");
    await (outInput as any).trigger("blur");
    await flushPromises();
    expect(patchMock).toHaveBeenCalledWith(
      expect.objectContaining({ pricing: expect.objectContaining({
        "deepseek-chat": expect.objectContaining({ input: 1.5, output: 3.0 }) }) }),
    );
  });
});
