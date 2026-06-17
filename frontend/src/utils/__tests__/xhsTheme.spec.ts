import { describe, it, expect } from "vitest";
import { orderedMarker, countOrderedMarkers, nextOrderedNumber } from "@/utils/xhsTheme";

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

describe("nextOrderedNumber 按列表块计数", () => {
  it("空文本 → 1", () => {
    expect(nextOrderedNumber("", "circle")).toBe(1);
  });
  it("当前块已有 ①② → 3", () => {
    expect(nextOrderedNumber("① 第一\n② 第二\n", "circle")).toBe(3);
  });
  it("空行分隔后新块从 1 起", () => {
    expect(nextOrderedNumber("① 上一组\n\n", "circle")).toBe(1);
  });
  it("前文有块、空行后当前块已 1 个 → 2", () => {
    expect(nextOrderedNumber("引言\n\n① 当前块第一\n", "circle")).toBe(2);
  });
  it("emoji 样式同理", () => {
    expect(nextOrderedNumber("1️⃣ a\n2️⃣ b\n", "emoji")).toBe(3);
  });
  it("CRLF 空行也能分块", () => {
    expect(nextOrderedNumber("① 上一组\r\n\r\n", "circle")).toBe(1);
  });
});
