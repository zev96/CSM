import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useArticle, type LintHit } from "@/stores/article";

vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: vi.fn() } }) }));

// 守卫顺序的可测纯函数（与 ArticleView.onExportClick 同逻辑）：
// 返回 "factcheck" | "lint" | "export"
function exportGate(a: ReturnType<typeof useArticle>): "factcheck" | "lint" | "export" {
  if (a.factcheck?.blocked) return "factcheck";
  if (a.lintBlocking) return "lint";
  return "export";
}
const JUDGE: LintHit = { category: "absolute", text: "最佳", start: 0, end: 2, sentence: "最佳", fixable: false, suggestion: "x" };

describe("export gate order", () => {
  beforeEach(() => setActivePinia(createPinia()));
  it("factcheck 优先", () => {
    const a = useArticle();
    a.factcheck = { blocked: true, violations: [] };
    a.lint = { hits: [JUDGE], fixed_text: "" };
    expect(exportGate(a)).toBe("factcheck");
  });
  it("无 factcheck 时 lint 拦", () => {
    const a = useArticle();
    a.lint = { hits: [JUDGE], fixed_text: "" };
    expect(exportGate(a)).toBe("lint");
  });
  it("都过 → 导出", () => {
    const a = useArticle();
    expect(exportGate(a)).toBe("export");
  });
});
