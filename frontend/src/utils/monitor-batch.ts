/**
 * Monitor batch + status helpers — small pure utilities shared between
 * MonitorView and its per-tab sub-modules.
 *
 * Extracted from MonitorView.vue (around lines 644-1177) as Phase 1 of
 * the v0.5.2-audit split: pulling pure functions into utils first means
 * the upcoming CommentMonitorModule can import the same logic without
 * having to drag the parent component along.
 */

/**
 * Parse the batch-name prefix from a comment monitor task name.
 *
 * Convention: tasks created via BatchImportTaskModal get
 * ``name = `${batchName} - ${urlTail}` `` so the same batch shows up as
 * one row in the L1 list and expands into its videos in L2. Tasks
 * created one-at-a-time via AddTaskModal don't have that prefix — we
 * treat them as their own single-item batch.
 *
 * Strategy: split on the **last** ``" - "`` (not the first). Batch
 * names themselves can contain hyphens; the URL tail typically doesn't,
 * but even if it did we'd misattribute a single character, which is
 * preferable to misattributing the whole batch name.
 */
export function parseBatchName(taskName: string): string {
  const idx = taskName.lastIndexOf(" - ");
  if (idx <= 0) return taskName;
  return taskName.slice(0, idx);
}

/**
 * Pill color for a retention ratio.
 *
 * 90%+ green, 60-89% yellow, sub-60% red. Thresholds match the
 * settings page's user-facing copy; changing these means updating both.
 */
export function statusFromRatio(retained: number, total: number): "ok" | "warn" | "alert" {
  if (total === 0) return "ok";
  const ratio = retained / total;
  if (ratio >= 0.9) return "ok";
  if (ratio >= 0.6) return "warn";
  return "alert";
}

/**
 * Coarse human time delta — "刚刚 / N 分钟前 / N 小时前 / N 天前 /
 * absolute date". Used for the L1 table's "上次检查" column and the
 * task list's last-status timestamp.
 */
export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  if (Number.isNaN(diffMs)) return "—";
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} 小时前`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days} 天前`;
  return d.toLocaleDateString();
}

/**
 * Compact "今天 HH:mm / 昨天 HH:mm / M/D HH:mm" timestamp — used by the
 * alert modal's history timeline. Keeps two days in relative form so
 * recent alerts are scannable; older ones fall back to numeric date.
 */
export function formatTimelineTime(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yest = new Date(now);
  yest.setDate(yest.getDate() - 1);
  const isYesterday = d.toDateString() === yest.toDateString();
  const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (sameDay) return `今天 ${hhmm}`;
  if (isYesterday) return `昨天 ${hhmm}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hhmm}`;
}

/**
 * 知乎原生「被浏览」数展示：< 1万 原数；1万~1亿 → X.X万；≥ 1亿 → X.X亿。
 * 空 / NaN → "—"。去掉 ".0" 尾巴（350.0万 → 350万）。
 */
export function formatVisitCount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n < 10000) return String(n);
  if (n < 1e8) return `${(n / 10000).toFixed(1).replace(/\.0$/, "")}万`;
  return `${(n / 1e8).toFixed(1).replace(/\.0$/, "")}亿`;
}
