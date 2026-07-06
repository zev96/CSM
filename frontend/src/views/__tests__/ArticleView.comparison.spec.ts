import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";

// ── jsdom shims ──────────────────────────────────────────────
beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true, media: q,
    addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {},
    onchange: null, dispatchEvent() { return false; },
  }));
});

// ── route query injected per-test ────────────────────────────
let routeQuery: Record<string, any> = {};
const pushMock = vi.fn();
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({ push: pushMock }),
}));

// ── capture the generate POST body via the sidecar mock ──────
const postMock = vi.fn();
const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock }, ready: true, error: null, mode: "native" }),
}));
vi.mock("@/api/client", () => ({
  subscribe: () => () => {},
}));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve(), ready: { value: true } }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("@/composables/useFailureAlert", () => ({
  failureAlert: vi.fn().mockResolvedValue("close"),
}));
vi.mock("@/stores/config", () => ({
  useConfig: () => ({ data: { user_name: "测试" }, load: vi.fn() }),
}));
// Heavy editor / panel children stubbed — irrelevant to comparison init wiring.
vi.mock("@/components/article/TiptapEditor.vue", () => ({
  default: { name: "TiptapEditor", template: "<div />" },
}));
vi.mock("@/components/article/FactCheckPanel.vue", () => ({
  default: { name: "FactCheckPanel", template: "<div />" },
}));
// ComparisonPicker（若被间接引用）拉品牌记忆 —— stub materials store。
vi.mock("@/stores/materials", () => ({
  useMaterials: () => ({ models: [], loading: false, error: null, list: vi.fn() }),
}));

import ArticleView from "@/views/ArticleView.vue";

function setupLookups() {
  getMock.mockImplementation((url: string) => {
    if (url === "/api/templates") return Promise.resolve({ data: { templates: [{ id: "tpl-a", name: "模板A" }] } });
    if (url === "/api/skills") return Promise.resolve({ data: { skills: [] } });
    // submit() also GETs /api/templates/:id for the assembly tab
    return Promise.resolve({ data: {} });
  });
}

describe("ArticleView — 横评 init 分支", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "jc" } });
    getMock.mockReset();
    setupLookups();
    routeQuery = {};
  });

  it("query mode=comparison → POST /api/generate/comparison 带 models", async () => {
    routeQuery = { keyword: "怎么选", mode: "comparison", models: "A,B", tone: "口语" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const call = postMock.mock.calls.find((c) => c[0] === "/api/generate/comparison");
    expect(call).toBeTruthy();
    expect(call![1].models).toEqual(["A", "B"]);
    expect(call![1].tone).toBe("口语");
  });

  it("无 mode（常规）不触发横评端点", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const call = postMock.mock.calls.find((c) => c[0] === "/api/generate/comparison");
    expect(call).toBeFalsy();
  });
});
