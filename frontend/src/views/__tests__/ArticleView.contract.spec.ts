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
// Heavy editor / panel children stubbed — irrelevant to contract wiring.
vi.mock("@/components/article/TiptapEditor.vue", () => ({
  default: { name: "TiptapEditor", template: "<div />" },
}));
vi.mock("@/components/article/FactCheckPanel.vue", () => ({
  default: { name: "FactCheckPanel", template: "<div />" },
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

describe("ArticleView — 契约 query 透传", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "j1" } });
    getMock.mockReset();
    setupLookups();
    pushMock.mockReset();
    routeQuery = {};
  });

  it("query contract=aggressive → submit 带 contract_mode:aggressive", async () => {
    routeQuery = { keyword: "无线吸尘器", template_id: "tpl-a", contract: "aggressive" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    expect(genCall).toBeTruthy();
    const body = genCall![1];
    expect(body.contract_mode).toBe("aggressive");
  });

  it("query contract=conservative → submit 带 contract_mode:conservative", async () => {
    routeQuery = { keyword: "无线吸尘器", template_id: "tpl-a", contract: "conservative" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    const body = genCall![1];
    expect(body.contract_mode).toBe("conservative");
  });

  it("query 无 contract → submit body 无该键（undefined）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    const body = genCall![1];
    expect(body.contract_mode).toBeUndefined();
  });

  it("query contract=garbage → submit body 无该键（undefined，不透传非法值）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a", contract: "garbage" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    const body = genCall![1];
    expect(body.contract_mode).toBeUndefined();
  });
});
