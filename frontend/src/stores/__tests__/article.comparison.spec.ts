import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

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

describe("article store — 横评 submitComparison", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("POST /api/generate/comparison 带 models + tone", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    const a = useArticle();
    await a.submitComparison({ models: ["A", "B"], keyword: "怎么选", tone: "口语" });
    expect(postMock).toHaveBeenCalledWith(
      "/api/generate/comparison",
      expect.objectContaining({ models: ["A", "B"], tone: "口语", draft_only: true }),
    );
    expect(a.lastJobId).toBe("jc");
  });

  it("assembly(plan=null) → draftText 填骨架、plan 保持 null", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    const a = useArticle();
    await a.submitComparison({ models: ["A", "B"], keyword: "k" });
    sseHandlers.assembly({ plan: null, draft: "## 参数对照\n...", comparison: { models: ["A", "B"] } });
    expect(a.draftText).toContain("## 参数对照");
    expect(a.plan).toBeNull();
  });

  it("finalize() 复用 lastJobId 打 /finalize（横评成稿走同端点）", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    const a = useArticle();
    await a.submitComparison({ models: ["A", "B"], keyword: "k" });
    sseHandlers.assembly({ plan: null, draft: "骨架", comparison: { models: ["A", "B"] } });
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    await a.finalize();
    expect(postMock).toHaveBeenLastCalledWith(
      "/api/generate/jc/finalize",
      expect.objectContaining({ draft: "骨架", keyword: "k" }),
    );
  });
});
