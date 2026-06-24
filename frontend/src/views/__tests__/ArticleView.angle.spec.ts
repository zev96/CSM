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
// Heavy editor / panel children stubbed — irrelevant to angle wiring.
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

describe("ArticleView — 从 query 重建角度", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "j1" } });
    getMock.mockReset();
    setupLookups();
    pushMock.mockReset();
    routeQuery = {};
  });

  it("query 带角度 → submit 提交重建的 angle 对象 + title", async () => {
    routeQuery = {
      keyword: "无线吸尘器",
      template_id: "tpl-a",
      audience: "铲屎官",
      sellpoints: "防缠绕技术,续航时间",
      tone: "口语",
      title: "无线吸尘器哪款好用",
    };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    expect(genCall).toBeTruthy();
    const body = genCall![1];
    expect(body.keyword).toBe("无线吸尘器");
    expect(body.title).toBe("无线吸尘器哪款好用");
    expect(body.angle).toEqual({
      audience: "铲屎官",
      sellpoints: ["防缠绕技术", "续航时间"],
      tone: "口语",
    });
  });

  it("空 sellpoints query → [] ; 缺失 facet → null", async () => {
    routeQuery = {
      keyword: "k",
      template_id: "tpl-a",
      audience: "宝妈",
      // 无 sellpoints / tone / title
    };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    const body = genCall![1];
    expect(body.angle).toEqual({ audience: "宝妈", sellpoints: [], tone: null });
    expect(body.title == null || body.title === "").toBe(true);
  });

  it("query 无任何角度 → submit 不带 angle/title（今天行为）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    const body = genCall![1];
    expect(body.angle == null).toBe(true);
    expect(body.title == null || body.title === "").toBe(true);
  });

  it("有 facet 时 header 显示角度 chip（铲屎官·防缠绕·口语）", async () => {
    routeQuery = {
      keyword: "k",
      template_id: "tpl-a",
      audience: "铲屎官",
      sellpoints: "防缠绕技术",
      tone: "口语",
    };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect(w.text()).toContain("铲屎官");
    expect(w.text()).toContain("口语");
  });

  it("无 facet 时 header 不显示角度 chip", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    // 角度 chip 用 data-angle-chip 标识，未设置时不渲染
    expect(w.find("[data-angle-chip]").exists()).toBe(false);
  });
});
