import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

// mock sidecar client（参考 article.finalize.spec.ts 的 mock 写法）
const post = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post } }),
}));

import { useArticle, type LintHit } from "@/stores/article";

const HIT: LintHit = {
  category: "absolute", text: "最佳", start: 0, end: 2,
  sentence: "最佳之选", fixable: false, suggestion: "改写",
};
const EMOJI: LintHit = {
  category: "emoji", text: "😀", start: 2, end: 3,
  sentence: "最佳😀", fixable: true, suggestion: "删",
};

describe("article lint", () => {
  beforeEach(() => { setActivePinia(createPinia()); post.mockReset(); });

  it("runLint 存结果并清放行", async () => {
    post.mockResolvedValue({ data: { hits: [HIT], fixed_text: "最佳" } });
    const a = useArticle();
    a.lintReleased = ["x"];
    await a.runLint("最佳😀");
    expect(a.lint?.hits).toHaveLength(1);
    expect(a.lintReleased).toEqual([]);
    expect(a.lintBlocking).toBe(true);
  });

  it("autofixLint 置 finalText=fixed_text 并重扫", async () => {
    const a = useArticle();
    a.lint = { hits: [HIT, EMOJI], fixed_text: "最佳" };
    post.mockResolvedValue({ data: { hits: [HIT], fixed_text: "最佳" } });
    await a.autofixLint();
    expect(a.finalText).toBe("最佳");
    expect(a.lint?.hits.every((h) => !h.fixable)).toBe(true);
  });

  it("放行后 lintBlocking 转 false", async () => {
    const a = useArticle();
    a.lint = { hits: [HIT], fixed_text: "最佳" };
    expect(a.lintBlocking).toBe(true);
    a.toggleLintRelease(HIT);
    expect(a.lintBlocking).toBe(false);
    expect(a.lintUnresolved).toBe(0);
  });

  it("runLint 失败 fail-open（lint=null，不拦）", async () => {
    post.mockRejectedValue(new Error("net"));
    const a = useArticle();
    await a.runLint("x");
    expect(a.lint).toBeNull();
    expect(a.lintBlocking).toBe(false);
  });
});
