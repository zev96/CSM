/**
 * 评论留存率 CSV 导出 —— 把一个批次的 VideoEntry 列表（CommentMonitorModule
 * L2 塑形结果）转成 Excel 可直接打开的 CSV 文本。
 *
 * 纯函数、不碰 DOM / Tauri —— 文件保存流程留在组件里（Tauri save dialog /
 * 浏览器 <a download> 两条路径），这里只负责内容，方便 vitest 直接断言。
 * BOM 由调用方在保存时统一前置（与 mining / 知乎导出一致）。
 *
 * 状态 → 文案的映射与 CommentMonitorModule 的 Pill / notFoundHint 保持一致：
 * 在显 / 跌出理想 / 被删除 / 超N名外 / 未监测 / 监测失败。改任何一边记得同步。
 */
import type { VideoEntry } from "./monitor-types";

export interface RetentionExportItem {
  video: VideoEntry;
  /** 最近一次检查时间（ISO），没跑过为 null。 */
  checkedAt: string | null;
}

export interface RetentionSummary {
  total: number;
  /** 留存 = 命中（在显 + 跌出理想）；口径与 L1 列表的 retained/total 相同。 */
  retained: number;
  /** 0-100，一位小数；total=0 时为 0。 */
  ratePercent: number;
  byStatus: Record<VideoEntry["status"], number>;
}

export function summarizeRetention(videos: VideoEntry[]): RetentionSummary {
  const byStatus: RetentionSummary["byStatus"] = {
    ok: 0, folded: 0, deleted: 0, beyond: 0, pending: 0, failed: 0,
  };
  for (const v of videos) byStatus[v.status]++;
  const retained = byStatus.ok + byStatus.folded;
  const total = videos.length;
  const ratePercent = total > 0 ? Math.round((retained / total) * 1000) / 10 : 0;
  return { total, retained, ratePercent, byStatus };
}

/** RFC 4180 逃逸：含半角逗号/引号/换行的字段裹引号，内部引号翻倍。 */
function csvEscape(field: string): string {
  return /[",\r\n]/.test(field) ? `"${field.replace(/"/g, '""')}"` : field;
}

function statusLabel(v: VideoEntry): string {
  switch (v.status) {
    case "ok": return "在显";
    case "folded": return "跌出理想";
    case "deleted": return "被删除";
    case "beyond": return `超${v.scanDepth}名外`;
    case "pending": return "未监测";
    case "failed": return "监测失败";
  }
}

/** 「是否留存」列：命中=是；确认未命中=否；没跑过/报错单列出来别混进否。 */
function retainedLabel(v: VideoEntry): string {
  switch (v.status) {
    case "ok":
    case "folded": return "是";
    case "deleted":
    case "beyond": return "否";
    case "pending": return "未监测";
    case "failed": return "监测失败";
  }
}

/** 排名列：命中给纯数字（Excel 里可排序）；超深度=「N+」；其余无意义=「—」。 */
function rankLabel(v: VideoEntry): string {
  if (v.rank > 0) return String(v.rank);
  return v.status === "beyond" ? `${v.scanDepth}+` : "—";
}

function noteFor(v: VideoEntry): string {
  const n = v.scanDepth;
  switch (v.status) {
    case "ok": return "评论留存中，排名在理想范围内";
    case "folded": return "评论留存中，但已跌出理想排名";
    case "deleted": return `上次还在前 ${n} 名，这次没找到——评论可能已被删除（也可能跌出了前 ${n} 名）`;
    case "pending": return "尚未监测，或该视频评论区为空";
    case "beyond": return `未进入前 ${n} 名——排名在 ${n} 名以外，或已被删除/限流（本次共比对 ${v.totalComments || 0} 条评论）`;
    case "failed": return "本次监测失败（网络/接口错误或熔断），未能扫描评论";
  }
}

function fmtDateTime(d: Date): string {
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtChecked(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : fmtDateTime(d);
}

/**
 * 生成整份 CSV：头部汇总块（总计/留存/留存率/状态分布）+ 空行 + 明细表。
 * 行序保持传入顺序（与 L2 列表一致）。换行用 CRLF，Windows Excel 直开不串行。
 */
export function buildRetentionCsv(opts: {
  batchName: string;
  platformLabel: string;
  items: RetentionExportItem[];
  /** 注入导出时刻，默认当前时间；测试传固定值。 */
  now?: Date;
}): string {
  const { batchName, platformLabel, items } = opts;
  const s = summarizeRetention(items.map((x) => x.video));
  const lines: string[] = [];
  lines.push(["任务批次", batchName].map(csvEscape).join(","));
  lines.push(["平台", platformLabel].map(csvEscape).join(","));
  lines.push(["导出时间", fmtDateTime(opts.now ?? new Date())].join(","));
  lines.push(["总计", `${s.total} 条`].join(","));
  lines.push(["留存", `${s.retained} 条`].join(","));
  lines.push(["留存率", `${s.ratePercent}%`].join(","));
  lines.push([
    "状态分布",
    `在显 ${s.byStatus.ok} · 跌出理想 ${s.byStatus.folded} · 被删除 ${s.byStatus.deleted} · 超出检索 ${s.byStatus.beyond} · 未监测 ${s.byStatus.pending} · 监测失败 ${s.byStatus.failed}`,
  ].map(csvEscape).join(","));
  lines.push("");
  lines.push([
    "序号", "名称", "视频链接", "我的评论", "是否留存", "排名",
    "状态", "检索深度", "评论区总数", "最近检查", "说明",
  ].join(","));
  items.forEach((it, i) => {
    const v = it.video;
    lines.push([
      String(i + 1),
      v.title,
      v.url,
      v.myComment,
      retainedLabel(v),
      rankLabel(v),
      statusLabel(v),
      String(v.scanDepth),
      String(v.totalComments),
      fmtChecked(it.checkedAt),
      noteFor(v),
    ].map(csvEscape).join(","));
  });
  return lines.join("\r\n") + "\r\n";
}
