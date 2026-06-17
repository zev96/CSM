/**
 * 排版主题「有序列表」符号工具（设计稿 §3.3 ordered / §5 主题）。
 *
 * P1 把 themes.json 的 `ordered` 留给 P3：工具条「有序」按钮要按主题样式
 * 插入「下一个序号」。orderedMarker 把第 n 个序号（n 从 1 起）渲染成该样式
 * 的字形；countOrderedMarkers 数出正文里已有的同样式序号个数，二者配合算出
 * 下一个序号。soft helper：跨多个列表会连续计数，作为辅助插入可接受。
 */
import type { XhsTheme } from "@/data/xhs/assets";

export type OrderedStyle = XhsTheme["ordered"]; // "emoji" | "circle" | "superscript"

// 各样式 1..N 的字形表（数组下标 0 = 序号 1）。超出表长用 `${n}.` 兜底。
const ORDERED_GLYPHS: Record<OrderedStyle, string[]> = {
  emoji: ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"],
  circle: ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
           "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"],
  superscript: ["¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"],
};

/** 第 n 个序号（n 从 1 起）渲染成 style 样式字形；n<1 返回空串、超表返回 `${n}.`。 */
export function orderedMarker(n: number, style: OrderedStyle): string {
  if (n < 1) return "";
  const glyphs = ORDERED_GLYPHS[style] ?? [];
  return glyphs[n - 1] ?? `${n}.`;
}

/** 数出 body 中 style 样式已出现的序号字形总数（用于推算下一个序号）。 */
export function countOrderedMarkers(body: string, style: OrderedStyle): number {
  const glyphs = ORDERED_GLYPHS[style] ?? [];
  let count = 0;
  for (const g of glyphs) {
    count += body.split(g).length - 1;
  }
  return count;
}

/**
 * 光标处「下一个有序序号」——只数当前列表块（最后一个空行之后的文本）里的同样式序号。
 * 这样跨多个列表块会各自从 1 重新计数（P4 打磨，取代 P3 的全文连续计数）。
 */
export function nextOrderedNumber(textBeforeCursor: string, style: OrderedStyle): number {
  // 空行（仅空白的整行）分隔列表块；取光标前最后一块。
  const blocks = textBeforeCursor.split(/\n[ \t]*\n/);
  const currentBlock = blocks[blocks.length - 1] ?? "";
  return countOrderedMarkers(currentBlock, style) + 1;
}
