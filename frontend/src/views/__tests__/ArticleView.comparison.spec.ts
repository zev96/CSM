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
import { useArticle } from "@/stores/article";

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

// 终审 P1：闭环最后一跳 —— store 已有成稿（done）时「重新生成」/home 起飞进来，
// 自动起飞守卫（status==='idle'）被挡死。修法=带 takeoff 意图的 query 进来先 reset
// 非运行态 store。现有测试全用全新 store，测不到 warm-store 路径。
describe("ArticleView — warm-store 重新生成闭环（终审 P1 回归）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "jc" } });
    getMock.mockReset();
    setupLookups();
    routeQuery = {};
  });

  it("done 成稿 + 横评 query → 仍触发 submitComparison（不再静默失效）", async () => {
    const a = useArticle();
    a.status = "done";
    a.finalText = "上一篇的成稿正文";
    routeQuery = { keyword: "怎么选", mode: "comparison", models: "A,B", tone: "口语" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect(postMock.mock.calls.find((c) => c[0] === "/api/generate/comparison")).toBeTruthy();
  });

  it("done 成稿 + 常规 query → 仍触发 submit", async () => {
    const a = useArticle();
    a.status = "done";
    a.finalText = "上一篇的成稿正文";
    routeQuery = { keyword: "无线吸尘器", template_id: "tpl-a" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect(postMock.mock.calls.find((c) => c[0] === "/api/generate")).toBeTruthy();
  });

  it("running 生成中 + query → 不 reset、不抢跑（保护进行中的生成）", async () => {
    const a = useArticle();
    a.status = "running";
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect(postMock.mock.calls.find((c) => c[0] === "/api/generate")).toBeFalsy();
    expect(a.status).toBe("running");
  });
});
