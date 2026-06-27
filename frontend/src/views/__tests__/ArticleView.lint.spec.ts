import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";

beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true, media: q,
    addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {},
    onchange: null, dispatchEvent() { return false; },
  }));
});

// vi.mock 工厂提升到顶部，mock 句柄放进 vi.hoisted 一并提升。
const h = vi.hoisted(() => ({
  routeQuery: { value: {} as Record<string, any> },
  postMock: vi.fn(),
  getMock: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: h.routeQuery.value }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: h.postMock, get: h.getMock }, ready: true, error: null, mode: "native" }),
}));
vi.mock("@/api/client", () => ({
  subscribe: () => () => {},
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve(), ready: { value: true } }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("@/composables/useFailureAlert", () => ({ failureAlert: vi.fn() }));
vi.mock("@/stores/config", () => ({ useConfig: () => ({ data: { user_name: "测试" }, load: vi.fn() }) }));
vi.mock("@/components/article/TiptapEditor.vue", () => ({ default: { name: "TiptapEditor", template: "<div />" } }));
// FactCheckPanel 整体 stub（断言只看 showFactcheck ref，不进面板内部）；LintPanel
// 保持真实渲染，这样 findComponent(LintPanel).vm.$emit("proceed") 才走到模板里
// 真实的 @proceed="onExportClick" 绑定（覆盖 C1 重入守卫）。
vi.mock("@/components/article/FactCheckPanel.vue", () => ({ default: { name: "FactCheckPanel", template: "<div />" } }));

import ArticleView from "@/views/ArticleView.vue";
import LintPanel from "@/components/article/LintPanel.vue";
import { useArticle, type LintHit } from "@/stores/article";

const JUDGE: LintHit = { category: "absolute", text: "最佳", start: 0, end: 2, sentence: "最佳", fixable: false, suggestion: "x" };

async function mountView() {
  h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
  const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
  await flushPromises();
  return w;
}

describe("ArticleView — 导出守卫链（真实 onExportClick）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    h.postMock.mockReset();
    h.postMock.mockResolvedValue({ data: {} });
    h.getMock.mockReset();
    h.getMock.mockResolvedValue({ data: {} });
    h.routeQuery.value = {};
  });

  it("factcheck.blocked → onExportClick 开 FactCheckPanel（不开导出 modal）", async () => {
    const w = await mountView();
    const a = useArticle();
    a.factcheck = { blocked: true, violations: [] };
    a.lint = { hits: [JUDGE], fixed_text: "" };
    (w.vm as any).onExportClick();
    await flushPromises();
    expect((w.vm as any).showFactcheck).toBe(true);
    expect((w.vm as any).showExportModal).toBe(false);
  });

  it("仅 lint 拦 → onExportClick 开 LintPanel（不开导出 modal）", async () => {
    const w = await mountView();
    const a = useArticle();
    a.lint = { hits: [JUDGE], fixed_text: "" };
    // watch(lintBlocking) 已自动弹 showLint —— 先复位以纯测 onExportClick 自身。
    (w.vm as any).showLint = false;
    await flushPromises();
    (w.vm as any).onExportClick();
    await flushPromises();
    expect((w.vm as any).showLint).toBe(true);
    expect((w.vm as any).showExportModal).toBe(false);
  });

  it("都过 → onExportClick 开导出 modal", async () => {
    const w = await mountView();
    (w.vm as any).onExportClick();
    await flushPromises();
    expect((w.vm as any).showExportModal).toBe(true);
    expect((w.vm as any).showFactcheck).toBe(false);
    expect((w.vm as any).showLint).toBe(false);
  });

  it("双失败 unstick（C1）：factcheck+lint 同拦，清 lint 后 LintPanel proceed 经 onExportClick 重入 → 回 FactCheckPanel，导出 modal 不开", async () => {
    const w = await mountView();
    const a = useArticle();
    a.factcheck = { blocked: true, violations: [] };
    a.lint = { hits: [JUDGE], fixed_text: "" };
    await flushPromises();
    expect(a.lintBlocking).toBe(true);

    // 用户在 LintPanel 里放行所有 lint 命中 → lintBlocking 转 false，factcheck 仍 blocked
    a.toggleLintRelease(JUDGE);
    await flushPromises();
    expect(a.lintBlocking).toBe(false);
    expect(a.factcheck?.blocked).toBe(true);

    // 真实 LintPanel emit proceed → 模板 @proceed="onExportClick" 重入守卫链
    const panel = w.findComponent(LintPanel);
    panel.vm.$emit("proceed");
    await flushPromises();

    // factcheck 仍 blocked → 回 FactCheckPanel，绝不直接开导出 modal（旁路已堵）
    expect((w.vm as any).showFactcheck).toBe(true);
    expect((w.vm as any).showExportModal).toBe(false);
  });
});
