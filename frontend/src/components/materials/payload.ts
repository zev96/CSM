// 素材库录入/拆条共用的 payload 组装（DRY：IntakeForm 与 AtomCard 同源）。
export function assembleFrontmatter(fm: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fm)) {
    if (k === "核心关键词") out[k] = String(v).split(/[，,\s]+/).filter(Boolean);
    else if (v) out[k] = v;
  }
  return out;
}

export function filenameError(name: string): string {
  const v = (name || "").trim();
  if (!v) return "";
  if (/\s/.test(v) || v.includes("/") || v.includes("\\")) return "不能含空格/路径分隔符";
  if (!v.endsWith(".md")) return "须以 .md 结尾";
  return "";
}
