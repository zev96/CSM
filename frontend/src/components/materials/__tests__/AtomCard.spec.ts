import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import AtomCard from "@/components/materials/AtomCard.vue";
import type { FolderProfile } from "@/stores/materials";

const FOLDERS: FolderProfile[] = [
  { rel_folder: "科普模块/吸尘器/挑选攻略", frontmatter_keys: ["产品", "素材类型", "核心关键词"],
    defaults: { 产品: "吸尘器" }, body_shape: "variants", sample_count: 2, material_types: ["科普选购"],
    template_from: null },
];

function atom(over: any = {}) {
  return { text: "看吸力", rel_folder: "科普模块/吸尘器/挑选攻略", material_type: "科普选购",
    product: "吸尘器", keyword: "吸力", filename: "吸力.md", confidence: "high", warnings: [], ...over };
}

describe("AtomCard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
  });

  it("off-menu 原子显示 warning", () => {
    const w = mount(AtomCard, { props: { atom: atom({ rel_folder: null, warnings: ["建议文件夹「x」不在素材库中，请人工选择"] }), folders: FOLDERS } });
    expect(w.text()).toContain("不在素材库");
  });

  it("确认入库走 commitAtom，成功后出撤销", async () => {
    postMock.mockResolvedValue({ data: { created_rel: "科普模块/吸尘器/挑选攻略/吸力.md", content_sha: "s", index_rel: null, index_line: null } });
    const w = mount(AtomCard, { props: { atom: atom(), folders: FOLDERS } });
    await w.vm.$nextTick();
    await w.find("[data-atom-commit]").trigger("click");
    await new Promise((r) => setTimeout(r));
    expect(postMock).toHaveBeenCalledWith("/api/vault/commit", expect.objectContaining({
      rel_folder: "科普模块/吸尘器/挑选攻略", body_shape: "variants" }));
    expect(w.find("[data-atom-undo]").exists()).toBe(true);
  });

  it("commitAuto 跳过 low 置信度", async () => {
    const w = mount(AtomCard, { props: { atom: atom({ confidence: "low" }), folders: FOLDERS } });
    await w.vm.$nextTick();
    await (w.vm as any).commitAuto();
    expect(postMock).not.toHaveBeenCalled();
  });
});
