/**
 * Batch generation state.
 *
 * Holds *one* live batch job. Submitting a new batch tears down the
 * SSE listener for the previous one (the worker thread keeps going
 * server-side; this store just stops listening).
 */
import { defineStore } from "pinia";

import { subscribe } from "@/api/client";
import { useSidecar } from "./sidecar";
import { useNotifications } from "@/composables/useNotifications";

export interface BatchItem {
  index: number;
  keyword: string;
  status: "queued" | "running" | "success" | "failed" | "cancelled";
  duration_seconds: number;
  document: string | null;
  error_type: string | null;
  error_message: string | null;
}

interface BatchState {
  jobId: string | null;
  stop: (() => void) | null;
  status: "idle" | "running" | "done" | "error" | "cancelled";
  items: BatchItem[];
  outDir: string | null;
  total: number;
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
  // Defaults for next submit.
  templateId: string;
  skillId: string;
  provider: string | null;
  // Summary on done.
  byStatus: Record<string, number>;
  totalDuration: number;
}

export const useBatch = defineStore("batch", {
  state: (): BatchState => ({
    jobId: null,
    stop: null,
    status: "idle",
    items: [],
    outDir: null,
    total: 0,
    startedAt: null,
    finishedAt: null,
    error: null,
    templateId: "",
    skillId: "",
    provider: null,
    byStatus: {},
    totalDuration: 0,
  }),
  getters: {
    isRunning: (state) => state.status === "running",
    progress(state): number {
      if (!state.total) return 0;
      const done = state.items.filter(
        (i) => i.status === "success" || i.status === "failed" || i.status === "cancelled",
      ).length;
      return done / state.total;
    },
  },
  actions: {
    async submit(keywords: string[]): Promise<void> {
      this._teardown();
      this.status = "running";
      this.error = null;
      this.items = [];
      this.byStatus = {};
      this.totalDuration = 0;
      this.outDir = null;
      this.finishedAt = null;
      this.startedAt = new Date().toISOString();

      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post("/api/batch", {
          keywords,
          template_id: this.templateId,
          skill_id: this.skillId || undefined,
          provider: this.provider ?? undefined,
        });
        this.jobId = resp.data.job_id;
        this.total = resp.data.total ?? keywords.length;
      } catch (e: any) {
        this.status = "error";
        this.error = e?.response?.data?.detail ?? e?.message ?? String(e);
        return;
      }

      // Pull initial snapshot to populate the queue immediately.
      await this.refreshSnapshot();

      this.stop = subscribe(`/api/events/${this.jobId}`, {
        started: (d: any) => {
          this.outDir = d.out_dir ?? null;
        },
        item_started: (d: any) => {
          const it = this.items.find((x) => x.index === d.index);
          if (it) it.status = "running";
        },
        item_finished: (d: any) => {
          const it = this.items.find((x) => x.index === d.index);
          if (it) {
            it.status = d.status;
            it.duration_seconds = d.duration_seconds ?? 0;
            it.document = d.document ?? null;
            it.error_type = d.error_type ?? null;
            it.error_message = d.error_message ?? null;
          }
        },
        cancel_requested: () => {
          /* no-op — UI knows cancel was requested via this.cancel() */
        },
        done: (d: any) => {
          this.status = "done";
          this.byStatus = d.by_status ?? {};
          this.totalDuration = d.total_duration_seconds ?? 0;
          this.finishedAt = new Date().toISOString();
          const failedCount = Number((d.by_status ?? {}).failed ?? 0);
          useNotifications().push("批量生成完成", {
            body: `共 ${this.total} 篇 · 成功 ${Number((d.by_status ?? {}).success ?? 0)}${failedCount ? ` · 失败 ${failedCount}` : ""}`,
            tone: failedCount ? "warn" : "success",
            category: "article_success",
          });
          this._teardown();
        },
        error: (d: any) => {
          this.status = "error";
          this.error = d.error ?? "unknown error";
          useNotifications().push("批量生成失败", {
            body: this.error ?? "",
            tone: "error",
            category: "article_failure",
          });
          this._teardown();
        },
      });
    },
    async refreshSnapshot(): Promise<void> {
      if (!this.jobId) return;
      const sidecar = useSidecar();
      try {
        const r = await sidecar.client.get(`/api/batch/${this.jobId}`);
        this.items = r.data.items ?? [];
        this.total = this.items.length || this.total;
        this.outDir = r.data.out_dir ?? this.outDir;
        if (r.data.finished_at) {
          this.finishedAt = r.data.finished_at;
          if (this.status === "running") this.status = "done";
        }
      } catch {
        /* ignore */
      }
    },
    async cancel(): Promise<void> {
      if (!this.jobId) return;
      const sidecar = useSidecar();
      try {
        await sidecar.client.post(`/api/batch/${this.jobId}/cancel`);
        this.status = "cancelled";
      } catch {
        /* ignore */
      }
    },
    _teardown() {
      if (this.stop) {
        try {
          this.stop();
        } catch {
          /* ignore */
        }
      }
      this.stop = null;
      this.jobId = null;
    },
  },
});
