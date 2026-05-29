import { describe, it, expect } from "vitest";
import { formatVisitCount } from "../monitor-batch";

describe("formatVisitCount", () => {
  it("< 1万 显原数", () => expect(formatVisitCount(856)).toBe("856"));
  it("1万~1亿 显 X.X万", () => {
    expect(formatVisitCount(12000)).toBe("1.2万");
    expect(formatVisitCount(3_500_000)).toBe("350万");
  });
  it("≥ 1亿 显 X.X亿", () => expect(formatVisitCount(123_000_000)).toBe("1.2亿"));
  it("空值显 —", () => {
    expect(formatVisitCount(null)).toBe("—");
    expect(formatVisitCount(undefined)).toBe("—");
  });
});
