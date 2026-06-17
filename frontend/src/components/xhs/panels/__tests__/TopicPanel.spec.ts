import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises, type VueWrapper } from "@vue/test-utils";

const mockClient = { get: vi.fn(), post: vi.fn(), delete: vi.fn() };
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: mockClient }) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

import TopicPanel from "@/components/xhs/panels/TopicPanel.vue";
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

describe("TopicPanel 预设话题", () => {
  it("点击预设话题追加到正文", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "addTopic");
    const w = mount(TopicPanel);
    await flushPromises();
    const first = w.find(".xhs-tag");
    const tag = first.text().replace(/^#/, "").trim();
    await first.trigger("click");
    expect(spy).toHaveBeenCalledWith(tag);
    w.unmount();
  });
});

describe("TopicPanel 我的自定义话题", () => {
  it("输入话题后点添加 → POST /api/xhs/custom-assets，# 前缀被去掉，输入清空", async () => {
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "99", kind: "topic", payload: { text: "穿搭" }, created_at: "t" } },
    });
    const w = mount(TopicPanel);
    await flushPromises();
    await switchToMine(w);
    const input = w.find(".xhs-topic-add-input");
    await input.setValue("#穿搭");
    await w.find(".xhs-topic-add-btn").trigger("click");
    await flushPromises();
    expect(mockClient.post).toHaveBeenCalledWith("/api/xhs/custom-assets", { kind: "topic", payload: { text: "穿搭" } });
    expect((input.element as HTMLInputElement).value).toBe("");
    w.unmount();
  });

  it("点击自定义话题调用 xhs.addTopic", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "1", kind: "topic", payload: { text: "穿搭" }, created_at: "t" }] },
    });
    const store = useXhs();
    const spy = vi.spyOn(store, "addTopic");
    const w = mount(TopicPanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-mine-main").trigger("click");
    expect(spy).toHaveBeenCalledWith("穿搭");
    w.unmount();
  });

  it("点 ✕ 删除自定义话题", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "1", kind: "topic", payload: { text: "穿搭" }, created_at: "t" }] },
    });
    mockClient.delete.mockResolvedValue({});
    const w = mount(TopicPanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-mine-del").trigger("click");
    await flushPromises();
    expect(mockClient.delete).toHaveBeenCalledWith("/api/xhs/custom-assets/1");
    w.unmount();
  });
});
