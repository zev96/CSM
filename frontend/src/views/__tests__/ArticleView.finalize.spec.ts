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

let routeQuery: Record<string, any> = {};
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({ push: vi.fn() }),
}));
const postMock = vi.fn();
const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock }, ready: true, error: null, mode: "native" }),
}));
vi.mock("@/api/client", () => ({ subscribe: () => () => {} }));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve(), ready: { value: true } }),
}));
const toastSuccess = vi.fn();
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: toastSuccess, error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("@/composables/useFailureAlert", () => ({ failureAlert: vi.fn().mockResolvedValue("close") }));
vi.mock("@/stores/config", () => ({ useConfig: () => ({ data: { user_name: "测试" }, load: vi.fn() }) }));
vi.mock("@/components/article/TiptapEditor.vue", () => ({ default: { name: "TiptapEditor", template: "<div />" } }));
vi.mock("@/components/article/FactCheckPanel.vue", () => ({ default: { name: "FactCheckPanel", template: "<div />" } }));

import ArticleView from "@/views/ArticleView.vue";
import { useArticle } from "@/stores/article";

describe("ArticleView — 整篇润色接 finalize", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "j1" } });
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    toastSuccess.mockReset();
    routeQuery = {};
  });

  it("real 模式 polishAll → 调 article.finalize（不再调 polishWhole/polish_block）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    const spy = vi.spyOn(a, "finalize").mockResolvedValue(undefined);
    a.lastRequest = { keyword: "k", template_id: "tpl-a" } as any;
    a.lastJobId = "job-A";
    a.draftText = "初稿正文";
    a.status = "done";
    a.finalText = "成稿";
    await (w.vm as any).polishAll();
    expect(spy).toHaveBeenCalled();
  });

  it("demo 模式（无 lastRequest）polishAll → 不调 finalize（走假弹窗）", async () => {
    routeQuery = {};
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    const spy = vi.spyOn(a, "finalize").mockResolvedValue(undefined);
    vi.useFakeTimers();
    const p = (w.vm as any).polishAll();
    expect(spy).not.toHaveBeenCalled();
    await vi.runAllTimersAsync();
    await p;
    vi.useRealTimers();
    expect(spy).not.toHaveBeenCalled();
  });
});
