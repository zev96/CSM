import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

let sseHandlers: Record<string, (d: any) => void> = {};
const postMock = vi.fn();
const getMock = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: postMock, get: getMock } }) }));
vi.mock("@/api/client", () => ({
  subscribe: (_u: string, h: Record<string, (d: any) => void>) => { sseHandlers = h; return () => {}; },
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import { useArticle } from "@/stores/article";

describe("article store — 链成本", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset(); getMock.mockReset(); getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("done 带 cost → 存 cost state；tokenTotal getter 求和", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_chain: ["p"] });
    sseHandlers.done({
      final_text: "成稿", passes: [],
      cost: { input_tokens: 1200, output_tokens: 800, cost: 0.0032, currency: "CNY" },
    });
    expect(a.cost?.cost).toBe(0.0032);
    expect(a.tokenTotal).toBe(2000);
  });

  it("无 cost（旧路径/未知 model）→ cost=null，tokenTotal=0", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j2" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    sseHandlers.done({ final_text: "成稿" });
    expect(a.cost).toBeNull();
    expect(a.tokenTotal).toBe(0);
  });

  it("submit 清空上一轮 cost", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j3" } });
    const a = useArticle();
    a.cost = { input_tokens: 1, output_tokens: 1, cost: 0.1, currency: "CNY" } as any;
    await a.submit({ keyword: "k", template_id: "t" });
    expect(a.cost).toBeNull();
  });

  it("rerunPass 流式 done 带 cost → 更新 cost", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j4" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_chain: ["p"] });
    a.passes = [{ index: 0, role: "persona", skill_id: "p", skill_name: "x", output: "A", input_chars: 1, output_chars: 1, input_tokens: 1, output_tokens: 1 }];
    // 流式：POST 返回 {job_id}，cost 由 done 事件带来（不再同步从 resp 读）
    postMock.mockResolvedValueOnce({ data: { job_id: "j4", stream_url: "/api/events/j4" } });
    await a.rerunPass(0);
    sseHandlers.done({ passes: a.passes, final_text: "A", cost: { input_tokens: 5, output_tokens: 5, cost: 0.001, currency: "CNY" } });
    expect(a.cost?.cost).toBe(0.001);
  });
});
