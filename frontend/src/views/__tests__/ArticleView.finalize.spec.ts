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

// vi.mock 工厂被提升到文件顶部，不能引用普通 const（TDZ）。把工厂内要用的
// mock 句柄放进 vi.hoisted 一并提升，这样 sseHandlers/post/toast/failureAlert
// 在工厂里可用。routeQuery 用 getter 透传（每个用例改 .value）。
const h = vi.hoisted(() => ({
  routeQuery: { value: {} as Record<string, any> },
  sseHandlers: { value: {} as Record<string, (d: any) => void> },
  postMock: vi.fn(),
  getMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  failureAlertMock: vi.fn(),
}));
const { postMock, getMock, toastSuccess, toastError, failureAlertMock } = h;

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: h.routeQuery.value }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: h.postMock, get: h.getMock }, ready: true, error: null, mode: "native" }),
}));
vi.mock("@/api/client", () => ({
  subscribe: (_u: string, hd: Record<string, (d: any) => void>) => { h.sseHandlers.value = hd; return () => {}; },
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve(), ready: { value: true } }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: h.toastSuccess, error: h.toastError, warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("@/composables/useFailureAlert", () => ({ failureAlert: h.failureAlertMock }));
vi.mock("@/stores/config", () => ({ useConfig: () => ({ data: { user_name: "测试" }, load: vi.fn() }) }));
vi.mock("@/components/article/TiptapEditor.vue", () => ({ default: { name: "TiptapEditor", template: "<div />" } }));
vi.mock("@/components/article/FactCheckPanel.vue", () => ({ default: { name: "FactCheckPanel", template: "<div />" } }));

import ArticleView from "@/views/ArticleView.vue";
import { useArticle } from "@/stores/article";

function seedTakeoff(a: ReturnType<typeof useArticle>) {
  // 模拟起飞已完成：lastJobId + lastRequest + 已就绪初稿，status=done、finalText 空。
  a.lastJobId = "job-A";
  a.lastRequest = { keyword: "无线吸尘器", template_id: "tpl-a", skill_chain: ["人设"] } as any;
  a.draftText = "用户初稿正文";
  a.status = "done";
  a.finalText = "";
}

describe("ArticleView — 整篇润色接 finalize（真实 SSE 时序）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "job-A" } });
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    toastSuccess.mockReset();
    toastError.mockReset();
    failureAlertMock.mockReset();
    failureAlertMock.mockResolvedValue("close");
    h.sseHandlers.value = {};
    h.routeQuery.value = {};
  });

  it("polishAll → finalize POST，返回时 status=running 且未切 final；done 到达才切 final + toast", async () => {
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);
    (w.vm as any).activeTab = "draft";
    await flushPromises();

    await (w.vm as any).polishAll();
    await flushPromises();
    // finalize 流式：POST 已发、status=running、还没切 final、没弹成功 toast
    expect(postMock).toHaveBeenCalledWith("/api/generate/job-A/finalize", expect.objectContaining({ draft: "用户初稿正文" }));
    expect(a.status).toBe("running");
    expect((w.vm as any).activeTab).not.toBe("final");
    expect(toastSuccess).not.toHaveBeenCalled();

    // SSE done 到达 → 切 final + 成功 toast
    h.sseHandlers.value.done({ final_text: "成稿正文", passes: [], document: null, draft: "用户初稿正文", title: "T" });
    await flushPromises();
    expect(a.finalText).toBe("成稿正文");
    expect((w.vm as any).activeTab).toBe("final");
    expect(toastSuccess).toHaveBeenCalledWith("整篇润色完成");
  });

  it("done 带 factcheck.blocked → 不切 final（审查面板接管）", async () => {
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);
    (w.vm as any).activeTab = "draft";
    await flushPromises();

    await (w.vm as any).polishAll();
    await flushPromises();
    h.sseHandlers.value.done({ final_text: "越界成稿", passes: [], factcheck: { blocked: true, violations: [] }, draft: "用户初稿正文", title: "T" });
    await flushPromises();
    expect((w.vm as any).activeTab).not.toBe("final");
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("finalize POST 失败 → 弹失败 modal、不切 final（store 把 status 置 error，由既有 error watcher 接管 $reset/回首页）", async () => {
    // 说明：finalize 设 status=error 后，既有的 watch(status) error 分支会
    // failureAlert→$reset，所以组件层 status 最终回 idle（不是 error）。
    // 「POST 失败保留旧 draftText」是 store 层契约，已在 article.finalize.spec
    // 覆盖；这里只断言组件层可观察行为：失败弹窗触发、绝不切成稿 tab。
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);
    (w.vm as any).activeTab = "draft";
    await flushPromises();
    postMock.mockRejectedValueOnce({ response: { data: { detail: "plan cache miss" } } });
    await (w.vm as any).polishAll();
    await flushPromises();
    expect(failureAlertMock).toHaveBeenCalled();        // 失败 modal 触发
    expect((w.vm as any).activeTab).not.toBe("final");  // 绝不切成稿
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("demo 模式（无 lastRequest）polishAll → 不 POST finalize（走假弹窗）", async () => {
    h.routeQuery.value = {};
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    a.lastRequest = null as any;  // 确保 demo
    vi.useFakeTimers();
    const p = (w.vm as any).polishAll();
    expect(postMock).not.toHaveBeenCalledWith(expect.stringContaining("/finalize"), expect.anything());
    await vi.runAllTimersAsync();
    await p;
    vi.useRealTimers();
  });
});
