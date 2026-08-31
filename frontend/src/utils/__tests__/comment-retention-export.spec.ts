import { describe, it, expect } from "vitest";
import {
  buildRetentionCsv,
  summarizeRetention,
  type RetentionExportItem,
} from "../comment-retention-export";
import type { VideoEntry } from "../monitor-types";

function entry(over: Partial<VideoEntry>): VideoEntry {
  return {
    id: "task-1",
    url: "https://www.bilibili.com/video/BV1xx",
    title: "BV1xx",
    myComment: "好用，推荐",
    rank: 0,
    status: "pending",
    scanDepth: 150,
    postedAt: "—",
    totalComments: 0,
    ...over,
  };
}

describe("summarizeRetention", () => {
  it("留存=在显+跌出理想；率取一位小数", () => {
    const s = summarizeRetention([
      entry({ status: "ok", rank: 3 }),
      entry({ status: "folded", rank: 12 }),
      entry({ status: "deleted" }),
    ]);
    expect(s.total).toBe(3);
    expect(s.retained).toBe(2);
    expect(s.ratePercent).toBe(66.7);
    expect(s.byStatus.deleted).toBe(1);
  });
  it("空批次不除零", () => {
    const s = summarizeRetention([]);
    expect(s.total).toBe(0);
    expect(s.ratePercent).toBe(0);
  });
});

describe("buildRetentionCsv", () => {
  const now = new Date(2026, 7, 31, 9, 5); // 2026-08-31 09:05 本地时间
  const items: RetentionExportItem[] = [
    {
      video: entry({ status: "ok", rank: 3, totalComments: 888 }),
      checkedAt: "2026-08-30T10:00:00",
    },
    {
      video: entry({
        id: "task-2",
        status: "beyond",
        totalComments: 120,
        myComment: 'a,"b"', // 半角逗号+引号 → 必须走 RFC4180 逃逸
      }),
      checkedAt: null,
    },
  ];
  const csv = buildRetentionCsv({
    batchName: "品牌A - 8月投放",
    platformLabel: "B站",
    items,
    now,
  });
  const lines = csv.split("\r\n");

  it("头部汇总块：总计/留存/留存率", () => {
    expect(lines[0]).toBe("任务批次,品牌A - 8月投放");
    expect(lines[1]).toBe("平台,B站");
    expect(lines[2]).toBe("导出时间,2026-08-31 09:05");
    expect(lines[3]).toBe("总计,2 条");
    expect(lines[4]).toBe("留存,1 条");
    expect(lines[5]).toBe("留存率,50%");
    expect(lines[6]).toContain("在显 1");
    expect(lines[6]).toContain("超出检索 1");
  });

  it("汇总与明细之间隔空行，随后是表头", () => {
    expect(lines[7]).toBe("");
    expect(lines[8].startsWith("序号,名称,视频链接,我的评论,是否留存,排名,状态")).toBe(true);
  });

  it("命中行：留存=是、排名为纯数字、在显", () => {
    const cols = lines[9].split(",");
    expect(cols[0]).toBe("1");
    expect(cols[4]).toBe("是");
    expect(cols[5]).toBe("3");
    expect(cols[6]).toBe("在显");
    expect(cols[9]).toBe("2026-08-30 10:00");
  });

  it("未命中行：留存=否、排名=N+、状态=超N名外、无检查时间显—", () => {
    expect(lines[10]).toContain('"a,""b"""'); // 逗号+引号字段被正确逃逸
    expect(lines[10]).toContain(",否,150+,超150名外,");
    expect(lines[10]).toContain(",—,"); // checkedAt=null → —
  });

  it("以 CRLF 结尾（Windows Excel 直开）", () => {
    expect(csv.endsWith("\r\n")).toBe(true);
  });
});
