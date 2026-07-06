import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const factsChangesMock = vi.fn();
vi.mock("@/api/client", () => ({
  factsChanges: () => factsChangesMock(),
}));

import { useFactsChanges } from "@/stores/factsChanges";

function change(model: string) {
  return { model, changed: [], detected_at: "2026-07-05T00:00:00Z" };
}

describe("factsChanges store（§7.2 型号变更累积）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    factsChangesMock.mockReset();
  });

  it("ingest 累积 + staleModels 去重 + isStale/count", () => {
    const s = useFactsChanges();
    s.ingest([change("A"), change("B")]);
    s.ingest([change("A")]); // A 重复 → staleModels 不加
    expect(s.count).toBe(2);
    expect(s.isStale("A")).toBe(true);
    expect(s.isStale("C")).toBe(false);
    expect(s.changes.length).toBe(3); // changes 明细全存（含重复）
  });

  it("pull 命中 → ingest + 返回 changes", async () => {
    factsChangesMock.mockResolvedValueOnce({ changes: [change("X")] });
    const s = useFactsChanges();
    const out = await s.pull();
    expect(out.length).toBe(1);
    expect(s.isStale("X")).toBe(true);
  });

  it("pull 失败 → 静默返回 []（fail-safe，非关键数据）", async () => {
    factsChangesMock.mockRejectedValueOnce(new Error("network boom"));
    const s = useFactsChanges();
    expect(await s.pull()).toEqual([]);
    expect(s.count).toBe(0);
  });

  it("pull 空变更 → 不动 store", async () => {
    factsChangesMock.mockResolvedValueOnce({ changes: [] });
    const s = useFactsChanges();
    expect(await s.pull()).toEqual([]);
    expect(s.count).toBe(0);
  });
});
