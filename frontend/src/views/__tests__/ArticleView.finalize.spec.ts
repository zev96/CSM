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
  toastWarn: vi.fn(),
  failureAlertMock: vi.fn(),
  confirmMock: vi.fn(),
}));
const { postMock, getMock, toastSuccess, toastError, toastWarn, failureAlertMock, confirmMock } = h;

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
  useToast: () => ({ success: h.toastSuccess, error: h.toastError, warn: h.toastWarn, info: vi.fn() }),
}));
vi.mock("@/composables/useFailureAlert", () => ({ failureAlert: h.failureAlertMock }));
vi.mock("@/composables/useConfirm", () => ({ confirmDialog: h.confirmMock }));
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
    toastWarn.mockReset();
    failureAlertMock.mockReset();
    failureAlertMock.mockResolvedValue("close");
    confirmMock.mockReset();
    confirmMock.mockResolvedValue(true);
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

  // 整篇润色是从毛坯文重跑整条链，成稿被整段替换。成稿编辑器修好之前它被
  // pass 条带挤成 0 高、根本改不了，所以没人撞得到；现在能改了，得先问一句。
  it("成稿已有内容 → 先确认；点取消不发 finalize、成稿原样保留", async () => {
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);
    a.finalText = "我在成稿里改过的正文";
    confirmMock.mockResolvedValue(false);

    await (w.vm as any).polishAll();

    expect(confirmMock).toHaveBeenCalled();
    expect(postMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/finalize"), expect.anything());
    expect(a.finalText).toBe("我在成稿里改过的正文");
  });

  it("确认后照常润色", async () => {
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);
    a.finalText = "我在成稿里改过的正文";
    confirmMock.mockResolvedValue(true);

    await (w.vm as any).polishAll();

    expect(postMock).toHaveBeenCalledWith(
      "/api/generate/job-A/finalize", expect.objectContaining({ draft: "用户初稿正文" }));
  });

  it("起飞后在右栏换 skill → 整篇润色带界面当前所选（不再用起飞快照）", async () => {
    // 用户报「软件没有通过我设置的润色 skill 去润色」：下拉改的是视图 ref，
    // finalize 却读起飞快照 —— 下拉成了摆设。现在 polishAll 必须把当前所选
    // 传给 finalize。
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a); // 快照里是 skill_chain: ["人设"]
    (w.vm as any).skillId = "空气净化器家电博主";
    await flushPromises();

    await (w.vm as any).polishAll();
    await flushPromises();

    const call = postMock.mock.calls.find((c) => String(c[0]).includes("/finalize"));
    expect(call).toBeTruthy();
    expect(call![1].skill_id).toBe("空气净化器家电博主");
    // 视图里没有链（query 未带）→ 明确送 null，后端退回单 skill_id
    expect(call![1].skill_chain).toBeNull();
  });

  it("mount 时从 lastRequest 回填 skillId/skillChain（leftnav 直进不丢起飞参数）", async () => {
    // 「视图为真相源」的另一半：不带 query 直进创作区时，视图 ref 必须先从
    // 起飞快照回填，否则 polishAll 会把快照里的 skill/链静默降级成空。
    const a = useArticle();
    seedTakeoff(a);
    a.lastRequest = {
      keyword: "k", template_id: "t",
      skill_id: "sk-A", skill_chain: ["链A", "链B"],
    } as any;
    h.routeQuery.value = {};
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect((w.vm as any).skillId).toBe("sk-A");
    expect((w.vm as any).skillChain).toEqual(["链A", "链B"]);
  });

  it("home 新起飞（带 keyword query）不回填旧快照的 skill/链 —— 不污染新起飞", async () => {
    // 上一单（可能已取消）的 lastRequest 里带链；这次从 home 故意不选链、
    // 新关键词起飞（home 从不带 skill_id，空链不入 query）。回填若不区分
    // 「新起飞」和「leftnav 回看」，旧链会被静默写进新 takeoff 请求，且界面
    // 上完全不可见。
    const a = useArticle();
    a.lastRequest = {
      keyword: "旧词", template_id: "tpl-a",
      skill_id: "旧skill", skill_chain: ["旧链"],
    } as any;
    a.status = "idle";
    h.routeQuery.value = { keyword: "新词", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect((w.vm as any).skillId).toBe("");
    expect((w.vm as any).skillChain).toEqual([]);
    // 自动起飞的 POST body 不含旧 skill/旧链
    const gen = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    expect(gen).toBeTruthy();
    expect(gen![1].skill_id).toBeUndefined();
    expect(gen![1].skill_chain).toBeUndefined();
  });

  it("done 的 passes 带 guard_note → 弹保护提示 warn toast（回退不静默）", async () => {
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);
    (w.vm as any).activeTab = "draft";
    await flushPromises();

    await (w.vm as any).polishAll();
    await flushPromises();
    h.sseHandlers.value.done({
      final_text: "成稿正文",
      passes: [{
        index: 0, role: "persona", skill_id: null, skill_name: "",
        output: "成稿正文", input_chars: 1, output_chars: 1,
        guard_note: "卡片标题行被改写或删除 —— 本轮润色已回退",
      }],
      document: null, draft: "用户初稿正文", title: "T",
    });
    await flushPromises();
    expect(toastWarn).toHaveBeenCalledTimes(1);
    expect(String(toastWarn.mock.calls[0][0])).toContain("守卫");
  });

  it("done 的 passes 无 guard_note → 不弹 warn（零打扰）", async () => {
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);
    await (w.vm as any).polishAll();
    await flushPromises();
    h.sseHandlers.value.done({
      final_text: "成稿正文",
      passes: [{
        index: 0, role: "persona", skill_id: "s", skill_name: "S",
        output: "成稿正文", input_chars: 1, output_chars: 1, guard_note: null,
      }],
      document: null, draft: "用户初稿正文", title: "T",
    });
    await flushPromises();
    expect(toastWarn).not.toHaveBeenCalled();
  });

  it("成稿为空 → 不打扰，直接润色（零回归）", async () => {
    h.routeQuery.value = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    seedTakeoff(a);   // finalText = ""

    await (w.vm as any).polishAll();

    expect(confirmMock).not.toHaveBeenCalled();
    expect(postMock).toHaveBeenCalledWith(
      "/api/generate/job-A/finalize", expect.anything());
  });
});
