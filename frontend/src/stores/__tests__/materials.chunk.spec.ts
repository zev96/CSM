import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn();
const get = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post, get } }),
}));

import { useMaterials, type AtomDraft } from "@/stores/materials";

const atom = (text: string, folder = "营销资料库/科普"): AtomDraft => ({
  text, rel_folder: folder, material_type: "科普", product: "希喂",
  keyword: "k", filename: "f.md", confidence: "high", warnings: [],
});

describe("materials 分块拆条", () => {
  beforeEach(() => { setActivePinia(createPinia()); post.mockReset(); });

  it("短文走原路径（不调 split）", async () => {
    post.mockResolvedValueOnce({ data: { atoms: [atom("a")] } });
    const m = useMaterials();
    const out = await m.atomizeText("短文");
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][0]).toBe("/api/vault/atomize");
    expect(out).toHaveLength(1);
  });

  it("长文：split → 逐块 atomize → 合并", async () => {
    const long = "字".repeat(9000);
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2"], truncated: false, dropped_chars: 0 } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("a1")] } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("a2")] } });
    const m = useMaterials();
    const out = await m.atomizeText(long);
    expect(post.mock.calls.map((c) => c[0])).toEqual([
      "/api/vault/atomize/split", "/api/vault/atomize", "/api/vault/atomize",
    ]);
    expect(out.map((a) => a.text)).toEqual(["a1", "a2"]);
    expect(m.chunkProgress).toBeNull();          // 收尾清空
  });

  it("跨块重复原子去重", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2"], truncated: false, dropped_chars: 0 } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("同一条要点。")] } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("同一条 要点。")] } });   // 空白差异
    const m = useMaterials();
    const out = await m.atomizeText("字".repeat(9000));
    expect(out).toHaveLength(1);
  });

  it("truncated 透出", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1"], truncated: true, dropped_chars: 123 } });
    post.mockResolvedValueOnce({ data: { atoms: [] } });
    const m = useMaterials();
    await m.atomizeText("字".repeat(9000));
    expect(m.lastAtomizeTruncated).toEqual({ dropped: 123 });
  });

  it("取消中断后续块", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2", "c3"], truncated: false, dropped_chars: 0 } });
    const m = useMaterials();
    post.mockImplementationOnce(async () => {
      m.cancelAtomize();                          // 第 1 块进行中点取消
      return { data: { atoms: [atom("a1")] } };
    });
    const out = await m.atomizeText("字".repeat(9000));
    expect(out.map((a) => a.text)).toEqual(["a1"]);
    expect(post).toHaveBeenCalledTimes(2);        // split + 1 块
  });

  it("某块失败：保留已拆 + 报错中断", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2"], truncated: false, dropped_chars: 0 } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("a1")] } });
    post.mockRejectedValueOnce(new Error("net"));
    const m = useMaterials();
    const out = await m.atomizeText("字".repeat(9000));
    expect(out.map((a) => a.text)).toEqual(["a1"]);
    expect(m.intakeError).toBeTruthy();
  });
});
