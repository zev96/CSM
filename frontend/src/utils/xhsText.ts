/**
 * 小红书纯文本工具 —— 编辑器内核的字数与「一键复制」组装逻辑。
 *
 * 纯函数、无 DOM 依赖，便于单测。所有「点素材插入」相关的光标逻辑在
 * composables/useCursorInsert.ts。
 */

/**
 * 按 Unicode 码点计数（emoji 计 1）。与小红书官方计数口径可能有个位数
 * 差异（ZWJ 组合 emoji 会被算成多个码点），作为软提示可接受。
 */
export function countChars(s: string): number {
  return [...s].length;
}

/**
 * 组装「复制全文」：标题 + 空行 + 正文 + 空行 + `#话题` 串。
 *
 * - 标题用 trim 后判空（首尾空白不该单独成段）；
 * - 正文**不 trim**（保留 emoji 排版的首尾换行/缩进），仅用 trim 判空；
 * - 话题逐个 trim、去掉用户误带的前导 `#`、丢弃空项，再以空格连接。
 */
export function buildFullText(title: string, body: string, topics: string[]): string {
  const parts: string[] = [];
  if (title.trim()) parts.push(title.trim());
  if (body.trim()) parts.push(body);
  const tags = topics
    .map((t) => t.replace(/^#+/, "").trim())
    .filter((t) => t.length > 0)
    .map((t) => `#${t}`);
  if (tags.length) parts.push(tags.join(" "));
  return parts.join("\n\n");
}
