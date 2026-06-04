export type ZhihuSearchTone = "ok" | "warn" | "alert" | "info";
export interface ZhihuSearchStatus {
  label: string;
  tone: ZhihuSearchTone;
}

/**
 * L1「状态」列 —— 基于该任务最新一份 result（taskHistories[id][0]）。
 * latest 形如 { status, metric }；null/undefined = 无历史。
 *
 * 规则（对齐 spec / csm_core zhihu_search metric）：
 *   无历史            → 未跑 (info)
 *   status=error      → 鉴权失败 (alert)
 *   status=risk_control → 限频 (warn)
 *   任一关键词 first_rank>0 → 正常 (ok)
 *   全部前 10 无命中 / 空 keywords → 未命中 / 未跑 (info)
 */
export function zhihuSearchTaskStatus(
  latest: { status?: string | null; metric?: any } | null | undefined,
): ZhihuSearchStatus {
  if (!latest) return { label: "未跑", tone: "info" };
  if (latest.status === "error") return { label: "鉴权失败", tone: "alert" };
  if (latest.status === "risk_control") return { label: "限频", tone: "warn" };
  const kws = latest.metric?.keywords;
  if (!Array.isArray(kws) || kws.length === 0) return { label: "未跑", tone: "info" };
  const anyHit = kws.some((k: any) => Number(k?.first_rank) > 0);
  return anyHit ? { label: "正常", tone: "ok" } : { label: "未命中", tone: "info" };
}
