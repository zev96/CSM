import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

const mockClient = { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() };
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: mockClient,
    sseURL: (p: string) => p,
  }),
}));
vi.mock("@/composables/useConfirm", () => ({
  confirmDialog: vi.fn().mockResolvedValue(true),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn(), dismiss: vi.fn(), toasts: { value: [] } }),
}));

import TemplatePanel from "@/components/xhs/panels/TemplatePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.mocked(confirmDialog).mockClear();
  vi.useFakeTimers();
  mockClient.get.mockResolvedValue({ data: { assets: [] } });
  mockClient.post.mockReset();
  mockClient.post.mockResolvedValue({ data: { id: "d1" } });
  mockClient.patch.mockReset();
  mockClient.patch.mockResolvedValue({ data: {} });
  mockClient.delete.mockReset();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("TemplatePanel", () => {
  it("编辑器为空时点击模板直接载入（不弹确认）", async () => {
    const store = useXhs();
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(store.title.length).toBeGreaterThan(0);
    expect(confirmDialog).not.toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器非空时先弹确认，确认后覆盖", async () => {
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(confirmDialog).toHaveBeenCalledTimes(1);
    expect(store.body).not.toBe("已有内容");
    w.unmount();
  });

  it("编辑器非空时取消确认不覆盖", async () => {
    vi.mocked(confirmDialog).mockResolvedValueOnce(false);
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(store.body).toBe("已有内容");
    w.unmount();
  });
});

describe("TemplatePanel 我的模版", () => {
  it("点「存为我的模版」用当前标题/正文 create(template)", async () => {
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "1", kind: "template", payload: { name: "我的标题", title: "我的标题", body: "正文", topics: [] }, created_at: "t" } },
    });
    const store = useXhs();
    store.$patch({ title: "我的标题", body: "正文" });
    const w = mount(TemplatePanel);
    await flushPromises();
    await w.find(".xhs-save-template").trigger("click");
    await flushPromises();
    expect(mockClient.post).toHaveBeenCalledTimes(1);
    const [, body] = mockClient.post.mock.calls[0];
    expect(body.kind).toBe("template");
    expect(body.payload.title).toBe("我的标题");
    w.unmount();
  });

  it("内容为空时不创建（提示先写内容）", async () => {
    useXhs();
    const w = mount(TemplatePanel);
    await flushPromises();
    await w.find(".xhs-save-template").trigger("click");
    await flushPromises();
    expect(mockClient.post).not.toHaveBeenCalled();
    w.unmount();
  });
});
