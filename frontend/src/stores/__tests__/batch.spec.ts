import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/api/client", () => ({ subscribe: vi.fn(() => () => {}) }));

import { useBatch } from "@/stores/batch";
import { useNotifications } from "@/composables/useNotifications";

describe("batch — 快照对账完成路径", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    const n = useNotifications();
    n.clear();
    n.setEnabled(true);
    getMock.mockReset();
    postMock.mockReset();
  });

  it("refreshSnapshot 发现 finished_at 且原为 running → 置 done + 补完成通知", async () => {
    const batch = useBatch();
    batch.$patch({ status: "running", jobId: "u1", total: 2 });
    getMock.mockResolvedValue({
      data: {
        items: [
          { index: 1, keyword: "a", status: "success", duration_seconds: 1, document: null, error_type: null, error_message: null },
          { index: 2, keyword: "b", status: "failed", duration_seconds: 1, document: null, error_type: "X", error_message: "boom" },
        ],
        finished_at: "2026-06-10T10:00:00",
        out_dir: "D:/out",
      },
    });
    await batch.refreshSnapshot();
    expect(batch.status).toBe("done");
    const n = useNotifications();
    expect(n.items.value[0]?.title).toBe("批量生成完成");
    expect(n.items.value[0]?.tone).toBe("warn"); // 有失败 → warn
    expect(n.items.value[0]?.body).toContain("失败 1");
  });

  it("快照含 cancelled 项 → 静默不推", async () => {
    const batch = useBatch();
    batch.$patch({ status: "running", jobId: "u1", total: 2 });
    getMock.mockResolvedValue({
      data: {
        items: [
          { index: 1, keyword: "a", status: "success", duration_seconds: 1, document: null, error_type: null, error_message: null },
          { index: 2, keyword: "b", status: "cancelled", duration_seconds: 0, document: null, error_type: null, error_message: null },
        ],
        finished_at: "2026-06-10T10:00:00",
      },
    });
    await batch.refreshSnapshot();
    expect(batch.status).toBe("done");
    expect(useNotifications().items.value.length).toBe(0);
  });
});
