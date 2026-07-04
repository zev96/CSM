import { mount, flushPromises, type VueWrapper } from "@vue/test-utils";
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
vi.mock("@/components/article/FactCheckPanel.vue", () => ({ default: { name: "FactCheckPanel", template: "<div />" } }));

import ArticleView from "@/views/ArticleView.vue";
import LintPanel from "@/components/article/LintPanel.vue";
import { useArticle, type LintHit } from "@/stores/article";

const HIT_A: LintHit = { category: "absolute", text: "最佳", start: 0, end: 2, sentence: "全网最佳", fixable: false, suggestion: "x" };
const HIT_B: LintHit = { category: "meta_speak", text: "众所周知", start: 5, end: 9, sentence: "众所周知这样", fixable: false, suggestion: "y" };

// 冷环境（CI 冷 transform 缓存 / 并行 worker）下 flushPromises 后渲染仍
// 可能没 settle，直断会负载敏感 flake —— 正向断言一律 waitFor 化。
const WAIT = { timeout: 5000 };

// 空 query mount —— 右栏质检卡无条件渲染，一级卡列表只受
// panelMode==='checks'（默认值）控制，不需要起飞。等一级卡真的
// 渲染出来再返回。
async function mountView() {
  const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
  await flushPromises();
  await vi.waitFor(() => {
    expect(w.findAll("button.qc-primary-card").length).toBeGreaterThan(0);
  }, WAIT);
  return w;
}

function findCards(w: VueWrapper<InstanceType<typeof ArticleView>>) {
  return w.findAll("button.qc-primary-card");
}
function lintCard(w: VueWrapper<InstanceType<typeof ArticleView>>) {
  const card = findCards(w).find((c) => c.text().includes("禁区"));
  expect(card, "一级质检卡应包含「禁区」卡").toBeTruthy();
  // 钉「实际可见」而不只是「存在于 DOM」—— v-show/inline display 隐藏也算回归。
  expect(card!.isVisible(), "「禁区」卡应实际可见").toBe(true);
  return card!;
}

describe("ArticleView — 一级质检卡渲染（primaryChecks）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    h.postMock.mockReset();
    h.postMock.mockResolvedValue({ data: {} });
    h.getMock.mockReset();
    h.getMock.mockResolvedValue({ data: {} });
    h.routeQuery.value = {};
  });

  it("渲染五张大卡：重复率·历史 / 关键词密度 / 禁区 / 完整性 / 综合评分（禁区钉 PR#148 可见性，完整性/综合评分为 Phase 4+）", async () => {
    const w = await mountView();
    const texts = findCards(w).map((c) => c.text());
    expect(texts.some((t) => t.includes("重复率"))).toBe(true);
    expect(texts.some((t) => t.includes("关键词密度"))).toBe(true);
    expect(texts.some((t) => t.includes("禁区"))).toBe(true);
    expect(texts.some((t) => t.includes("完整性"))).toBe(true);
    expect(texts.some((t) => t.includes("综合评分"))).toBe(true);
    expect(texts).toHaveLength(5);
  });

  it("禁区卡未检查（lint=null）→ 值为 — 且徽章「通过」（不软拦导出即通过）", async () => {
    const w = await mountView();
    const text = lintCard(w).text();
    expect(text).toContain("—");
    expect(text).toContain("通过");
    expect(text).not.toContain("复查");
  });

  it("禁区卡有未处理违规 → 「N 处」+ 徽章「复查」", async () => {
    const w = await mountView();
    const a = useArticle();
    a.lint = { hits: [HIT_A, HIT_B], fixed_text: "" };
    await vi.waitFor(() => {
      const text = lintCard(w).text();
      expect(text).toContain("2 处");
      expect(text).toContain("复查");
    }, WAIT);
  });

  it("禁区卡命中全部放行 → 「无」+ 徽章「通过」", async () => {
    const w = await mountView();
    const a = useArticle();
    a.lint = { hits: [HIT_A], fixed_text: "" };
    a.toggleLintRelease(HIT_A);
    await vi.waitFor(() => {
      const text = lintCard(w).text();
      expect(text).toContain("无");
      expect(text).toContain("通过");
    }, WAIT);
  });

  it("点击禁区卡（有报告）→ 打开 LintPanel", async () => {
    const w = await mountView();
    const a = useArticle();
    a.lint = { hits: [HIT_A], fixed_text: "" };
    // 等卡片 patch 到新状态再取 wrapper 点击，避免点到被替换前的旧节点。
    await vi.waitFor(() => { expect(lintCard(w).text()).toContain("1 处"); }, WAIT);
    // watch(lintBlocking) 已自动弹 showLint —— 先复位以纯测卡片点击自身。
    (w.vm as any).showLint = false;
    await flushPromises();
    // 复位真的写穿了再点击 —— 防 watch 残留 true 让本测试恒真空转。
    expect((w.vm as any).showLint).toBe(false);
    await lintCard(w).trigger("click");
    await vi.waitFor(() => {
      expect((w.vm as any).showLint).toBe(true);
      // ref 翻转 ≠ 面板真开 —— 钉住 v-model:open 直通 LintPanel 这最后一环。
      expect(w.findComponent(LintPanel).props("open")).toBe(true);
    }, WAIT);
  });

  it("成稿 lint 命中（lintBlocking false→true）→ 自动弹 LintPanel", async () => {
    const w = await mountView();
    const a = useArticle();
    a.lint = { hits: [HIT_A], fixed_text: "" };
    await vi.waitFor(() => {
      expect((w.vm as any).showLint).toBe(true);
      expect(w.findComponent(LintPanel).props("open")).toBe(true);
    }, WAIT);
  });

  it("未检查（lint=null）点击禁区卡 → 不开空面板", async () => {
    const w = await mountView();
    await lintCard(w).trigger("click");
    await flushPromises();
    expect((w.vm as any).showLint).toBe(false);
    expect(w.findComponent(LintPanel).props("open")).toBe(false);
  });

  it("有成稿但报告被 fail-open 清空（lint=null）→ 点卡同样不开面板", async () => {
    const w = await mountView();
    const a = useArticle();
    a.finalText = "正文在这里";
    await flushPromises();
    await lintCard(w).trigger("click");
    await flushPromises();
    expect((w.vm as any).showLint).toBe(false);
    expect(w.findComponent(LintPanel).props("open")).toBe(false);
  });

  it("干净报告（无命中）点禁区卡 → 面板打开且标题不误报违规", async () => {
    const w = await mountView();
    const a = useArticle();
    a.lint = { hits: [], fixed_text: "" };
    // 值从「—」patch 成「无」后再点击，保证点的是当前节点。
    await vi.waitFor(() => { expect(lintCard(w).text()).toContain("无"); }, WAIT);
    await lintCard(w).trigger("click");
    await vi.waitFor(() => {
      expect(w.findComponent(LintPanel).props("open")).toBe(true);
      const panelText = w.findComponent(LintPanel).text();
      expect(panelText).toContain("未发现违规");
      expect(panelText).not.toContain("发现违规措辞/标点");
    }, WAIT);
  });
});
