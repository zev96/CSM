import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises, type VueWrapper } from "@vue/test-utils";

const mockClient = { get: vi.fn(), post: vi.fn(), delete: vi.fn() };
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: mockClient }) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

import CopyPanel from "@/components/xhs/panels/CopyPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

async function switchToMine(w: VueWrapper) {
  const tab = w.findAll("button").find((b) => b.text() === "我的");
  if (tab) await tab.trigger("click");
  await flushPromises();
}

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  mockClient.get.mockResolvedValue({ data: { assets: [] } });
  mockClient.post.mockReset();
  mockClient.delete.mockReset();
});

describe("CopyPanel 我的文案", () => {
  it("输入后点「添加」create(copy) 并清空输入", async () => {
    mockClient.post.mockResolvedValue({ data: { asset: { id: "1", kind: "copy", payload: { text: "自定义一句" }, created_at: "t" } } });
    const w = mount(CopyPanel);
    await flushPromises();
    await switchToMine(w);
    const input = w.find("input.xhs-copy-add-input");
    await input.setValue("自定义一句");
    await w.find(".xhs-copy-add-btn").trigger("click");
    await flushPromises();
    expect(mockClient.post).toHaveBeenCalledWith("/api/xhs/custom-assets", { kind: "copy", payload: { text: "自定义一句" } });
    expect((input.element as HTMLInputElement).value).toBe("");
    w.unmount();
  });

  it("点我的文案条插入正文光标处", async () => {
    mockClient.get.mockResolvedValue({ data: { assets: [{ id: "1", kind: "copy", payload: { text: "插我" }, created_at: "t" }] } });
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(CopyPanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-mine-main").trigger("click");
    expect(spy).toHaveBeenCalledWith("插我");
    w.unmount();
  });

  it("点 ✕ 删除我的文案", async () => {
    mockClient.get.mockResolvedValue({ data: { assets: [{ id: "9", kind: "copy", payload: { text: "删我" }, created_at: "t" }] } });
    mockClient.delete.mockResolvedValue({});
    const w = mount(CopyPanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-mine-del").trigger("click");
    await flushPromises();
    expect(mockClient.delete).toHaveBeenCalledWith("/api/xhs/custom-assets/9");
    w.unmount();
  });
});
