import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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

afterEach(() => {
  vi.clearAllTimers();
});

describe("TopicPanel", () => {
  it("点击话题加入 topics，重复点击不重复", async () => {
    const store = useXhs();
    const w = mount(TopicPanel);
    await flushPromises();
    const first = w.find(".xhs-tag");
    const tag = first.text().replace(/^#/, "").trim();
    await first.trigger("click");
    expect(store.topics).toContain(tag);
    await first.trigger("click"); // 再点一次
    expect(store.topics.filter((t) => t === tag)).toHaveLength(1);
    w.unmount();
  });
});

describe("TopicPanel 我的话题分组", () => {
  it("有话题时「存为话题分组」create(topic_group)", async () => {
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "1", kind: "topic_group", payload: { name: "我的话题", tags: ["穿搭", "通勤"] }, created_at: "t" } },
    });
    const store = useXhs();
    store.$patch({ topics: ["穿搭", "通勤"] });
    const w = mount(TopicPanel);
    await flushPromises();
    await w.find(".xhs-save-topicgroup").trigger("click");
    await flushPromises();
    expect(mockClient.post).toHaveBeenCalledTimes(1);
    const [, body] = mockClient.post.mock.calls[0];
    expect(body.kind).toBe("topic_group");
    expect(body.payload.tags).toEqual(["穿搭", "通勤"]);
    w.unmount();
  });

  it("无话题时不创建", async () => {
    useXhs();
    const w = mount(TopicPanel);
    await flushPromises();
    await w.find(".xhs-save-topicgroup").trigger("click");
    await flushPromises();
    expect(mockClient.post).not.toHaveBeenCalled();
    w.unmount();
  });

  it("「全部添加」把组内 tag 全部 addTopic", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "1", kind: "topic_group", payload: { name: "g", tags: ["a", "b", "c"] }, created_at: "t" }] },
    });
    const store = useXhs();
    const spy = vi.spyOn(store, "addTopic");
    const w = mount(TopicPanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-addall").trigger("click");
    expect(spy).toHaveBeenCalledTimes(3);
    w.unmount();
  });

  it("点 ✕ 删除话题分组", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "9", kind: "topic_group", payload: { name: "g", tags: ["a"] }, created_at: "t" }] },
    });
    mockClient.delete.mockResolvedValue({});
    const w = mount(TopicPanel);
    await flushPromises();
    await switchToMine(w);
    await w.find(".xhs-mine-del").trigger("click");
    await flushPromises();
    expect(mockClient.delete).toHaveBeenCalledWith("/api/xhs/custom-assets/9");
    w.unmount();
  });
});
