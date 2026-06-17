import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

// ── stable spy refs (hoisted so vi.mock factories can reference them) ────
const { mockGet, mockPatch } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPatch: vi.fn(),
}));

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: { get: mockGet, patch: mockPatch },
    sseURL: (p: string) => p,
  }),
}));

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError, warn: vi.fn() }),
}));

import XhsPromptsCard from "@/components/settings/XhsPromptsCard.vue";

const MOCK_RESPONSE = {
  data: {
    generate: { current: "G现", default: "G默" },
    polish: { current: "", default: "P默" },
  },
};

beforeEach(() => {
  setActivePinia(createPinia());
  mockGet.mockReset().mockResolvedValue(MOCK_RESPONSE);
  mockPatch.mockReset().mockResolvedValue(MOCK_RESPONSE);
  toastSuccess.mockClear();
  toastError.mockClear();
});

describe("XhsPromptsCard", () => {
  it("mount 时 GET /api/xhs/ai_prompts，渲染两个 textarea，generate 的值绑到 current", async () => {
    const w = mount(XhsPromptsCard);
    await flushPromises();

    expect(mockGet).toHaveBeenCalledWith("/api/xhs/ai_prompts");

    const textareas = w.findAll("textarea");
    expect(textareas).toHaveLength(2);

    // generate textarea（第一个）的 value 应等于 "G现"
    const genTa = w.find("[data-test='textarea-generate']");
    expect((genTa.element as HTMLTextAreaElement).value).toBe("G现");

    // polish textarea（第二个）current 是 ""，所以 value 为空
    const polishTa = w.find("[data-test='textarea-polish']");
    expect((polishTa.element as HTMLTextAreaElement).value).toBe("");

    w.unmount();
  });

  it("修改 generate textarea 并点保存 → PATCH body.generate 等于新值", async () => {
    const w = mount(XhsPromptsCard);
    await flushPromises();

    const newVal = "我的自定义生成 prompt";
    await w.find("[data-test='textarea-generate']").setValue(newVal);

    // PATCH 返回新状态
    mockPatch.mockResolvedValueOnce({
      data: {
        generate: { current: newVal, default: "G默" },
        polish: { current: "", default: "P默" },
      },
    });

    await w.find("[data-test='save-generate']").trigger("click");
    await flushPromises();

    expect(mockPatch).toHaveBeenCalledWith(
      "/api/xhs/ai_prompts",
      expect.objectContaining({ generate: newVal }),
    );
    expect(toastSuccess).toHaveBeenCalled();

    w.unmount();
  });

  it("点 generate 重置为默认 → PATCH body.generate 为空字符串", async () => {
    const w = mount(XhsPromptsCard);
    await flushPromises();

    // generate baseline 是 "G现"（非空 = 自定义态），重置按钮应该可点
    mockPatch.mockResolvedValueOnce({
      data: {
        generate: { current: "", default: "G默" },
        polish: { current: "", default: "P默" },
      },
    });

    await w.find("[data-test='reset-generate']").trigger("click");
    await flushPromises();

    expect(mockPatch).toHaveBeenCalledWith(
      "/api/xhs/ai_prompts",
      expect.objectContaining({ generate: "" }),
    );
    expect(toastSuccess).toHaveBeenCalled();

    w.unmount();
  });
});
