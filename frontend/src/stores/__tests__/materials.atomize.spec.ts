import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import { useMaterials } from "@/stores/materials";

describe("materials store — AI 拆条", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
  });

  it("atomizeText 打 /atomize 返回 atoms", async () => {
    postMock.mockResolvedValueOnce({ data: { atoms: [
      { text: "看吸力", rel_folder: "a", material_type: "科普选购", product: "通用",
        keyword: "吸力", filename: "x.md", confidence: "high", warnings: [] }] } });
    const m = useMaterials();
    const atoms = await m.atomizeText("资料");
    expect(atoms.length).toBe(1);
    expect(atoms[0].confidence).toBe("high");
    expect(postMock).toHaveBeenCalledWith("/api/vault/atomize", { text: "资料" });
  });

  it("atomizeText 失败 → [] + intakeError", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "未配置 provider" } } });
    const m = useMaterials();
    expect(await m.atomizeText("资料")).toEqual([]);
    expect(m.intakeError).toContain("provider");
  });

  it("commitAtom 返回 receipt", async () => {
    postMock.mockResolvedValueOnce({ data: { created_rel: "a/x.md", content_sha: "s" } });
    const m = useMaterials();
    const rc = await m.commitAtom({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(rc?.created_rel).toBe("a/x.md");
  });

  it("commitAtom 失败 → null + intakeError", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "同名笔记已存在" } } });
    const m = useMaterials();
    expect(await m.commitAtom({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] })).toBeNull();
    expect(m.intakeError).toContain("同名");
  });

  it("commitAtom 成功清掉残留 intakeError", async () => {
    postMock.mockResolvedValueOnce({ data: { created_rel: "a/x.md", content_sha: "s" } });
    const m = useMaterials();
    m.intakeError = "旧错误";
    await m.commitAtom({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(m.intakeError).toBeNull();
  });

  it("undoAtom 打 /undo", async () => {
    postMock.mockResolvedValueOnce({ data: { undone: true, warnings: [] } });
    const m = useMaterials();
    await m.undoAtom({ created_rel: "a/x.md", content_sha: "s", index_rel: null, index_line: null });
    expect(postMock).toHaveBeenCalledWith("/api/vault/undo", expect.objectContaining({ created_rel: "a/x.md" }));
  });
});
