import { mount } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import BlockEditor from "../BlockEditor.vue";

/** 空 vault —— 素材还没写的真实场景（先配模板后写素材是正常顺序）。 */
function emptyVault() {
  getMock.mockResolvedValue({ data: { attributes: [] } });
}

function cardPool(overrides: Record<string, any> = {}) {
  return {
    kind: "competitor_pool",
    id: "pool_1",
    source: { type: "notes_query", module: "竞品推荐内容", filter: {} },
    pick_notes: 3,
    sections: [{ label: "市场口碑数据", h2: "", required: true, pick_variants: 1 }],
    heading_template: "### {tier} TOP{n}. {title}",
    ...overrides,
  };
}

function mountEditor(block: Record<string, any>) {
  return mount(BlockEditor, {
    props: { modelValue: block, index: 0, total: 1, vaultDirs: [] },
    global: { stubs: { CascadePicker: true } },
  });
}

describe("BlockEditor — 卡片竞品池的筛选条件", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    emptyVault();
  });

  it("卡片模式缺筛选时就地提示，不用等保存才报错", () => {
    const w = mountEditor(cardPool());
    expect(w.text()).toContain("卡片模式需要筛选条件");
  });

  it("「填入约定值」一键补上 素材类型=竞品卡", async () => {
    // schema 强制卡片模式必须有筛选，而筛选属性下拉是从 vault 已有笔记
    // 聚合的：卡还没写时下拉是空的，没有这条出路就是死锁。
    const w = mountEditor(cardPool());
    const btn = w.findAll("button").find((b) => b.text().includes("填入约定值"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");

    const emitted = w.emitted("update:modelValue");
    expect(emitted).toBeTruthy();
    const last = emitted!.at(-1)![0] as any;
    expect(last.source.filter).toEqual({ 素材类型: "竞品卡" });
    expect(last.source.module).toBe("竞品推荐内容");   // 目录不能被冲掉
  });

  it("已经有筛选条件就不再提示", () => {
    const w = mountEditor(
      cardPool({
        source: {
          type: "notes_query",
          module: "竞品推荐内容",
          filter: { 素材类型: "竞品卡" },
        },
      }),
    );
    expect(w.text()).not.toContain("卡片模式需要筛选条件");
  });

  it("非卡片模式（旧竞品池）不提示 —— 它不要求筛选", () => {
    const w = mountEditor(cardPool({ sections: [] }));
    expect(w.text()).not.toContain("卡片模式需要筛选条件");
  });

  it("空 vault 下属性下拉仍给出「自定义属性…」出口", async () => {
    const w = mountEditor(cardPool());
    await new Promise((r) => setTimeout(r, 0));
    expect(w.html()).toContain("自定义属性");
  });
});
