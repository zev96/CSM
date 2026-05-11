/**
 * Article generation job state.
 *
 * Owns the SSE subscription for one in-flight `/api/generate` job at a
 * time — submitting a fresh request tears down the previous stream.
 *
 * The flow:
 *   submit({keyword, template_id, skill_id, ...})
 *     → POST /api/generate → 202 {job_id}
 *     → subscribe /api/events/{job_id}
 *       stage: bumps progress, pushes stage label
 *       done:  { document, format, title, plan, final_text }
 *       error: surfaces the failure verbatim
 *
 * Other sidecar calls (polish, title candidates, dedup analyze) are
 * exposed as actions here too so views can keep their script blocks
 * thin.
 */
import { defineStore } from "pinia";

import { subscribe } from "@/api/client";
import { useSidecar } from "./sidecar";

export interface GenerateRequest {
  keyword: string;
  template_id: string;
  skill_id?: string | null;
  seed?: number;
  draft_only?: boolean;
  core_keyword?: string | null;
  provider?: string | null;
  model?: string | null;
}

const STAGES = [
  "扫描资料库",
  "加载模板",
  "采样 blocks",
  "组装 prompt",
  "调用 LLM",
  "导出",
];

interface ArticleState {
  jobId: string | null;
  // Job_id of the *most recently submitted* generate. Survives across
  // teardown so the per-pick reroll endpoint can find the cached plan
  // even after the SSE stream has closed.
  lastJobId: string | null;
  // SSE teardown — populated while a job is live.
  stop: (() => void) | null;
  status: "idle" | "running" | "done" | "error";
  currentStage: string | null;
  stageIndex: number;
  // Sticky on done — the views read these for display.
  documentPath: string | null;
  format: string | null;
  finalText: string;
  draftText: string;
  title: string;
  plan: Record<string, any> | null;
  error: string | null;
  // Last submitted request — kept around so UI can re-run with tweaks.
  lastRequest: GenerateRequest | null;
  // Per-call helpers (independent of the streaming generate job).
  titleCandidates: string[];
  titleLoading: boolean;
  dedupReport: any | null;
  dedupLoading: boolean;
  // Keyword density — refreshed alongside finalText so the quality
  // report reflects edits without per-keystroke API spam.
  keywordDensity: { count: number; density: number } | null;
}

export const useArticle = defineStore("article", {
  state: (): ArticleState => ({
    jobId: null,
    lastJobId: null,
    stop: null,
    status: "idle",
    currentStage: null,
    stageIndex: -1,
    documentPath: null,
    format: null,
    finalText: "",
    draftText: "",
    title: "",
    plan: null,
    error: null,
    lastRequest: null,
    titleCandidates: [],
    titleLoading: false,
    dedupReport: null,
    dedupLoading: false,
    keywordDensity: null,
  }),
  getters: {
    progress(state): number {
      if (state.status === "done") return 1;
      if (state.stageIndex < 0) return 0;
      return Math.min(1, (state.stageIndex + 1) / STAGES.length);
    },
    stages: () => STAGES,
    isRunning: (state) => state.status === "running",
  },
  actions: {
    async submit(req: GenerateRequest): Promise<void> {
      this._teardown();
      this.lastRequest = req;
      this.status = "running";
      this.error = null;
      this.currentStage = null;
      this.stageIndex = -1;
      this.finalText = "";
      this.draftText = "";
      this.documentPath = null;
      this.title = req.keyword;
      this.plan = null;

      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post("/api/generate", req);
        this.jobId = resp.data.job_id;
        this.lastJobId = resp.data.job_id;
      } catch (e: any) {
        this.status = "error";
        this.error = e?.response?.data?.detail ?? e?.message ?? String(e);
        return;
      }

      this.stop = subscribe(`/api/events/${this.jobId}`, {
        stage: (d: any) => {
          this.currentStage = d.stage;
          // The sidecar emits {stage, index, total} — fall back to STAGES
          // lookup if the index isn't present.
          if (typeof d.index === "number") {
            this.stageIndex = d.index;
          } else {
            const i = STAGES.indexOf(d.stage);
            if (i >= 0) this.stageIndex = i;
          }
        },
        done: (d: any) => {
          this.documentPath = d.document ?? null;
          this.format = d.format ?? null;
          this.title = d.title ?? this.title;
          this.finalText = d.final_text ?? d.draft ?? "";
          this.draftText = d.draft ?? "";
          this.plan = d.plan ?? null;
          this.stageIndex = STAGES.length;
          this.status = "done";
          this._teardown();
        },
        error: (d: any) => {
          this.error = d.error ?? "unknown error";
          this.status = "error";
          this._teardown();
        },
      });
    },
    /** Re-run the last request — useful for "重新随机" buttons. */
    async rerun(): Promise<void> {
      if (!this.lastRequest) return;
      // Bump seed by 1 so the assembler re-samples instead of giving the
      // exact same draft back.
      const next = {
        ...this.lastRequest,
        seed: (this.lastRequest.seed ?? 0) + 1,
      };
      await this.submit(next);
    },
    /** Cancel the live SSE subscription. The worker thread keeps going
     * (no /generate cancel endpoint yet), but the UI stops listening. */
    cancel() {
      this._teardown();
      if (this.status === "running") this.status = "idle";
    },
    /** Replace the local final text — used by polish results that the
     * user accepts manually (no auto-write back to disk). */
    setFinalText(text: string) {
      this.finalText = text;
    },
    async fetchTitleCandidates(): Promise<void> {
      if (!this.lastRequest) return;
      const sidecar = useSidecar();
      this.titleLoading = true;
      try {
        const resp = await sidecar.client.post("/api/title", {
          keyword: this.lastRequest.keyword,
          template_type: null,
          n_candidates: 5,
          provider: this.lastRequest.provider ?? null,
          model: this.lastRequest.model ?? null,
        });
        this.titleCandidates = resp.data.candidates ?? [];
      } catch (e: any) {
        this.titleCandidates = [];
      } finally {
        this.titleLoading = false;
      }
    },
    async runDedup(text: string, kind: "history" | "vault" = "history"): Promise<void> {
      const sidecar = useSidecar();
      this.dedupLoading = true;
      try {
        const resp = await sidecar.client.post("/api/dedup/analyze", {
          text,
          kind,
        });
        this.dedupReport = resp.data;
      } catch (e: any) {
        this.dedupReport = null;
      } finally {
        this.dedupLoading = false;
      }
      // Density is cheap (no LLM, no SSE) — recompute alongside dedup so
      // the quality report shows both numbers in one click.
      await this.refreshDensity(text);
    },
    async refreshDensity(text?: string): Promise<void> {
      if (!this.lastRequest) return;
      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post("/api/keyword/density", {
          keyword: this.lastRequest.keyword,
          text: text ?? this.finalText,
        });
        this.keywordDensity = {
          count: resp.data.count,
          density: resp.data.density,
        };
      } catch {
        this.keywordDensity = null;
      }
    },
    /** Re-sample one pick inside the current plan (no LLM rerun).
     *
     * The sidecar caches plans by job_id; after a fresh generate the
     * cache holds this article's plan. We POST the pick coordinates and
     * receive the updated plan + recomputed draft. ``finalText`` is
     * left untouched — user must explicitly re-polish to replay the LLM.
     */
    async rerollPick(blockId: string, pickIndex: number): Promise<boolean> {
      if (!this.lastJobId) return false;
      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post("/api/assembler/reroll", {
          job_id: this.lastJobId,
          block_id: blockId,
          pick_index: pickIndex,
        });
        this.plan = resp.data.plan ?? this.plan;
        this.draftText = resp.data.draft ?? this.draftText;
        return true;
      } catch (e: any) {
        const detail = e?.response?.data?.detail ?? e?.message ?? String(e);
        // Surface the original error so the caller can toast it cleanly.
        throw new Error(detail);
      }
    },
    async polishWhole(text: string): Promise<string | null> {
      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post("/api/polish/block", {
          text,
          skill_id: this.lastRequest?.skill_id ?? null,
          provider: this.lastRequest?.provider ?? null,
          model: this.lastRequest?.model ?? null,
        });
        return resp.data.text ?? null;
      } catch {
        return null;
      }
    },
    async exportArticle(opts: { format: "markdown" | "docx"; include_dedup_report?: boolean }) {
      if (!this.finalText.trim() || !this.lastRequest) return null;
      const sidecar = useSidecar();
      const resp = await sidecar.client.post(`/api/export/${opts.format}`, {
        keyword: this.lastRequest.keyword,
        final_text: this.finalText,
        include_dedup_report: opts.include_dedup_report ?? false,
      });
      this.documentPath = resp.data.document ?? this.documentPath;
      this.format = resp.data.format ?? this.format;
      return resp.data;
    },
    _teardown() {
      if (this.stop) {
        try {
          this.stop();
        } catch {
          /* ignore teardown errors */
        }
      }
      this.stop = null;
      this.jobId = null;
    },
  },
});
