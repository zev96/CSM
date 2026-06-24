import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ── capture the SSE handlers passed to subscribe() so we can drive
//    `pass` / `done` events directly (the real EventSource never opens
//    in jsdom). subscribe returns a no-op teardown like production. ──
let sseHandlers: Record<string, (d: any) => void> = {};
const postMock = vi.fn();
const getMock = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock } }),
}));
vi.mock("@/api/client", () => ({
  subscribe: (_url: string, handlers: Record<string, (d: any) => void>) => {
    sseHandlers = handlers;
    return () => {};
  },
}));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

import { useArticle } from "@/stores/article";
import type { ChainPass } from "@/stores/article";

function mkPass(over: Partial<ChainPass> = {}): ChainPass {
  return {
    index: 0,
    role: "persona",
    skill_id: "p",
    skill_name: "人设",
    output: "OUT",
    input_chars: 3,
    output_chars: 3,
    ...over,
  };
}

describe("article store — skill 链 passes", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("submit POSTs skill_chain when provided", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    const a = useArticle();
    await a.submit({
      keyword: "无线吸尘器",
      template_id: "t",
      skill_chain: ["p", "h", "plat"],
    });
    expect(postMock).toHaveBeenCalledWith(
      "/api/generate",
      expect.objectContaining({ skill_chain: ["p", "h", "plat"] }),
    );
  });

  it("submit 不带 skill_chain 时 body 无 skill_chain（零回归）", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j2" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_id: "p" });
    const body = postMock.mock.calls[0][1];
    expect("skill_chain" in body ? body.skill_chain : undefined).toBeUndefined();
  });

  it("submit 清空上一轮 passes", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j3" } });
    const a = useArticle();
    a.passes = [mkPass()];
    await a.submit({ keyword: "k", template_id: "t" });
    expect(a.passes).toEqual([]);
  });

  it("SSE pass 事件逐个 push 到 passes", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j4" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_chain: ["p", "h"] });
    sseHandlers.pass(mkPass({ index: 0, skill_name: "人设", output: "A" }));
    sseHandlers.pass(mkPass({ index: 1, role: "humanize", skill_id: "h", skill_name: "去AI味", output: "B" }));
    expect(a.passes.map((p) => p.skill_name)).toEqual(["人设", "去AI味"]);
    expect(a.passes[1].output).toBe("B");
  });

  it("SSE done 带 passes 时覆盖 passes", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j5" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_chain: ["p", "h"] });
    // partial passes streamed in...
    sseHandlers.pass(mkPass({ index: 0 }));
    // ...then done carries the authoritative full list
    const full = [
      mkPass({ index: 0, output: "A", output_chars: 1 }),
      mkPass({ index: 1, role: "humanize", skill_id: "h", skill_name: "去AI味", output: "BB", output_chars: 2 }),
    ];
    sseHandlers.done({ final_text: "BB", passes: full, title: "T" });
    expect(a.passes).toHaveLength(2);
    expect(a.passes[1].output).toBe("BB");
    expect(a.finalText).toBe("BB");
  });

  it("SSE done 无 passes（单 skill 旧路径）→ passes 不被改写", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j6" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_id: "p" });
    sseHandlers.done({ final_text: "成稿", title: "T" });
    expect(a.passes).toEqual([]);
    expect(a.finalText).toBe("成稿");
  });

  it("rerunPass POSTs /api/chain/rerun 并更新 passes + finalText", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j7" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_chain: ["p", "h"] });
    a.passes = [mkPass({ index: 0, output: "A" }), mkPass({ index: 1, output: "B" })];
    const updated = [
      mkPass({ index: 0, output: "A" }),
      mkPass({ index: 1, output: "B2", output_chars: 2 }),
    ];
    postMock.mockResolvedValueOnce({ data: { passes: updated, final_text: "B2" } });
    await a.rerunPass(1);
    expect(postMock).toHaveBeenLastCalledWith("/api/chain/rerun", {
      job_id: "j7",
      pass_index: 1,
    });
    expect(a.passes[1].output).toBe("B2");
    expect(a.finalText).toBe("B2");
  });

  it("rerunPass 从不抛 —— 网络异常静默吞掉", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j8" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_chain: ["p"] });
    a.passes = [mkPass({ index: 0, output: "A" })];
    postMock.mockRejectedValueOnce(new Error("boom"));
    await expect(a.rerunPass(0)).resolves.toBeUndefined();
    // unchanged on failure
    expect(a.passes[0].output).toBe("A");
  });

  it("成本 getter callCount / totalChars", async () => {
    const a = useArticle();
    a.passes = [
      mkPass({ index: 0, output_chars: 100 }),
      mkPass({ index: 1, output_chars: 250 }),
      mkPass({ index: 2, output_chars: 80 }),
    ];
    expect(a.callCount).toBe(3);
    expect(a.totalChars).toBe(430);
  });
});
