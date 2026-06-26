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

let routeQuery: Record<string, any> = {};
const pushMock = vi.fn();
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({ push: pushMock }),
}));

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
vi.mock("@/components/article/TiptapEditor.vue", () => ({
  default: { name: "TiptapEditor", template: "<div />" },
}));
vi.mock("@/components/article/FactCheckPanel.vue", () => ({
  default: { name: "FactCheckPanel", template: "<div />" },
}));

import ArticleView from "@/views/ArticleView.vue";
import { useArticle, type ChainPass } from "@/stores/article";

function setupLookups() {
  getMock.mockImplementation((url: string) => {
    if (url === "/api/templates") return Promise.resolve({ data: { templates: [{ id: "tpl-a", name: "模板A" }] } });
    if (url === "/api/skills") return Promise.resolve({ data: { skills: [] } });
    return Promise.resolve({ data: {} });
  });
}

function mkPass(over: Partial<ChainPass> = {}): ChainPass {
  return {
    index: 0, role: "persona", skill_id: "p", skill_name: "人设",
    output: "OUT", input_chars: 3, output_chars: 3, ...over,
  };
}

describe("ArticleView — skill 链", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "j1" } });
    getMock.mockReset();
    setupLookups();
    pushMock.mockReset();
    routeQuery = {};
  });

  it("query 带 skill_chain → submit 提交重建的数组", async () => {
    routeQuery = { keyword: "无线吸尘器", template_id: "tpl-a", skill_chain: "p,h,plat" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    expect(genCall).toBeTruthy();
    expect(genCall![1].skill_chain).toEqual(["p", "h", "plat"]);
  });

  it("query 无 skill_chain → submit body 无 skill_chain（零回归）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const genCall = postMock.mock.calls.find((c) => c[0] === "/api/generate");
    const body = genCall![1];
    expect(body.skill_chain == null).toBe(true);
  });

  it("有 passes 时成稿区渲染每 pass（role + skill 名 + 输出）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    a.passes = [
      mkPass({ index: 0, skill_name: "家电人设", output: "第一段输出文本" }),
      mkPass({ index: 1, role: "humanize", skill_id: "h", skill_name: "去AI味技", output: "第二段更自然" }),
    ];
    // 切到成稿 tab
    (w.vm as any).activeTab = "final";
    await flushPromises();
    const txt = w.text();
    expect(txt).toContain("家电人设");
    expect(txt).toContain("去AI味技");
    expect(txt).toContain("第一段输出文本");
    expect(txt).toContain("第二段更自然");
  });

  it("点「重跑此 pass」调 rerunPass(i)", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    const spy = vi.spyOn(a, "rerunPass").mockResolvedValue(undefined);
    a.passes = [mkPass({ index: 0, output: "A" }), mkPass({ index: 1, output: "B" })];
    (w.vm as any).activeTab = "final";
    await flushPromises();

    const btns = w.findAll("[data-rerun-pass]");
    expect(btns.length).toBe(2);
    await btns[1].trigger("click");
    expect(spy).toHaveBeenCalledWith(1);
  });

  it("有 passes 时 header 显示链 chip（skill 名 → 连）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    a.passes = [
      mkPass({ index: 0, skill_name: "人设" }),
      mkPass({ index: 1, role: "humanize", skill_name: "去AI味" }),
    ];
    await flushPromises();
    expect(w.find("[data-chain-chip]").exists()).toBe(true);
    expect(w.find("[data-chain-chip]").text()).toContain("人设");
    expect(w.find("[data-chain-chip]").text()).toContain("去AI味");
    expect(w.find("[data-chain-chip]").text()).toContain("→");
  });

  it("有 passes 时成稿区显示成本行「调用 N 次 · ≈X tokens」", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    a.passes = [
      mkPass({ index: 0, output_chars: 120 }),
      mkPass({ index: 1, output_chars: 200 }),
    ];
    (w.vm as any).activeTab = "final";
    await flushPromises();
    const txt = w.text();
    expect(txt).toContain("调用 2 次");
    // 成本行文案升级为「≈X tokens」（旧「共 X 字」已淘汰）
    expect(txt).toContain("≈");
    expect(txt).toContain("tokens");
  });

  it("无 passes（单 skill 旧路径）→ 成稿区不渲染 pass 卡 / 链 chip", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    a.finalText = "普通成稿";
    (w.vm as any).activeTab = "final";
    await flushPromises();
    expect(w.find("[data-chain-chip]").exists()).toBe(false);
    expect(w.findAll("[data-rerun-pass]").length).toBe(0);
    // 旧路径成稿编辑器仍在（TiptapEditor stub 渲染为 <div>）
    expect(w.findComponent({ name: "TiptapEditor" }).exists()).toBe(true);
  });
});
