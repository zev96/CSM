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
/** §7.3：成稿记录引用（供历史页「重新生成」预填 Hero/横评 query）。 */
export interface CreationRecordRef {
  keyword: string | null;
  template_id: string | null;
  title: string | null;
  angle_json: string | null;
  skill_chain_json: string | null;
  mode: string;
  models_json: string | null;
  contract_mode: string | null;
}

export interface RecentDoc {
  path: string;
  filename: string;
  title: string;
  template_name: string | null;
  words: number;
  modified_at: string;
  format: "markdown" | "docx";
  // Phase 4+ §7.3（新前端读、旧后端不返回时 undefined，均兼容）。
  facts_stale?: boolean;
  stale_models?: string[];
  record?: CreationRecordRef | null;
}

export async function listRecent(limit = 5, days = 7) {
  return (await client().get("/api/recent", { params: { limit, days } })).data as {
    count: number;
    documents: RecentDoc[];
  };
}

// ── /api/feedback + /api/facts（Phase 4+ §6.4 / §7.2-7.3）────────────────────
export interface NoteStat {
  note_id: string;
  uses: number;
  avg_edit_ratio: number | null;
  avg_score: number | null;
  keep_score: number | null;
}
export interface AngleStat {
  audience: string | null;
  sellpoints: string[];
  tone: string | null;
  uses: number;
  avg_score: number | null;
  avg_edit_ratio: number | null;
}
export async function feedbackStats() {
  return (await client().get("/api/feedback/stats")).data as {
    notes: NoteStat[];
    angles: AngleStat[];
  };
}

export interface FieldChange {
  field: string;
  old: string | null;
  new: string | null;
}
export interface ModelChange {
  model: string;
  changed: FieldChange[];
  detected_at: string;
}
export async function factsChanges() {
  return (await client().get("/api/facts/changes")).data as { changes: ModelChange[] };
}
export async function factsDiff(model: string) {
  return (await client().get("/api/facts/diff", { params: { model } })).data as {
    model: string;
    changed: FieldChange[];
  };
}

// ── /api/health ────────────────────────────────────────────────────────────
export async function health() {
  return (await client().get("/health")).data as { status: string };
}

// ── /api/version ───────────────────────────────────────────────────────────
// Sidecar 自报版本号，由 csm_sidecar.__version__ 决定，release.py 跟
// tauri.conf.json / Cargo.toml 一起 bump。前端**不该**自己存常量版本号
// （以前的 const APP_VERSION = "0.4.0" 就是因为没人记得 bump、显示成
// 跟实际装的版本号差几号）。
export async function getVersion() {
  return (await client().get("/api/version")).data as { sidecar: string };
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

export interface SSEOptions {
  /** EventSource onerror 时回调（连接会自动重连；用于触发一次快照对账）。 */
  onError?: () => void;
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
export function subscribe(
  path: string,
  handlers: SSEHandlers,
  opts: SSEOptions = {},
): () => void {
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
  if (opts.onError) {
    es.onerror = () => opts.onError!();
  }
  return () => es.close();
}
