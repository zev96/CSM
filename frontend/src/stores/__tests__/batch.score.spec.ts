import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));

// Capture the handlers registered by subscribe() so tests can drive
// item_finished / done manually (mirrors batch.spec.ts's "SSE 不真跑，
// 直接调 handler" 风格 — 该文件用快照对账路径；这里改走事件路径，
// 需要拿到 handler map)。
let lastHandlers: Record<string, (d: any) => void> = {};
vi.mock("@/api/client", () => ({
  subscribe: vi.fn((_url: string, handlers: Record<string, (d: any) => void>) => {
    lastHandlers = handlers;
    return () => {};
  }),
}));

import { useBatch } from "@/stores/batch";

describe("batch score/candidates/total_cost", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset();
    postMock.mockReset();
    lastHandlers = {};
  });

  it("submit 传 candidates（默认 1）", async () => {
    const batch = useBatch();
    postMock.mockResolvedValue({ data: { job_id: "j1", total: 1 } });
    getMock.mockResolvedValue({ data: { items: [] } });
    await batch.submit(["k"]);
    expect(postMock.mock.calls[0][1]).toMatchObject({ candidates: 1 });
  });

  it("submit 传 candidates=2（设置后 body 含 candidates:2）", async () => {
    const batch = useBatch();
    batch.candidates = 2;
    postMock.mockResolvedValue({ data: { job_id: "j1", total: 1 } });
    getMock.mockResolvedValue({ data: { items: [] } });
    await batch.submit(["k"]);
    expect(postMock.mock.calls[0][1]).toMatchObject({ candidates: 2 });
  });

  it("item_finished 带 score/score_parts/candidate_scores/factcheck_violations → BatchItem 落位", async () => {
    const batch = useBatch();
    postMock.mockResolvedValue({ data: { job_id: "j1", total: 1 } });
    getMock.mockResolvedValue({
      data: { items: [{ index: 1, keyword: "k", status: "queued", duration_seconds: 0, document: null, error_type: null, error_message: null }] },
    });
    await batch.submit(["k"]);
    lastHandlers.item_finished({
      index: 1, status: "success", duration_seconds: 1.2, document: "d.md",
      error_type: null, error_message: null,
      score: 72.5, score_parts: [{ key: "lint", label: "禁区命中", points: 12, detail: "3 处" }],
      candidate_scores: [72.5, 60.0], factcheck_violations: 1,
    });
    const it = batch.items.find((x) => x.index === 1);
    expect(it?.score).toBe(72.5);
    expect(it?.score_parts).toEqual([{ key: "lint", label: "禁区命中", points: 12, detail: "3 处" }]);
    expect(it?.candidate_scores).toEqual([72.5, 60.0]);
    expect(it?.factcheck_violations).toBe(1);
  });

  it("item_finished 无新键（旧事件）→ BatchItem 新字段 fallback null/[]/0", async () => {
    const batch = useBatch();
    postMock.mockResolvedValue({ data: { job_id: "j1", total: 1 } });
    getMock.mockResolvedValue({
      data: { items: [{ index: 1, keyword: "k", status: "queued", duration_seconds: 0, document: null, error_type: null, error_message: null }] },
    });
    await batch.submit(["k"]);
    lastHandlers.item_finished({
      index: 1, status: "success", duration_seconds: 1.2, document: "d.md",
      error_type: null, error_message: null,
    });
    const it = batch.items.find((x) => x.index === 1);
    expect(it?.score ?? null).toBeNull();
    expect(it?.score_parts ?? []).toEqual([]);
    expect(it?.candidate_scores ?? []).toEqual([]);
    expect(it?.factcheck_violations ?? 0).toBe(0);
  });

  it("done 带 total_cost → store.totalCost 落位", async () => {
    const batch = useBatch();
    postMock.mockResolvedValue({ data: { job_id: "j1", total: 1 } });
    getMock.mockResolvedValue({ data: { items: [] } });
    await batch.submit(["k"]);
    lastHandlers.done({
      by_status: { success: 1 }, total_duration_seconds: 3.0,
      total_cost: { input_tokens: 100, output_tokens: 200, cost: 0.5, currency: "CNY" },
    });
    expect(batch.totalCost).toEqual({ input_tokens: 100, output_tokens: 200, cost: 0.5, currency: "CNY" });
  });

  it("done 无 total_cost（旧事件）→ totalCost 保持 null", async () => {
    const batch = useBatch();
    postMock.mockResolvedValue({ data: { job_id: "j1", total: 1 } });
    getMock.mockResolvedValue({ data: { items: [] } });
    await batch.submit(["k"]);
    lastHandlers.done({ by_status: { success: 1 }, total_duration_seconds: 3.0 });
    expect(batch.totalCost).toBeNull();
  });

  it("submit reset 清空上一轮 totalCost", async () => {
    const batch = useBatch();
    batch.totalCost = { input_tokens: 1, output_tokens: 1, cost: 1, currency: "CNY" };
    postMock.mockResolvedValue({ data: { job_id: "j1", total: 1 } });
    getMock.mockResolvedValue({ data: { items: [] } });
    await batch.submit(["k"]);
    expect(batch.totalCost).toBeNull();
  });
});
