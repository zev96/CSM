import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

// 捕获 subscribe() 收到的 SSE handler，直接驱动 pass / done / error 事件
// （jsdom 里真 EventSource 不会开）。subscribe 返回与生产一致的 no-op teardown。
let sseHandlers: Record<string, (d: any) => void> = {};
const postMock = vi.fn();
const getMock = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: postMock, get: getMock } }) }));
vi.mock("@/api/client", () => ({
  subscribe: (_u: string, h: Record<string, (d: any) => void>) => { sseHandlers = h; return () => {}; },
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import { useArticle, type ChainPass } from "@/stores/article";

function mkPass(i: number, out: string): ChainPass {
  return { index: i, role: "persona", skill_id: "p", skill_name: "x", output: out, input_chars: 1, output_chars: 1 };
}

describe("article store — 流式重跑", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset(); getMock.mockReset(); getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("rerunPass POST 后订阅 SSE，pass 按 index 替换、done 覆盖+cost", async () => {
    const a = useArticle();
    a.lastJobId = "j1";
    a.passes = [mkPass(0, "A"), mkPass(1, "B")];
    postMock.mockResolvedValueOnce({ data: { job_id: "j1", stream_url: "/api/events/j1" } });
    await a.rerunPass(0);
    expect(postMock).toHaveBeenCalledWith("/api/chain/rerun", { job_id: "j1", pass_index: 0 });
    expect(a.rerunningIndex).toBe(0);
    sseHandlers.pass(mkPass(0, "A2"));
    expect(a.passes[0].output).toBe("A2");
    sseHandlers.pass(mkPass(1, "B2"));
    expect(a.passes[1].output).toBe("B2");
    sseHandlers.done({ passes: [mkPass(0, "A2"), mkPass(1, "B2")], final_text: "B2",
      cost: { input_tokens: 5, output_tokens: 5, cost: 0.001, currency: "CNY" } });
    expect(a.finalText).toBe("B2");
    expect(a.cost?.cost).toBe(0.001);
    expect(a.rerunningIndex).toBeNull();
  });

  it("rerunPass POST 失败 → rerunningIndex 清空，从不抛", async () => {
    const a = useArticle();
    a.lastJobId = "j2";
    postMock.mockRejectedValueOnce(new Error("boom"));
    await expect(a.rerunPass(0)).resolves.toBeUndefined();
    expect(a.rerunningIndex).toBeNull();
  });

  it("无 lastJobId → 不 POST", async () => {
    const a = useArticle();
    await a.rerunPass(0);
    expect(postMock).not.toHaveBeenCalled();
  });

  it("cancelRerun POSTs /cancel", async () => {
    const a = useArticle();
    a.lastJobId = "j3"; a.rerunningIndex = 1;
    postMock.mockResolvedValueOnce({ data: {} });
    await a.cancelRerun();
    expect(postMock).toHaveBeenCalledWith("/api/generate/j3/cancel");
  });

  it("SSE error（含 cancelled）→ 清 rerunningIndex（取消链路核心收尾）", async () => {
    const a = useArticle();
    a.lastJobId = "j5";
    a.passes = [mkPass(0, "A")];
    postMock.mockResolvedValueOnce({ data: { job_id: "j5" } });
    await a.rerunPass(0);
    expect(a.rerunningIndex).toBe(0);
    sseHandlers.error({ cancelled: true });
    expect(a.rerunningIndex).toBeNull();
  });
});
