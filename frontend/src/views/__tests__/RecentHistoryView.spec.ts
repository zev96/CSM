import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";

const listRecentMock = vi.fn();
vi.mock("@/api/client", () => ({
  listRecent: (...a: any[]) => listRecentMock(...a),
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

const docA = {
  path: "/h/a.md", filename: "a.md", title: "第一篇", template_name: "tpl",
  words: 1000, modified_at: "2026-07-05T00:00:00Z", format: "markdown" as const,
};
const docB = {
  path: "/h/b.docx", filename: "b.docx", title: "第二篇", template_name: null,
  words: 500, modified_at: "2026-07-05T01:00:00Z", format: "docx" as const,
};

beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true, media: q, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, onchange: null, dispatchEvent() { return false; },
  }));
});

describe("RecentHistoryView — 列表 + 清除记录", () => {
  beforeEach(() => {
    localStorage.clear();
    pushMock.mockReset();
    listRecentMock.mockReset();
    listRecentMock.mockResolvedValue({ count: 2, documents: [docA, docB] });
  });

  it("拉 30 条 / 30 天并渲染每篇的标题、格式与操作按钮", async () => {
    const w = mount(RecentHistoryView);
    await flushPromises();
    expect(listRecentMock).toHaveBeenCalledWith(30, 30);
    expect(w.text()).toContain("第一篇");
    expect(w.text()).toContain("第二篇");
    expect(w.text()).toContain("DOCX");
    expect(w.text()).toContain("近 30 天 · 2 篇");
    const openBtns = w.findAll("button").filter((b) => b.text().includes("打开位置"));
    expect(openBtns.length).toBe(2);
    // 创作区已下线：不再有「重新生成」/「参数已变更」入口
    expect(w.text()).not.toContain("重新生成");
    expect(w.text()).not.toContain("参数已变更");
  });

  it("「返回工作台」→ router.push home", async () => {
    const w = mount(RecentHistoryView);
    await flushPromises();
    await w.findAll("button").find((b) => b.text().includes("返回工作台"))!.trigger("click");
    expect(pushMock).toHaveBeenCalledWith({ name: "home" });
  });

  it("「清除记录」→ 全部隐藏并写入 localStorage，不动数据源", async () => {
    const w = mount(RecentHistoryView);
    await flushPromises();
    await w.findAll("button").find((b) => b.text().includes("清除记录"))!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("记录已清空");
    expect(w.text()).toContain("已隐藏 2 条");
    const hidden = JSON.parse(localStorage.getItem("csm.recent.hidden.v1") ?? "[]");
    expect(hidden.sort()).toEqual(["/h/a.md", "/h/b.docx"]);
  });
});
