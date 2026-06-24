import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const postMock = vi.fn();
let capturedHandlers: any = null;
vi.mock("@/stores/sidecar", () => ({
  // submit() 会并行 GET template 详情（失败不阻塞）；mock 的 get 必须返回
  // 一个 promise，否则 `.then` 在 undefined 上抛错（与 factcheck 无关）。
  useSidecar: () => ({ client: { post: postMock, get: vi.fn().mockResolvedValue({ data: {} }) } }),
}));
vi.mock("@/api/client", () => ({
  subscribe: (_url: string, handlers: any) => { capturedHandlers = handlers; return () => {}; },
}));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

import { useArticle } from "@/stores/article";

describe("article factcheck", () => {
  beforeEach(() => { setActivePinia(createPinia()); postMock.mockReset(); capturedHandlers = null; });

  it("done 带 factcheck.blocked → 填充 factcheck", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    capturedHandlers.done({
      document: null, final_text: "成稿…",
      factcheck: { blocked: true, violations: [{ kind: "number", value: "15万转", number: 150000, sentence: "…", suggestion: "…" }] },
    });
    expect(a.factcheck?.blocked).toBe(true);
    expect(a.factcheck?.violations).toHaveLength(1);
    expect(a.status).toBe("done");
  });

  it("done 无 factcheck → factcheck=null", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j2" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    capturedHandlers.done({ document: "/p.md", final_text: "x" });
    expect(a.factcheck).toBeNull();
  });

  it("resolveFactcheck ok → 清 factcheck + 设 documentPath", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j3" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    a.lastJobId = "j3";
    a.factcheck = { blocked: true, violations: [] } as any;
    postMock.mockResolvedValueOnce({ data: { ok: true, document: "/out.md", format: "markdown" } });
    const r = await a.resolveFactcheck("成稿", [150000], []);
    expect(r.ok).toBe(true);
    expect(a.factcheck).toBeNull();
    expect(a.documentPath).toBe("/out.md");
  });

  it("resolveFactcheck 仍有违规 → 更新 violations 不清", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j4" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    a.lastJobId = "j4";
    postMock.mockResolvedValueOnce({ data: { ok: false, violations: [{ kind: "cert", value: "CCC", number: null, sentence: "…", suggestion: "…" }] } });
    const r = await a.resolveFactcheck("成稿", [], []);
    expect(r.ok).toBe(false);
    expect(a.factcheck?.violations).toHaveLength(1);
  });
});
