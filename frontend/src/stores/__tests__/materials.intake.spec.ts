import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import { useMaterials } from "@/stores/materials";

describe("materials store — 录入", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
  });

  it("loadFolders 填充 writableFolders", async () => {
    getMock.mockResolvedValueOnce({ data: { folders: [
      { rel_folder: "科普模块/吸尘器/挑选攻略", frontmatter_keys: ["产品"], defaults: {},
        body_shape: "variants", sample_count: 2, material_types: ["科普选购"] },
    ] } });
    const m = useMaterials();
    await m.loadFolders();
    expect(m.writableFolders.length).toBe(1);
    expect(m.writableFolders[0].body_shape).toBe("variants");
  });

  it("planNote 存 currentPlan", async () => {
    postMock.mockResolvedValueOnce({ data: { full_text: "FT", conflict: false, warnings: [] } });
    const m = useMaterials();
    await m.planNote({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(m.currentPlan?.full_text).toBe("FT");
    expect(postMock).toHaveBeenCalledWith("/api/vault/plan", expect.objectContaining({ filename: "x.md" }));
  });

  it("commitNote 存 lastReceipt + 返回 true", async () => {
    postMock.mockResolvedValueOnce({ data: { created_rel: "a/x.md", content_sha: "sha" } });
    const m = useMaterials();
    const ok = await m.commitNote({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(ok).toBe(true);
    expect(m.lastReceipt?.created_rel).toBe("a/x.md");
  });

  it("commitNote 409 冲突 → 返回 false + 设 intakeError", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "同名笔记已存在" } } });
    const m = useMaterials();
    const ok = await m.commitNote({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(ok).toBe(false);
    expect(m.intakeError).toContain("同名");
  });

  it("undoLast 调 /undo 并清 lastReceipt", async () => {
    postMock.mockResolvedValueOnce({ data: { undone: true, warnings: [] } });
    const m = useMaterials();
    m.lastReceipt = { created_rel: "a/x.md", content_sha: "sha", index_rel: null, index_line: null };
    await m.undoLast();
    expect(postMock).toHaveBeenCalledWith("/api/vault/undo", expect.objectContaining({ created_rel: "a/x.md" }));
    expect(m.lastReceipt).toBeNull();
  });
});
