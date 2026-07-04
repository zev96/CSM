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
  // Phase 4+: 确定性评分（免费）+ 多候选选优信号。旧事件不带这些键时
  // 落到 refreshSnapshot 的 to_dict 快照也天然带（后端 dataclass 默认值）。
  score: number | null;
  score_parts: { key: string; label: string; points: number; detail: string }[];
  candidate_scores: number[];
  factcheck_violations: number;
}

/** 批量总成本汇总（镜像后端 done 事件 total_cost）。
 * 注意：这是本批「全部候选」的真实花费（含落选者），不是单篇成本 ——
 * 渲染时务必标「本批实际消耗」而非按篇均摊。 */
export interface BatchTotalCost {
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
  currency: string;
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
  // Phase 4+: 每关键词候选数（1-3），费用与候选数线性。默认 1 = 零回归。
  candidates: number;
  // Summary on done.
  byStatus: Record<string, number>;
  totalDuration: number;
  // Phase 4+: 本批总成本（含落选候选，见 BatchTotalCost 注释）。null=未知/旧事件。
  totalCost: BatchTotalCost | null;
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
    candidates: 1,
    byStatus: {},
    totalDuration: 0,
    totalCost: null,
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
      this.totalCost = null; // 起新批 —— 清掉上一轮成本汇总
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
          candidates: this.candidates,
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
            // Phase 4+: 评分/候选信号 —— 旧事件（未升级 sidecar）不带这些
            // 键，fallback 到 null/[]/0（不崩、不误报有信号）。
            it.score = typeof d.score === "number" ? d.score : null;
            it.score_parts = Array.isArray(d.score_parts) ? d.score_parts : [];
            it.candidate_scores = Array.isArray(d.candidate_scores) ? d.candidate_scores : [];
            it.factcheck_violations = typeof d.factcheck_violations === "number" ? d.factcheck_violations : 0;
          }
        },
        cancel_requested: () => {
          /* no-op — UI knows cancel was requested via this.cancel() */
        },
        done: (d: any) => {
          this.status = "done";
          this.byStatus = d.by_status ?? {};
          this.totalDuration = d.total_duration_seconds ?? 0;
          // Phase 4+: 本批总成本（含落选候选）。旧事件无该键 → 保持 null。
          this.totalCost = d.total_cost ?? null;
          this.finishedAt = new Date().toISOString();
          const byStatus = (d.by_status ?? {}) as Record<string, number>;
          const failedCount = Number(byStatus.failed ?? 0);
          const cancelledCount = Number(byStatus.cancelled ?? 0);
          if (cancelledCount === 0) {
            // 含被取消项 = 用户主动停的批次 —— 静默，与 monitor/article 取消语义一致
            useNotifications().push("批量生成完成", {
              body: `共 ${this.total} 篇 · 成功 ${Number(byStatus.success ?? 0)}${failedCount ? ` · 失败 ${failedCount}` : ""}`,
              tone: failedCount ? "warn" : "success",
              category: "article_success",
            });
          }
          this._teardown();
        },
        error: (d: any) => {
          const msg = String(d?.error ?? "");
          if (msg.startsWith("unknown job_id")) {
            // 断线期间事件队列已被 sidecar 回收 —— 合成 error，不是真失败。
            // EventSource 会持续重连并反复收到它，等效 ~3s 轮询：用快照对账，
            // 真终态由 refreshSnapshot 落地（含完成通知）后，下一轮再收流。
            void this.refreshSnapshot();
            if (this.status !== "running") this._teardown();
            return;
          }
          this.status = "error";
          this.error = d.error ?? "unknown error";
          useNotifications().push("批量生成失败", {
            body: this.error ?? "",
            tone: "error",
            category: "article_failure",
          });
          this._teardown();
        },
      }, {
        onError: () => { void this.refreshSnapshot(); },
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
          const wasRunning = this.status === "running";
          this.finishedAt = r.data.finished_at;
          if (wasRunning) {
            this.status = "done";
            // 从快照得知完成（done 事件已随断线被回收）—— 补完成通知，
            // 口径与 done handler 一致（含取消静默）。
            const failedCount = this.items.filter((i) => i.status === "failed").length;
            const cancelledCount = this.items.filter((i) => i.status === "cancelled").length;
            if (cancelledCount === 0) {
              useNotifications().push("批量生成完成", {
                body: `共 ${this.total} 篇 · 成功 ${this.items.filter((i) => i.status === "success").length}${failedCount ? ` · 失败 ${failedCount}` : ""}`,
                tone: failedCount ? "warn" : "success",
                category: "article_success",
              });
            }
          }
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
