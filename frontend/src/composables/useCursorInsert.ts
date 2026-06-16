/**
 * textarea 光标插入内核 —— 设计稿 §4.2。所有「点素材插入」（emoji / 装饰
 * / 文案 / 主题符号，P1 起）都走 useCursorInsert().insert(text) 这一个入口。
 */
import { type Ref, nextTick } from "vue";

/**
 * 纯字符串变换：把 [start, end) 区间替换为 insert，返回新串与插入后光标位。
 * start/end 会被夹紧到 [0, value.length]；start>end 时取 max 退化为插入点。
 */
export function spliceAtSelection(
  value: string,
  start: number,
  end: number,
  insert: string,
): { value: string; caret: number } {
  const len = value.length;
  const s = Math.max(0, Math.min(start, len));
  const e = Math.max(s, Math.min(end, len));
  const next = value.slice(0, s) + insert + value.slice(e);
  return { value: next, caret: s + insert.length };
}

/**
 * 把 textarea ref 接上光标插入。
 *
 * @param textareaRef 目标 textarea 的模板 ref
 * @param onUpdate    收到新串后回调（调用方据此更新 v-model / store）
 *
 * insert(text)：取当前选区 → spliceAtSelection → onUpdate(newValue) →
 * nextTick 后把光标移到插入串末尾并重新 focus（等 Vue 把新值 patch 进 DOM）。
 */
export function useCursorInsert(
  textareaRef: Ref<HTMLTextAreaElement | null>,
  onUpdate: (value: string) => void,
) {
  function insert(text: string): void {
    const el = textareaRef.value;
    const current = el ? el.value : "";
    const start = el ? el.selectionStart ?? current.length : current.length;
    const end = el ? el.selectionEnd ?? current.length : current.length;
    const { value, caret } = spliceAtSelection(current, start, end, text);
    onUpdate(value);
    void nextTick(() => {
      const after = textareaRef.value;
      if (!after) return;
      after.focus();
      after.setSelectionRange(caret, caret);
    });
  }
  return { insert };
}
