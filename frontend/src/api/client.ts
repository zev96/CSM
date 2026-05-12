/**
 * Thin wrappers around the sidecar HTTP API.
 *
 * Each call grabs the axios client from the sidecar store at *call*
 * time so a token rotation (re-bootstrap) takes effect immediately.
 *
 * SSE streams use the native EventSource; we expose a tiny ``subscribe``
 * helper that returns a teardown function.
 */
import { useSidecar } from "@/stores/sidecar";

function client() {
  return useSidecar().client;
}

// ── /api/config ────────────────────────────────────────────────────────────
export async function getConfig() {
  return (await client().get("/api/config")).data;
}

export async function patchConfig(updates: Record<string, unknown>) {
  return (await client().patch("/api/config", updates)).data;
}

// ── /api/keyring ────────────────────────────────────────────────────────────
export async function keyringStatus(provider: string) {
  return (await client().get(`/api/keyring/${provider}`)).data as {
    provider: string;
    has_key: boolean;
  };
}

export async function keyringSet(provider: string, value: string) {
  return (await client().post(`/api/keyring/${provider}`, { value })).data;
}

export async function keyringDelete(provider: string) {
  return (await client().delete(`/api/keyring/${provider}`)).data;
}

// ── /api/recent ────────────────────────────────────────────────────────────
export async function listRecent(limit = 5, days = 7) {
  return (await client().get("/api/recent", { params: { limit, days } })).data as {
    count: number;
    documents: Array<{
      path: string;
      filename: string;
      title: string;
      template_name: string | null;
      words: number;
      modified_at: string;
      format: "markdown" | "docx";
    }>;
  };
}

// ── /api/calendar ──────────────────────────────────────────────────────────
export async function getCalendar(month?: string) {
  return (await client().get("/api/calendar", { params: month ? { month } : {} }))
    .data as {
    year: number;
    month: number;
    days: number;
    done: number[];
    scheduled: number[];
  };
}

// ── /api/stats/words ───────────────────────────────────────────────────────
export async function getWordsStats(range: "yesterday" | "this-week" = "this-week") {
  return (await client().get("/api/stats/words", { params: { range } })).data as {
    range: string;
    start: string;
    end: string;
    total_words: number;
    by_day: Array<{ date: string; weekday: string; words: number; polished: number }>;
  };
}

// ── /api/health ────────────────────────────────────────────────────────────
export async function health() {
  return (await client().get("/health")).data as { status: string };
}

// ── /api/keyword/density ───────────────────────────────────────────────────
export async function keywordDensity(keyword: string, text: string) {
  return (await client().post("/api/keyword/density", { keyword, text })).data as {
    count: number;
    density: number;
    text_length: number;
    keyword_length: number;
  };
}

// ── /api/updater ───────────────────────────────────────────────────────────
export interface UpdaterCheckResult {
  has_update: boolean;
  current_version: string;
  error: string | null;
  info: {
    version: string;
    tag_name: string;
    zip_url: string;
    manifest_url: string;
    changelog: string;
    published_at: string;
    asset_size: number;
    /**
     * 64 字符的 sha256，由 sidecar 在 check 时单独 fetch manifest.json 获取。
     * 如果 manifest 不可达（release 没附 manifest.json / 临时网络抖动），
     * 这里是空字符串 —— 下载入口需先检测，否则 download 路由会 422 拒绝。
     */
    expected_sha256: string;
  } | null;
}

export async function updaterCheck() {
  return (await client().get("/api/updater/check")).data as UpdaterCheckResult;
}

export async function updaterDownload(url: string, expected_sha256: string) {
  return (
    await client().post("/api/updater/download", { url, expected_sha256 })
  ).data as { job_id: string; stream_url: string };
}

// ── SSE subscription helper ────────────────────────────────────────────────
export interface SSEHandlers {
  [event: string]: (data: any) => void;
}

/**
 * Subscribe to a sidecar SSE stream by relative path.
 * Returns a teardown function that closes the underlying EventSource.
 *
 * Usage::
 *
 *   const stop = subscribe("/api/events/JOB_ID", {
 *     stage:  (d) => console.log("stage", d.stage),
 *     done:   (d) => { console.log("done", d); stop(); },
 *     error:  (d) => { console.error(d.error); stop(); },
 *   });
 */
export function subscribe(path: string, handlers: SSEHandlers): () => void {
  const url = useSidecar().sseURL(path);
  const es = new EventSource(url);
  for (const [event, handler] of Object.entries(handlers)) {
    es.addEventListener(event, (e) => {
      const me = e as MessageEvent;
      let data: unknown = me.data;
      try {
        data = JSON.parse(me.data);
      } catch {
        /* leave as raw string */
      }
      handler(data);
    });
  }
  return () => es.close();
}
