import { describe, it, expect } from "vitest";
import { orderedMarker, countOrderedMarkers } from "@/utils/xhsTheme";

describe("orderedMarker", () => {
  it("emoji 样式：1→1️⃣、10→🔟、超表→`${n}.`", () => {
    expect(orderedMarker(1, "emoji")).toBe("1️⃣");
    expect(orderedMarker(10, "emoji")).toBe("🔟");
    expect(orderedMarker(11, "emoji")).toBe("11.");
  });
  it("circle 样式：1→①、20→⑳、超表→`${n}.`", () => {
    expect(orderedMarker(1, "circle")).toBe("①");
    expect(orderedMarker(20, "circle")).toBe("⑳");
    expect(orderedMarker(21, "circle")).toBe("21.");
  });
  it("superscript 样式：1→¹、9→⁹、超表→`${n}.`", () => {
    expect(orderedMarker(1, "superscript")).toBe("¹");
    expect(orderedMarker(9, "superscript")).toBe("⁹");
    expect(orderedMarker(10, "superscript")).toBe("10.");
  });
  it("n<1 返回空串（防御）", () => {
    expect(orderedMarker(0, "emoji")).toBe("");
  });
});

describe("countOrderedMarkers", () => {
  it("数出正文已有的同样式序号个数", () => {
    expect(countOrderedMarkers("1️⃣ 第一\n2️⃣ 第二", "emoji")).toBe(2);
    expect(countOrderedMarkers("① a ② b ③ c", "circle")).toBe(3);
    expect(countOrderedMarkers("¹ x", "superscript")).toBe(1);
  });
  it("无该样式序号时为 0", () => {
    expect(countOrderedMarkers("纯文本没有序号", "emoji")).toBe(0);
    expect(countOrderedMarkers("", "circle")).toBe(0);
  });
});
