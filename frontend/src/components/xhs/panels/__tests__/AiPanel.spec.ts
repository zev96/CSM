import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
    sseURL: (p: string) => p,
  }),
}));

// 稳定 spy（vi.hoisted 避免 vi.mock 提升导致的未初始化）。
const { toastSuccess, toastError, toastWarn, routerPush, confirmFn } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastWarn: vi.fn(),
  routerPush: vi.fn(),
  confirmFn: vi.fn().mockResolvedValue(true),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError, warn: toastWarn }),
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: routerPush }) }));
vi.mock("@/composables/useConfirm", () => ({ confirmDialog: confirmFn }));

import AiPanel from "@/components/xhs/panels/AiPanel.vue";
import { useXhs, _resetXhsModuleState, LLMNotConfiguredError } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  toastSuccess.mockClear();
  toastError.mockClear();
  toastWarn.mockClear();
  routerPush.mockClear();
  confirmFn.mockClear().mockResolvedValue(true);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

function setIntent(w: ReturnType<typeof mount>, v: string) {
  const ta = w.find("textarea.xhs-ai-input");
  return ta.setValue(v);
}

describe("AiPanel —— 生成整篇", () => {
  it("空主题点生成 → warn，不调 store", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "generateNote");
    const w = mount(AiPanel);
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(toastWarn).toHaveBeenCalled();
    expect(spy).not.toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器为空 → 不弹确认，直接 applyTemplate 填入", async () => {
    const store = useXhs();
    vi.spyOn(store, "generateNote").mockResolvedValue({ title: "T", body: "B", topics: ["x"] });
    const applySpy = vi.spyOn(store, "applyTemplate");
    const w = mount(AiPanel);
    await setIntent(w, "平价护肤");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(confirmFn).not.toHaveBeenCalled();
    expect(applySpy).toHaveBeenCalledWith({ title: "T", body: "B", topics: ["x"] });
    expect(toastSuccess).toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器非空 → 先弹确认；确认后 applyTemplate", async () => {
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    vi.spyOn(store, "generateNote").mockResolvedValue({ title: "T", body: "B", topics: [] });
    const applySpy = vi.spyOn(store, "applyTemplate");
    const w = mount(AiPanel);
    await setIntent(w, "主题");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(confirmFn).toHaveBeenCalledTimes(1);
    expect(applySpy).toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器非空 → 取消确认 → 不调 generateNote、不 applyTemplate", async () => {
    confirmFn.mockResolvedValueOnce(false);
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    const genSpy = vi.spyOn(store, "generateNote");
    const applySpy = vi.spyOn(store, "applyTemplate");
    const w = mount(AiPanel);
    await setIntent(w, "主题");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(genSpy).not.toHaveBeenCalled();
    expect(applySpy).not.toHaveBeenCalled();
    w.unmount();
  });

  it("LLMNotConfiguredError → toast.error 带「去设置」、点击跳 /settings", async () => {
    const store = useXhs();
    vi.spyOn(store, "generateNote").mockRejectedValue(new LLMNotConfiguredError());
    const w = mount(AiPanel);
    await setIntent(w, "主题");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(toastError).toHaveBeenCalledTimes(1);
    const opts = toastError.mock.calls[0][1];
    expect(opts.actionLabel).toBe("去设置");
    opts.onAction();
    expect(routerPush).toHaveBeenCalledWith("/settings");
    w.unmount();
  });
});

describe("AiPanel —— 润色正文", () => {
  it("正文为空点润色 → warn，不调 store", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "polishBody");
    const w = mount(AiPanel);
    await w.find("button.xhs-ai-btn-polish").trigger("click");
    await flushPromises();
    expect(toastWarn).toHaveBeenCalled();
    expect(spy).not.toHaveBeenCalled();
    w.unmount();
  });

  it("正文非空 → polishBody 后 setBody 填回 + success", async () => {
    const store = useXhs();
    store.$patch({ body: "朴素正文" });
    vi.spyOn(store, "polishBody").mockResolvedValue("润色后");
    const setSpy = vi.spyOn(store, "setBody");
    const w = mount(AiPanel);
    await w.find("button.xhs-ai-btn-polish").trigger("click");
    await flushPromises();
    expect(setSpy).toHaveBeenCalledWith("润色后");
    expect(toastSuccess).toHaveBeenCalled();
    w.unmount();
  });
});
