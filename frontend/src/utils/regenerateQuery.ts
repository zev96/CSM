/**
 * §7.3 一键重新生成 —— 用成稿记录参数重建创作流 router query。
 *
 * query key **必须对齐** ArticleView 的 route.query 读取（常规 keyword/template_id/
 * skill_chain/audience/sellpoints/tone/title/contract；横评 mode/models/... ），
 * 否则预填失效。抽成纯函数便于单测钉死这份契约。
 */
import type { CreationRecordRef } from "@/api/client";

export function parseAngleJson(json: string | null | undefined): {
  audience?: string;
  sellpoints?: string[];
  tone?: string;
} | null {
  if (!json) return null;
  try {
    const a = JSON.parse(json);
    if (!a || typeof a !== "object" || Array.isArray(a)) return null;
    return {
      audience: typeof a.audience === "string" ? a.audience : undefined,
      sellpoints: Array.isArray(a.sellpoints) ? a.sellpoints.map(String) : undefined,
      tone: typeof a.tone === "string" ? a.tone : undefined,
    };
  } catch {
    return null;
  }
}

export function parseJsonArray(json: string | null | undefined): string[] {
  if (!json) return [];
  try {
    const c = JSON.parse(json);
    return Array.isArray(c) ? c.map(String) : [];
  } catch {
    return [];
  }
}

export type RegenerateResult =
  | { ok: true; query: Record<string, string> }
  | { ok: false; error: string };

export function buildRegenerateQuery(rec: CreationRecordRef): RegenerateResult {
  const q: Record<string, string> = { keyword: rec.keyword ?? "" };
  if (rec.title) q.title = rec.title;
  const chain = parseJsonArray(rec.skill_chain_json);
  if (chain.length) q.skill_chain = chain.join(",");
  if (rec.contract_mode) q.contract = rec.contract_mode;

  if (rec.mode === "comparison") {
    const models = parseJsonArray(rec.models_json);
    if (models.length < 2) return { ok: false, error: "横评记录型号不足，无法重新生成" };
    q.mode = "comparison";
    q.models = models.join(",");
    const tone = parseAngleJson(rec.angle_json)?.tone;
    if (tone) q.tone = tone;
  } else {
    if (rec.template_id) q.template_id = rec.template_id;
    const a = parseAngleJson(rec.angle_json);
    if (a?.audience) q.audience = a.audience;
    if (a?.sellpoints?.length) q.sellpoints = a.sellpoints.join(",");
    if (a?.tone) q.tone = a.tone;
  }
  return { ok: true, query: q };
}
