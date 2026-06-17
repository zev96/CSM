import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises, type VueWrapper } from "@vue/test-utils";

const mockClient = { get: vi.fn(), post: vi.fn(), delete: vi.fn() };
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: mockClient }) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

import TitlePanel from "@/components/xhs/panels/TitlePanel.vue";
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

describe("TitlePanel 预设标题", () => {
  it("点击标题条目填入标题（替换）", async () => {
    const store = useXhs();
    const w = mount(TitlePanel);
    await flushPromises();
    const first = w.find(".xhs-row");
    await first.trigger("click");
    expect(store.title).toBe(first.text().trim());
    w.unmount();
  });
});

describe("TitlePanel 我的标题", () => {
  it("输入后点「添加」create(title) 并清空输入", async () => {
    mockClient.post.mockResolvedValue({ data: { asset: { id: "1", kind: "title", payload: { text: "我的好标题" }, created_at: "t" } } });
    const w = mount(TitlePanel);
    await flushPromises();
    await switchToMine(w);
    const input = w.find("input.xhs-title-add-input");
    await input.setValue("我的好标题");
    await w.find(".xhs-title-add-btn").trigger("click");
    await flushPromises();
    expect(mockClient.post).toHaveBeenCalledWith("/api/xhs/custom-assets", { kind: "title", payload: { text: "我的好标题" } });
    expect((input.element as HTMLInputElement).value).toBe("");
    w.unmount();
  });

  it("点自定义标题条目填入标题（setTitle）", async () => {
    mockClient.get.mockResolvedValue({ data: { assets: [{ id: "1", kind: "title", payload: { text: "我的好标题" }, created_at: "t" }] } });
    const store = useXhs();
    const spy = vi.spyOn(store, "setTitle");
    const w = mount(TitlePanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-mine-main").trigger("click");
    expect(spy).toHaveBeenCalledWith("我的好标题");
    w.unmount();
  });

  it("点 ✕ 删除我的标题", async () => {
    mockClient.get.mockResolvedValue({ data: { assets: [{ id: "1", kind: "title", payload: { text: "我的好标题" }, created_at: "t" }] } });
    mockClient.delete.mockResolvedValue({});
    const w = mount(TitlePanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-mine-del").trigger("click");
    await flushPromises();
    expect(mockClient.delete).toHaveBeenCalledWith("/api/xhs/custom-assets/1");
    w.unmount();
  });
});
