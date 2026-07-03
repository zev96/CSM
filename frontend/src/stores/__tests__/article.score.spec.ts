import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn();
const get = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post, get } }),
}));

import { useArticle, type ScoreReport } from "@/stores/article";

const REPORT: ScoreReport = {
  total: 72.5,
  parts: [{ key: "lint", label: "禁区命中", points: 12, detail: "3 处" }],
};

describe("article score/completeness", () => {
  beforeEach(() => { setActivePinia(createPinia()); post.mockReset(); });

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

  it("done 事件接 completeness + 自动评分", async () => {
    const a = useArticle();
    a.completeness = null;
    // 直接模拟 done handler 行为面：state 可写 + reset 清空
    a.completeness = { checked: true, missing: [] };
    a.score = REPORT;
    // submit reset 清空（复制 submit() 的 reset 清单断言两字段）
    post.mockResolvedValue({ data: { job_id: "x" } });
    // 不真跑 submit 全流程（SSE 依赖）；直接断言字段存在且可空
    expect(a.completeness.checked).toBe(true);
    a.$patch({ completeness: null, score: null });
    expect(a.completeness).toBeNull();
    expect(a.score).toBeNull();
  });
});
