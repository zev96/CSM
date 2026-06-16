import { describe, it, expect, vi } from "vitest";
import { ref, nextTick } from "vue";
import { spliceAtSelection, useCursorInsert } from "@/composables/useCursorInsert";

describe("spliceAtSelection（纯）", () => {
  it("在中间插入", () => {
    expect(spliceAtSelection("abcd", 2, 2, "XY")).toEqual({ value: "abXYcd", caret: 4 });
  });
  it("末尾追加（无选区）", () => {
    expect(spliceAtSelection("abc", 3, 3, "!")).toEqual({ value: "abc!", caret: 4 });
  });
  it("替换选区", () => {
    expect(spliceAtSelection("abcd", 1, 3, "X")).toEqual({ value: "aXd", caret: 2 });
  });
  it("越界 start/end 被夹紧", () => {
    expect(spliceAtSelection("ab", 99, 99, "Z")).toEqual({ value: "abZ", caret: 3 });
    expect(spliceAtSelection("ab", -5, -5, "Z")).toEqual({ value: "Zab", caret: 1 });
  });
  it("start>end 时按 max(start) 退化为插入点", () => {
    expect(spliceAtSelection("abcd", 3, 1, "X")).toEqual({ value: "abcXd", caret: 4 });
  });
});

describe("useCursorInsert（接 textarea）", () => {
  it("在光标处插入并通过回调更新模型，nextTick 复位光标", async () => {
    const el = document.createElement("textarea");
    el.value = "abcd";
    document.body.appendChild(el);
    el.focus();
    el.setSelectionRange(2, 2);

    const taRef = ref<HTMLTextAreaElement | null>(el);
    const onUpdate = vi.fn((v: string) => {
      el.value = v; // 模拟模型回写到 DOM（真实里由 Vue :value 绑定完成）
    });
    const { insert } = useCursorInsert(taRef, onUpdate);

    insert("XY");
    expect(onUpdate).toHaveBeenCalledWith("abXYcd");
    await nextTick();
    expect(el.selectionStart).toBe(4);
    expect(el.selectionEnd).toBe(4);

    el.remove();
  });

  it("textarea ref 为空时回退到末尾追加", () => {
    const taRef = ref<HTMLTextAreaElement | null>(null);
    let captured = "";
    const { insert } = useCursorInsert(taRef, (v) => { captured = v; });
    // ref 为空 → current="" → 末尾插入
    insert("hi");
    expect(captured).toBe("hi");
  });
});
