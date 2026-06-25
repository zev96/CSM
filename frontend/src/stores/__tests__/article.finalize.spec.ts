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

/** 模拟 takeoff 完成后的 store 态：lastJobId + lastRequest + 已编辑 draftText。 */
function seedAfterTakeoff(a: ReturnType<typeof useArticle>) {
  a.lastJobId = "job-A";
  a.lastRequest = {
    keyword: "无线吸尘器",
    template_id: "tpl-a",
    title: "无线吸尘器哪款好？",
    angle: { audience: "铲屎官", sellpoints: ["防缠绕技术"], tone: "口语" },
    skill_chain: ["人设", "去味"],
    provider: "deepseek",
    model: "deepseek-chat",
  } as any;
  a.draftText = "用户编辑后的初稿";
}

describe("article store — finalize（整篇润色=成稿增强）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("finalize POSTs /api/generate/{lastJobId}/finalize，draft 取 draftText、其余取 lastRequest", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "job-A" } });
    const a = useArticle();
    seedAfterTakeoff(a);
    await a.finalize();
    expect(postMock).toHaveBeenCalledWith("/api/generate/job-A/finalize", {
      draft: "用户编辑后的初稿",
      keyword: "无线吸尘器",
      title: "无线吸尘器哪款好？",
      angle: { audience: "铲屎官", sellpoints: ["防缠绕技术"], tone: "口语" },
      skill_id: null,
      skill_chain: ["人设", "去味"],
      provider: "deepseek",
      model: "deepseek-chat",
    });
  });

  it("finalize 守卫：无 lastJobId / lastRequest / draftText 时不 POST", async () => {
    const a = useArticle();
    await a.finalize();
    expect(postMock).not.toHaveBeenCalled();
    a.lastJobId = "job-A";
    a.lastRequest = { keyword: "k", template_id: "t" } as any;
    a.draftText = "   ";
    await a.finalize();
    expect(postMock).not.toHaveBeenCalled();
  });

  it("SSE pass → passes 增量；done → finalText + status done", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "job-A" } });
    const a = useArticle();
    seedAfterTakeoff(a);
    await a.finalize();
    expect(a.status).toBe("running");
    sseHandlers.pass({ index: 0, role: "persona", skill_id: "人设", skill_name: "克制理性", output: "A", input_chars: 1, output_chars: 1 });
    sseHandlers.pass({ index: 1, role: "humanize", skill_id: "去味", skill_name: "去AI味", output: "B", input_chars: 1, output_chars: 1 });
    expect(a.passes.map((p) => p.output)).toEqual(["A", "B"]);
    sseHandlers.done({ final_text: "成稿正文", passes: a.passes, document: null, draft: "用户编辑后的初稿", title: "T" });
    expect(a.finalText).toBe("成稿正文");
    expect(a.status).toBe("done");
  });

  it("finalize 轻 reset：保留 draftText（链输入），重置 finalText/passes", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "job-A" } });
    const a = useArticle();
    seedAfterTakeoff(a);
    a.finalText = "旧成稿";
    a.passes = [{ index: 0, role: "persona", skill_id: "x", skill_name: "x", output: "old", input_chars: 1, output_chars: 1 }];
    await a.finalize();
    expect(a.draftText).toBe("用户编辑后的初稿");
    expect(a.finalText).toBe("");
    expect(a.passes).toEqual([]);
  });

  it("finalize POST 失败 → status error，不抛", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "plan cache miss" } } });
    const a = useArticle();
    seedAfterTakeoff(a);
    await expect(a.finalize()).resolves.toBeUndefined();
    expect(a.status).toBe("error");
    expect(a.error).toBe("plan cache miss");
  });
});
