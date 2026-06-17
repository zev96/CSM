/**
 * 小红书官方贴纸「文字代码」切分（设计稿 §6）。
 *
 * 小红书贴纸代码形如 `[害羞R]`、`[偷笑R]`（中文标签 + 尾随 R，方括号包裹）。
 * 本工具把正文切成 文本段 / 代码段，供 PhonePreview 把代码段渲染成占位 chip
 * （小药丸，显示去掉 []R 的标签）—— **不渲染任何官方贴纸图片**（版权 / ToS）。
 * 编辑区仍是纯文本，所见即所得只在预览面板承担。
 */
export interface XhsTextSegment {
  type: "text" | "code";
  value: string; // 原始片段（code 段含方括号，如 "[害羞R]"）
  label: string; // code 段的展示标签（去掉 []R，如 "害羞"）；text 段为空串
}

// 匹配最短的非方括号内容 + 尾随 R + 闭方括号。捕获组 1 = 标签文字。
const CODE_RE = /\[([^[\]]+?)R\]/g;

export function tokenizeXhsCodes(text: string): XhsTextSegment[] {
  if (!text) return [];
  const out: XhsTextSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(CODE_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) {
      out.push({ type: "text", value: text.slice(last, idx), label: "" });
    }
    out.push({ type: "code", value: m[0], label: m[1] });
    last = idx + m[0].length;
  }
  if (last < text.length) {
    out.push({ type: "text", value: text.slice(last), label: "" });
  }
  return out;
}
