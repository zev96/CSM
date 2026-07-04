import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn();
const get = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post, get } }),
}));
// 捕获 subscribe 的 handler map，直接驱动 done 事件（jsdom 无真 EventSource）
// —— 与 article.chain.spec.ts 同款装置。done handler 会推完成通知，一并 mock。
let sseHandlers: Record<string, (d: any) => void> = {};
vi.mock("@/api/client", () => ({
  subscribe: (_url: string, handlers: Record<string, (d: any) => void>) => {
    sseHandlers = handlers;
    return () => {};
  },
}));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

import { useArticle, type MissingFact, type ScoreReport } from "@/stores/article";

const REPORT: ScoreReport = {
  total: 72.5,
  parts: [{ key: "lint", label: "禁区命中", points: 12, detail: "3 处" }],
};

describe("article score/completeness", () => {
  beforeEach(() => { setActivePinia(createPinia()); post.mockReset(); sseHandlers = {}; });

  it("runScore 存报告（形状校验）", async () => {
    post.mockResolvedValue({ data: REPORT });
    const a = useArticle();
    await a.runScore("正文");
    expect(a.score?.total).toBe(72.5);
  });

  it("runScore 非法形状 fail-open null", async () => {
    post.mockResolvedValue({ data: { foo: 1 } });
    const a = useArticle();
    await a.runScore("正文");
    expect(a.score).toBeNull();
  });

  it("runScore 带核对信号", async () => {
    post.mockResolvedValue({ data: REPORT });
    const a = useArticle();
    a.factcheck = { blocked: true, violations: [{ kind: "number", value: "9W", number: 9, sentence: "", suggestion: "" }] };
    a.completeness = { checked: true, missing: [{ kind: "cert", token: "CCC", value: null, sentence: "" }] };
    await a.runScore("正文");
    expect(post.mock.calls[0][1]).toEqual({
      text: "正文", factcheck_violations: 1, completeness_missing: 1,
    });
  });

  it("done 事件接 completeness + 自动评分（真实 SSE handler 驱动）", async () => {
    const MISS: MissingFact = { kind: "cert", token: "CCC", value: null, sentence: "已通过 CCC。" };
    // /api/generate → job_id；其余 POST（/api/lint、/api/score）→ REPORT。
    // lint 收到 REPORT（无 hits）会 fail-open null —— 既有跨文件守卫行为。
    post.mockImplementation((url: string) =>
      url === "/api/generate"
        ? Promise.resolve({ data: { job_id: "j1" } })
        : Promise.resolve({ data: REPORT }));
    const a = useArticle();
    // 先污染两字段，验证 submit reset 会清空
    a.completeness = { checked: true, missing: [MISS] };
    a.score = REPORT;
    await a.submit({ keyword: "k", template_id: "t" });
    expect(a.completeness).toBeNull();
    expect(a.score).toBeNull();
    // 驱动 done：带 completeness + final_text（触发自动 lint + score）
    sseHandlers.done({
      final_text: "成稿正文",
      completeness: { checked: true, missing: [MISS] },
    });
    await new Promise((r) => setTimeout(r, 0)); // 等 void runScore 的微任务落定
    expect(a.completeness).toEqual({ checked: true, missing: [MISS] });
    // 自动评分触发：/api/score 被调，且 completeness_missing 已计入
    const scoreCall = post.mock.calls.find((c) => c[0] === "/api/score");
    expect(scoreCall).toBeTruthy();
    expect(scoreCall![1]).toEqual({
      text: "成稿正文", factcheck_violations: 0, completeness_missing: 1,
    });
    expect(a.score?.total).toBe(72.5);
  });

  it("done 事件无 completeness 键（旧事件）→ completeness 保持 null 不崩", async () => {
    post.mockImplementation((url: string) =>
      url === "/api/generate"
        ? Promise.resolve({ data: { job_id: "j2" } })
        : Promise.resolve({ data: REPORT }));
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    sseHandlers.done({ final_text: "成稿", title: "T" });
    await new Promise((r) => setTimeout(r, 0));
    expect(a.completeness).toBeNull();
    expect(a.status).toBe("done");
  });
});
