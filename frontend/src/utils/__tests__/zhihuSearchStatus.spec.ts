import { describe, it, expect } from "vitest";
import { zhihuSearchTaskStatus } from "../zhihuSearchStatus";

describe("zhihuSearchTaskStatus", () => {
  it("无历史 → 未跑", () => {
    expect(zhihuSearchTaskStatus(null)).toEqual({ label: "未跑", tone: "info" });
  });
  it("error → 鉴权失败", () => {
    expect(zhihuSearchTaskStatus({ status: "error", metric: {} })).toEqual({ label: "鉴权失败", tone: "alert" });
  });
  it("risk_control → 限频", () => {
    expect(zhihuSearchTaskStatus({ status: "risk_control", metric: {} })).toEqual({ label: "限频", tone: "warn" });
  });
  it("任一关键词 first_rank>0 → 正常", () => {
    expect(zhihuSearchTaskStatus({ status: "ok", metric: { keywords: [{ first_rank: -1 }, { first_rank: 3 }] } }))
      .toEqual({ label: "正常", tone: "ok" });
  });
  it("全部前 10 无命中 → 未命中", () => {
    expect(zhihuSearchTaskStatus({ status: "ok", metric: { keywords: [{ first_rank: -1 }, { first_rank: 0 }] } }))
      .toEqual({ label: "未命中", tone: "info" });
  });
  it("空 keywords → 未跑", () => {
    expect(zhihuSearchTaskStatus({ status: "ok", metric: { keywords: [] } })).toEqual({ label: "未跑", tone: "info" });
  });
});
