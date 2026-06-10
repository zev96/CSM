/**
 * In-app notification log — backs the bell icon dropdown in App.vue.
 *
 * Separate from `useToast` because toasts are ephemeral (auto-dismiss in
 * a few seconds) while notifications are a persistent log the user
 * checks via the bell badge: ToastContainer renders pinned at the
 * bottom and disappears; this store keeps history.
 *
 * Singleton ref-array pattern (same shape as useToast) so any component
 * can push without dependency injection.
 *
 * Filtering happens in two layers:
 *   1. master switch  `enabled`  — kill switch for everything
 *   2. per-category   `categories[cat]` — the user can mute e.g.
 *      "评论异动" while still receiving "生成文章成功"
 * Both are persisted to localStorage so they survive a reload before
 * the settings store rehydrates.
 */
import { computed, reactive, ref, watch } from "vue";

/**
 * Stable category IDs — also the keys persisted to localStorage. Adding
 * a new category here means existing localStorage blobs won't have it,
 * so `loadCategories` falls back to the default (true) for missing keys.
 */
export type NotificationCategory =
  | "article_success"
  | "article_failure"
  | "ranking_change"
  | "comment_change"
  | "monitor_alert"
  | "monitor_done"
  | "mining_done"
  | "export_done"
  | "system";

export interface NotificationCategoryMeta {
  key: NotificationCategory;
  label: string;
  hint: string;
}

/**
 * The single source of truth for what the prefs dialog renders and what
 * the push() routes against. The label/hint copy lives here so the
 * dialog stays a thin v-for; add a category by appending one row.
 */
export const NOTIFICATION_CATEGORIES: NotificationCategoryMeta[] = [
  {
    key: "article_success",
    label: "生成文章 · 成功",
    hint: "一篇文章润色 / 生成完成时推送",
  },
  {
    key: "article_failure",
    label: "生成文章 · 失败",
    hint: "生成失败 / 中断时推送（建议开启）",
  },
  {
    key: "ranking_change",
    label: "排名异动",
    hint: "监测到 Top N 名次上下浮动时推送",
  },
  {
    key: "comment_change",
    label: "评论异动",
    hint: "新增/删除评论、热评变化时推送",
  },
  {
    key: "monitor_alert",
    label: "监测告警",
    hint: "Cookie 失效、抓取连续失败等系统级告警",
  },
  {
    key: "monitor_done",
    label: "监测任务完成",
    hint: "监测任务跑完一轮时推送（含定时）",
  },
  {
    key: "mining_done",
    label: "引流任务完成",
    hint: "视频抓取任务结束（含部分完成）时推送",
  },
  {
    key: "export_done",
    label: "导出完成",
    hint: "Markdown / DOCX 落盘完成时推送",
  },
  {
    key: "system",
    label: "系统消息",
    hint: "升级提示、版本变更等",
  },
];

export interface Notification {
  id: number;
  /** Short single-line title (shows in the dropdown). */
  title: string;
  /** Optional longer body (collapsed by default, shown in tooltip). */
  body?: string;
  /** When created, used for the relative "5 分钟前" label. */
  at: number;
  /** Origin tag — e.g. "monitor" / "system". Affects the colour dot. */
  tone: "info" | "success" | "warn" | "error";
  /**
   * Routing tag — push() looks this up in `_categories`. Optional for
   * backwards-compat (untagged pushes are treated as "system").
   */
  category: NotificationCategory;
  read: boolean;
}

const _items = ref<Notification[]>([]);
let _seq = 1;

// ── Master enable flag ──────────────────────────────────────────────
const ENABLED_KEY = "csm.notify.enabled.v1";
const _enabled = ref<boolean>(loadEnabled());

function loadEnabled(): boolean {
  if (typeof localStorage === "undefined") return true;
  const raw = localStorage.getItem(ENABLED_KEY);
  if (raw == null) return true;
  return raw === "1";
}
function saveEnabled(v: boolean) {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(ENABLED_KEY, v ? "1" : "0");
}

// ── Per-category flags ──────────────────────────────────────────────
const CATEGORIES_KEY = "csm.notify.categories.v1";

type CategoryMap = Record<NotificationCategory, boolean>;

function defaultCategories(): CategoryMap {
  const m = {} as CategoryMap;
  for (const c of NOTIFICATION_CATEGORIES) m[c.key] = true;
  return m;
}

function loadCategories(): CategoryMap {
  const base = defaultCategories();
  if (typeof localStorage === "undefined") return base;
  try {
    const raw = localStorage.getItem(CATEGORIES_KEY);
    if (!raw) return base;
    const parsed = JSON.parse(raw) as Partial<CategoryMap>;
    // Missing keys (new categories added in a future version) fall back
    // to the default `true` so a stale localStorage doesn't silently
    // hide a brand-new notification type.
    for (const c of NOTIFICATION_CATEGORIES) {
      if (typeof parsed[c.key] === "boolean") {
        base[c.key] = parsed[c.key] as boolean;
      }
    }
    return base;
  } catch {
    return base;
  }
}

const _categories = reactive<CategoryMap>(loadCategories());

watch(
  _categories,
  (v) => {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(CATEGORIES_KEY, JSON.stringify(v));
  },
  { deep: true },
);

// ── Push / mutate ──────────────────────────────────────────────────
function push(
  title: string,
  opts: {
    body?: string;
    tone?: Notification["tone"];
    category?: NotificationCategory;
  } = {},
): number | null {
  if (!_enabled.value) return null;
  const category: NotificationCategory = opts.category ?? "system";
  if (_categories[category] === false) return null;
  const id = _seq++;
  _items.value.unshift({
    id,
    title,
    body: opts.body,
    at: Date.now(),
    tone: opts.tone ?? "info",
    category,
    read: false,
  });
  // Cap log to 50 — older entries are dropped to avoid unbounded growth.
  if (_items.value.length > 50) _items.value.splice(50);
  return id;
}

function markAllRead() {
  _items.value.forEach((n) => (n.read = true));
}
function clear() {
  _items.value = [];
}
function setEnabled(v: boolean) {
  _enabled.value = v;
  saveEnabled(v);
}
function setCategory(c: NotificationCategory, v: boolean) {
  _categories[c] = v;
}

export function useNotifications() {
  const unreadCount = computed(
    () => _items.value.filter((n) => !n.read).length,
  );
  return {
    items: _items,
    unreadCount,
    enabled: _enabled,
    categories: _categories,
    push,
    markAllRead,
    clear,
    setEnabled,
    setCategory,
  };
}
