/**
 * Monitor — shared types & UI constants used by MonitorView.vue and the
 * per-tab sub-modules (Comment / Zhihu / Baidu / Report).
 *
 * Extracted from MonitorView.vue (Phase 2 of the v0.5.2-audit split) so
 * the new CommentMonitorModule can import the same shapes the parent
 * uses, without each module redeclaring its own Task / SampleComment /
 * CommentAlertData etc. Keep this file ref-free — pure type & constant
 * declarations only.
 */

export interface Task {
  id: number;
  type: string;
  name: string;
  target_url: string;
  enabled: boolean;
  schedule_cron: string;
  last_check_at: string | null;
  last_status: string | null;
}

export type CommentPlatform = "bilibili" | "douyin" | "kuaishou";

export interface SampleComment {
  id: string;
  kw: string;
  lastChecked: string;
  retained: number;
  total: number;
  delta: number;
  status: "ok" | "warn" | "alert";
}

export interface VideoEntry {
  id: string;
  url: string;
  /** 视频原标题 —— 列表渲染时只取前 15 字，鼠标悬停看全文。 */
  title: string;
  /** 我自己在这条视频下的评论原文。 */
  myComment: string;
  /** 我的评论目前在该视频下的热度排名。 */
  rank: number;
  /** 评论现状：在显 / 被删 / 折叠。 */
  status: "ok" | "deleted" | "folded";
  /** 评论发出时间。 */
  postedAt: string;
  /** 视频评论区的总评论数（仅展示用）。 */
  totalComments: number;
}

export interface AlertDeletedComment {
  who: string;       // 抢占者作者（hot_comments[0].author）或 "—"
  text: string;      // 我的评论原文
  date: string;
  state: "被删" | "折叠";
}

export interface CommentAlertData {
  title: string;
  subtitle: string;
  retained: number;
  total: number;
  ratio: number;     // 0-100
  recentDelta: number;   // 留存数变化
  prevRetained: number | null;
  sparkPoints: number[];
  sparkAxis: string[];
  deleted: AlertDeletedComment[];
}

export interface HeroAlert {
  keyword: string;
  headline: string;
  subtitle: string;
  /** 知乎告警：定位到具体 task。 */
  taskId?: number;
  /** 评论告警：定位到具体批次。 */
  batchName?: string;
}

export interface MonitorState {
  enabled: boolean;
  schedule: string;
}

export const SCHEDULE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "manual", label: "手动触发" },
  { value: "hourly-1", label: "每 1 小时" },
  { value: "hourly-6", label: "每 6 小时" },
  { value: "daily-09:00", label: "每天 09:00" },
  { value: "daily-12:00", label: "每天 12:00" },
  { value: "daily-18:00", label: "每天 18:00" },
];

export function scheduleLabel(v: string): string {
  return SCHEDULE_OPTIONS.find((o) => o.value === v)?.label ?? v;
}
