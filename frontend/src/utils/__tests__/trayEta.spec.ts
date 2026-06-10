import { describe, it, expect } from "vitest";

import { EtaEstimator } from "@/utils/trayEta";

describe("EtaEstimator", () => {
  it("首个样本与进度 <5% 时不出 ETA", () => {
    const e = new EtaEstimator();
    expect(e.observe("k", 0.02, 0)).toBeNull();
    expect(e.observe("k", 0.04, 60_000)).toBeNull(); // 有速率但 p < 0.05
  });

  it("稳定速率 → 约 X 分钟", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.1, 0);
    // 60s 走了 10% → 剩 80% ≈ 8 分钟
    expect(e.observe("k", 0.2, 60_000)).toBe("约 8 分钟");
  });

  it("剩余 <60s → 不到 1 分钟", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.5, 0);
    expect(e.observe("k", 0.98, 60_000)).toBe("不到 1 分钟");
  });

  it("进度回退（同 key 复用于新一轮任务）→ 重置不出脏 ETA", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.5, 0);
    e.observe("k", 0.9, 10_000);
    expect(e.observe("k", 0.1, 20_000)).toBeNull();
  });

  it("EMA 平滑：速率突变不会让 ETA 跳变到瞬时值", () => {
    const e = new EtaEstimator();
    e.observe("k", 0.1, 0);
    e.observe("k", 0.2, 60_000);          // rate=0.1/min
    const text = e.observe("k", 0.21, 120_000); // 瞬时掉到 0.01/min
    // 常规 EMA（α=0.3 权重在新样本）：0.3*0.01+0.7*0.1=0.073/min
    // → 剩 0.79/0.073≈10.8min。平滑语义：旧速率占大头，ETA 不随瞬时抖动跳变。
    expect(text).toBe("约 11 分钟");
  });
});
