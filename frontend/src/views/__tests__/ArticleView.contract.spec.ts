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
import { useArticle, type MissingFact, type ScoreReport } from "@/stores/article";

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

  it("质检卡真渲染 完整性(warn)与综合评分(alert <60) 两行", async () => {
    // 审查 Required 修复的可见性钉子：两项必须落在真渲染的 primaryChecks
    // 大卡（而非无模板消费者的 checkItems 死代码）。
    routeQuery = {}; // 不带 keyword —— 不自动起飞，idle 下质检卡也常驻
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();

    const a = useArticle();
    const MISS: MissingFact = { kind: "number", token: "250AW", value: 250, sentence: "吸力 250AW。" };
    const LOW: ScoreReport = { total: 55, parts: [{ key: "lint", label: "禁区命中", points: 45, detail: "" }] };
    a.completeness = { checked: true, missing: [MISS] };
    a.score = LOW;
    await flushPromises();

    // 合并 #150（禁区卡进 primaryChecks）后为五卡：重复率 / 密度 / 禁区 /
    // 完整性 / 综合评分。按文本定位而非固定下标 —— 抗后续再改顺序。
    const cards = w.findAll(".qc-primary-card");
    expect(cards).toHaveLength(5);
    const compCard = cards.find((c) => c.text().includes("完整性"));
    const scoreCard = cards.find((c) => c.text().includes("综合评分"));
    expect(compCard, "完整性卡应渲染").toBeTruthy();
    expect(scoreCard, "综合评分卡应渲染").toBeTruthy();
    expect(compCard!.text()).toContain("缺 1 处");
    expect(compCard!.html()).toContain("bg-yellow-soft"); // warn Pill
    expect(scoreCard!.text()).toContain("55 分");
    expect(scoreCard!.html()).toContain("bg-red-soft"); // alert Pill（<60）
  });
});
