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
  /**
   * 适配器特定配置 —— 知乎 ``{ target_brand, top_n }``，评论
   * ``{ my_comment_text, top_n }``。后端 task_to_dict 总是返回这个字段
   * （即便为 {}）；UI 按平台读所需的键。
   */
  config?: Record<string, any>;
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
  /** 评论现状(只检索前 scanDepth 名):
   *   ok       在前 alert_top_n 名(在显)
   *   folded   命中但排在 alert_top_n 名之后、仍在前 scanDepth(跌出理想)
   *   deleted  上次还在前 scanDepth、这次查不到 → 被删除(留存告警)
   *   beyond   从没进过前 scanDepth → 超N名外(排 N 名外,或本就被删/限流)
   *   pending  没跑过 / 评论区为空且无留存历史 → 未监测
   *   failed   本次监测报错(网络/接口/熔断)→ 监测失败,别伪装成未找到 */
  status: "ok" | "folded" | "deleted" | "beyond" | "pending" | "failed";
  /** 本次检索深度（后端 metric.depth_cap，"前 N 名"的 N）；缺失回退 100。
   *  所有 "超 N 名外 / N+ / 前 N 名" 文案读它，改深度只动后端。 */
  scanDepth: number;
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

/**
 * GEO 卡位监控（AI 卡位）·「API 联网采集」平台 —— 通义千问（阶段 1）+ 豆包（阶段 2，
 * 火山方舟 Ark 联网 bot）。这两家 API 都能回联网信源。
 * Kimi / DeepSeek / 腾讯元宝 / 夸克AI 的 API 不回信源 URL（Moonshot $web_search 只给
 * search_id；或干脆没联网 API），统一放阶段 3 走 RPA（开真网页抓回答+来源）。
 */
export const GEO_PLATFORMS = [
  { value: "tongyi", label: "通义千问", mode: "api" },
  { value: "doubao", label: "豆包", mode: "api" },
  { value: "deepseek", label: "DeepSeek", mode: "rpa" },
  { value: "kimi", label: "Kimi", mode: "rpa" },
  { value: "yuanbao", label: "腾讯元宝", mode: "rpa" },
] as const;

/**
 * geo_query 任务的 ``config`` 形状（对齐 csm_core.monitor.platforms.geo_query
 * adapter 读取的键）：品牌 + 别名 + 批量关键词 + 平台多选 + 联网开关 +
 * 抽取模型。``top_n_citations`` 给信源榜取数用。
 */
export interface GeoTaskConfig {
  brand: string;
  brand_aliases: string[];
  keywords: string[];
  platforms: string[];
  web_search: boolean;
  extract_provider: string;
  top_n_citations: number;
}

/**
 * zhihu_search 任务的 ``config`` 形状（对齐 csm_core.monitor.platforms.zhihu_search
 * adapter 读取的键）：多关键词 + 单品牌词 + 可选别名 + 固定 count。
 * ``match_full_text`` 为 PR #3 的可选全文匹配开关（默认 false）。
 */
export interface ZhihuSearchTaskConfig {
  search_keywords: string[];
  target_brand: string;
  brand_aliases: string[];
  count: number;
  match_full_text?: boolean;
}

/**
 * 信源榜一行（GET /api/monitor/geo/{id}/citations 的 leaderboard 元素）。
 * 域名频次降序，platforms/keywords 是聚合出现过的平台与关键词。
 */
export interface CitationRow {
  domain: string;
  source_type: string;
  count: number;
  platforms: string[];
  keywords: string[];
}

export const SCHEDULE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "manual", label: "手动触发" },
  { value: "hourly-1", label: "每 1 小时" },
  { value: "hourly-6", label: "每 6 小时" },
  { value: "daily-09:00", label: "每天 09:00" },
  { value: "daily-12:00", label: "每天 12:00" },
  { value: "daily-18:00", label: "每天 18:00" },
  { value: "weekly-0-09:00", label: "每周一 09:00" },
  { value: "weekly-3-09:00", label: "每周四 09:00" },
  { value: "weekly-5-09:00", label: "每周六 09:00" },
];

export function scheduleLabel(v: string): string {
  return SCHEDULE_OPTIONS.find((o) => o.value === v)?.label ?? v;
}
