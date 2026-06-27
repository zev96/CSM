import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import LintPanel from "@/components/article/LintPanel.vue";
import { useArticle, type LintHit } from "@/stores/article";

vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: vi.fn() } }) }));

const MECH: LintHit = { category: "emoji", text: "😀", start: 0, end: 1, sentence: "😀", fixable: true, suggestion: "删" };
const JUDGE: LintHit = { category: "absolute", text: "最佳", start: 1, end: 3, sentence: "x最佳", fixable: false, suggestion: "改写" };

function mountPanel() {
  return mount(LintPanel, { props: { open: true }, global: { stubs: { teleport: true } } });
}

describe("LintPanel", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("渲染命中项", () => {
    const a = useArticle();
    a.lint = { hits: [MECH, JUDGE], fixed_text: "最佳" };
    const w = mountPanel();
    expect(w.findAll("[data-lint-hit]")).toHaveLength(2);
  });

  it("一键清调 autofixLint", async () => {
    const a = useArticle();
    a.lint = { hits: [MECH], fixed_text: "" };
    const spy = vi.spyOn(a, "autofixLint").mockResolvedValue();
    const w = mountPanel();
    await w.find("[data-lint-autofix]").trigger("click");
    expect(spy).toHaveBeenCalled();
  });

  it("确认并导出仅在不拦时可点、emit proceed", async () => {
    const a = useArticle();
    a.lint = { hits: [JUDGE], fixed_text: "x最佳" };
    const w = mountPanel();
    expect(w.find("[data-lint-proceed]").attributes("disabled")).toBeDefined();
    a.toggleLintRelease(JUDGE);                 // 放行后可点
    await w.vm.$nextTick();
    expect(w.find("[data-lint-proceed]").attributes("disabled")).toBeUndefined();
    await w.find("[data-lint-proceed]").trigger("click");
    expect(w.emitted("proceed")).toBeTruthy();
  });
});
