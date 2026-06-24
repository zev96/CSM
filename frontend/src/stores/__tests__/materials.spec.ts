import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock } }),
}));

import { useMaterials } from "@/stores/materials";

describe("materials store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset();
  });

  it("list() 填充 models", async () => {
    getMock.mockResolvedValueOnce({ data: { count: 1, models: [
      { model: "CEWEYDS18", brand: "CEWEY", role: "主推", coverage: { has_specs: true } },
    ] } });
    const s = useMaterials();
    await s.list();
    expect(s.models).toHaveLength(1);
    expect(s.models[0].model).toBe("CEWEYDS18");
    expect(s.loading).toBe(false);
  });

  it("select() 拉详情 + 设 selectedModel", async () => {
    getMock.mockResolvedValueOnce({ data: { model_full: "CEWEYDS18", specs: {}, inject_preview: "x" } });
    const s = useMaterials();
    await s.select("CEWEYDS18");
    expect(s.selectedModel).toBe("CEWEYDS18");
    expect(s.detail?.model_full).toBe("CEWEYDS18");
  });

  it("list() 失败设 error 不抛", async () => {
    getMock.mockRejectedValueOnce({ response: { data: { detail: "boom" } } });
    const s = useMaterials();
    await s.list();
    expect(s.error).toBe("boom");
    expect(s.models).toEqual([]);
  });
});
