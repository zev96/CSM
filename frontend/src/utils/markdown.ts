/**
 * 极简 markdown → HTML。只认标题、加粗、段落 —— 全站成稿正文就这三样。
 *
 * 从 TiptapEditor 抽出来共用：润色 pass 的输出预览原来是 `white-space:
 * pre-wrap` 的纯文本，于是同一段正文在编辑器里是排好版的、在 pass 预览里
 * 是满屏 `##` 和 `**` 的 md 源码，看起来就像「润色把排版弄没了」。
 *
 * 安全性：文本先 escapeHtml 再拼标签，产出的标签只有 p/br/h1-6/strong，
 * 且内容不进任何属性 —— 可以直接 v-html。改这里时**先转义后拼**的顺序不
 * 能反。
 */
/**
 * 保证正文以 `# 标题` 开头 —— 已经有 H1 就原样返回。
 *
 * 必须与后端 `csm_core.export.markdown.ensure_title` **同口径**，否则同一
 * 段正文在编辑器里和导出文件里标题数量不一样。旧的 `withTitle` 用
 * `body.startsWith("# ")`（不跳前导空行），后端跳；而 txt 导出根本没判、
 * 直接 `${title}\n\n${body}` 拼 —— 成稿编辑器会把 `# 标题` 连同正文一起
 * 写回 finalText（编辑过一次就会），于是 txt 导出出来是两个标题。
 *
 * 标题里的换行会被压成空格：H1 是单行的，多行标题拼进去就断成了标题 + 正文。
 */
export function ensureTitle(body: string, title: string): string {
  const t = (title ?? "").replace(/\s+/g, " ").trim();
  if (!t) return body;
  for (const raw of (body ?? "").split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    // 只认真正的 H1（`#` 后面是空白）。`## 一、品牌分析` 是章节标题。
    return /^#\s/.test(line) && !/^##/.test(line) ? body : `# ${t}\n\n${body}`;
  }
  return `# ${t}\n\n${body}`;
}

/** 正文首行的 H1 文字；没有返回 ""。用于「换标题」时就地改写已内嵌的标题。 */
export function leadingTitle(body: string): string {
  for (const raw of (body ?? "").split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const m = /^#\s+(.*)$/.exec(line);
    return m && !line.startsWith("##") ? m[1].trim() : "";
  }
  return "";
}

/** 把正文里已内嵌的 H1 换成新标题；没有内嵌标题则原样返回。 */
export function replaceLeadingTitle(body: string, title: string): string {
  const t = (title ?? "").replace(/\s+/g, " ").trim();
  if (!t || !leadingTitle(body)) return body;
  const lines = (body ?? "").split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    if (!lines[i].trim()) continue;
    lines[i] = `# ${t}`;
    break;
  }
  return lines.join("\n");
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function mdToHtml(md: string): string {
  if (!md) return "";
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let para: string[] = [];
  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${para.join("<br/>")}</p>`);
      para = [];
    }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line === "") {
      flushPara();
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      flushPara();
      const level = h[1].length;
      out.push(`<h${level}>${escapeHtml(h[2])}</h${level}>`);
      continue;
    }
    para.push(escapeHtml(line).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>"));
  }
  flushPara();
  return out.join("\n");
}
