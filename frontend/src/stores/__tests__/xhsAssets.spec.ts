import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const mockClient = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
};
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: mockClient }),
}));

import { useXhsAssets } from "@/stores/xhsAssets";

beforeEach(() => {
  setActivePinia(createPinia());
  mockClient.get.mockReset();
  mockClient.post.mockReset();
  mockClient.delete.mockReset();
});

describe("xhsAssets store", () => {
  it("ensureLoaded 拉全量并按 kind 分流 getter", async () => {
    mockClient.get.mockResolvedValue({
      data: {
        assets: [
          { id: "1", kind: "copy", payload: { text: "a" }, created_at: "t1" },
          { id: "2", kind: "template", payload: { name: "n", title: "t", body: "b", topics: [] }, created_at: "t2" },
          { id: "3", kind: "title", payload: { text: "好标题" }, created_at: "t3" },
          { id: "4", kind: "topic", payload: { text: "穿搭" }, created_at: "t4" },
        ],
      },
    });
    const s = useXhsAssets();
    await s.ensureLoaded();
    expect(s.copies.length).toBe(1);
    expect(s.templates.length).toBe(1);
    expect(s.titles.length).toBe(1);
    expect(s.topics.length).toBe(1);
    await s.ensureLoaded();
    expect(mockClient.get).toHaveBeenCalledTimes(1);
  });

  it("create 把新素材推进列表", async () => {
    mockClient.get.mockResolvedValue({ data: { assets: [] } });
    mockClient.post.mockResolvedValue({
      data: { asset: { id: "9", kind: "copy", payload: { text: "new" }, created_at: "t" } },
    });
    const s = useXhsAssets();
    await s.ensureLoaded();
    const a = await s.create("copy", { text: "new" });
    expect(a.id).toBe("9");
    expect(s.assets[0].id).toBe("9");
    expect(s.copies.length).toBe(1);
    expect(mockClient.post).toHaveBeenCalledWith("/api/xhs/custom-assets", { kind: "copy", payload: { text: "new" } });
  });

  it("remove 调 DELETE 并从列表剔除", async () => {
    mockClient.get.mockResolvedValue({
      data: { assets: [{ id: "1", kind: "copy", payload: { text: "a" }, created_at: "t" }] },
    });
    mockClient.delete.mockResolvedValue({});
    const s = useXhsAssets();
    await s.ensureLoaded();
    await s.remove("1");
    expect(mockClient.delete).toHaveBeenCalledWith("/api/xhs/custom-assets/1");
    expect(s.copies.length).toBe(0);
  });
});
