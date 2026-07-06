import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";

const listRecentMock = vi.fn();
const factsDiffMock = vi.fn();
vi.mock("@/api/client", () => ({
  listRecent: (...a: any[]) => listRecentMock(...a),
  factsDiff: (...a: any[]) => factsDiffMock(...a),
}));
const pushMock = vi.fn();
vi.mock("vue-router", () => ({ useRouter: () => ({ push: pushMock }) }));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ info: vi.fn(), success: vi.fn(), warn: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/composables/useConfirm", () => ({ confirmDialog: vi.fn().mockResolvedValue(true) }));

import RecentHistoryView from "@/views/RecentHistoryView.vue";

const staleDoc = {
  path: "/h/a.md", filename: "a.md", title: "过期文章", template_name: "tpl",
  words: 1000, modified_at: "2026-07-05T00:00:00Z", format: "markdown" as const,
  facts_stale: true, stale_models: ["戴森V12"],
  record: {
    keyword: "无线吸尘器", template_id: "tpl-a", title: "过期文章",
    angle_json: '{"audience":"铲屎官","sellpoints":["防缠绕"],"tone":"口语"}',
    skill_chain_json: '["人设"]', mode: "normal", models_json: null, contract_mode: "aggressive",
  },
};
const freshDoc = {
  path: "/h/b.md", filename: "b.md", title: "正常文章", template_name: "tpl",
  words: 500, modified_at: "2026-07-05T01:00:00Z", format: "markdown" as const,
  facts_stale: false, stale_models: [], record: null,
};

beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true, media: q, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, onchange: null, dispatchEvent() { return false; },
  }));
});

describe("RecentHistoryView — §7.3 过期徽章 + 重新生成", () => {
  beforeEach(() => {
    pushMock.mockReset();
    listRecentMock.mockReset();
    factsDiffMock.mockReset();
    listRecentMock.mockResolvedValue({ count: 2, documents: [staleDoc, freshDoc] });
  });

  it("stale doc 显示「参数已变更」+「重新生成」；只此一条有重生成钮", async () => {
    const w = mount(RecentHistoryView);
    await flushPromises();
    expect(w.text()).toContain("参数已变更");
    const regenBtns = w.findAll("button").filter((b) => b.text().includes("重新生成"));
    expect(regenBtns.length).toBe(1); // fresh doc（record=null）不显示
  });

  it("点「重新生成」→ router.push 带对齐 ArticleView 的 query", async () => {
    const w = mount(RecentHistoryView);
    await flushPromises();
    const regenBtn = w.findAll("button").find((b) => b.text().includes("重新生成"))!;
    await regenBtn.trigger("click");
    expect(pushMock).toHaveBeenCalledWith({
      name: "article",
      query: {
        keyword: "无线吸尘器", title: "过期文章", template_id: "tpl-a",
        skill_chain: "人设", contract: "aggressive",
        audience: "铲屎官", sellpoints: "防缠绕", tone: "口语",
      },
    });
  });

  it("点「参数已变更」→ 取 factsDiff（按需字段 diff）", async () => {
    factsDiffMock.mockResolvedValue({
      model: "戴森V12", changed: [{ field: "吸力", old: "150AW", new: "230AW" }],
    });
    const w = mount(RecentHistoryView);
    await flushPromises();
    const pillBtn = w.findAll("button").find((b) => b.text().includes("参数已变更"))!;
    await pillBtn.trigger("click");
    await flushPromises();
    expect(factsDiffMock).toHaveBeenCalledWith("戴森V12");
  });
});
