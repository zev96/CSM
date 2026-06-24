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
import { useNotifications } from "@/composables/useNotifications";

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

/** 事实核对违规项（镜像后端 csm_core.factcheck.model.Violation）。
 * `number` = number 违规的归一值（万已展开），cert 为 null —— 审查面板放行
 * 万-值时回传它而非 parseFloat(value)。 */
export interface FactcheckViolation {
  kind: "number" | "cert";
  value: string;
  number: number | null;
  sentence: string;
  suggestion: string;
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
  // 当前 plan 对应的 template 详情（blocks 列表 + 各块 label）。
  // 组装 tab 的左侧 slot 列表渲染需要它 —— plan.results 里只有 block_id
  // 和 kind，section 的中文名（"开篇·痛点 / 选购维度 / 主推款"）住在
  // template.blocks[*].label / .text / .title 上。takeoff 时并行拉一次。
  template: Record<string, any> | null;
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
  // 事实核对门禁结果 —— 生成被 Plan 3 硬门禁拦下时 SSE `done` 事件带
  // `factcheck.{blocked, violations}`，存这里给审查面板（FactCheckPanel）。
  // 未拦 / 无门禁 → null。放行重核（resolveFactcheck）成功后清回 null。
  factcheck: { blocked: boolean; violations: FactcheckViolation[] } | null;
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
    template: null,
    error: null,
    lastRequest: null,
    titleCandidates: [],
    titleLoading: false,
    dedupReport: null,
    dedupLoading: false,
    keywordDensity: null,
    factcheck: null,
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
      this.template = null;
      this.factcheck = null;

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

      // 并行拉 template 详情，给组装 tab 的左侧 slot 列表用。失败不阻塞
      // SSE 流 —— 拿不到 template 时 UI 会 fallback 到 kind 名做 label。
      sidecar.client
        .get(`/api/templates/${encodeURIComponent(req.template_id)}`)
        .then((r) => { this.template = r.data; })
        .catch(() => { this.template = null; });

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
        // 后端在"组装 prompt"阶段完成后立刻推 plan + draft，让组装 / 初稿
        // 两个 tab 在 LLM 还在跑时就能显示真实内容（组装环节本来就不依赖
        // LLM，不应让 UI 等到最终 done 才一次性刷新）。
        assembly: (d: any) => {
          this.plan = d.plan ?? null;
          this.draftText = d.draft ?? "";
        },
        done: (d: any) => {
          this.documentPath = d.document ?? null;
          this.format = d.format ?? null;
          this.title = d.title ?? this.title;
          // 成稿（finalText）只在 LLM 整篇润色后才有值 —— draft_only 模式下
          // d.final_text 是 undefined，这里**不再回退到 draft**，否则会让
          // 成稿 tab 在用户还没点"整篇润色"前就显示初稿内容，破坏
          // 「初稿 → 用户检查 → 整篇润色 → 成稿」的两步语义。
          this.finalText = d.final_text ?? "";
          this.draftText = d.draft ?? "";
          this.plan = d.plan ?? null;
          // 生成被 Plan 3 事实核对硬门禁拦下时，done 事件带
          // factcheck.{blocked, violations} —— 存下来给审查面板；未拦 → null。
          this.factcheck =
            d.factcheck && d.factcheck.blocked
              ? { blocked: true, violations: d.factcheck.violations ?? [] }
              : null;
          this.stageIndex = STAGES.length;
          this.status = "done";
          useNotifications().push("文章生成完成", {
            body: this.title,
            tone: "success",
            category: "article_success",
          });
          this._teardown();
        },
        error: (d: any) => {
          if (d?.cancelled) {
            // 用户主动取消（/api/generate/{id}/cancel）—— 静默回 idle，不算失败
            this.status = "idle";
            this.error = null;
            this._teardown();
            return;
          }
          this.error = d.error ?? "unknown error";
          this.status = "error";
          useNotifications().push("文章生成失败", {
            body: this.error ?? "",
            tone: "error",
            category: "article_failure",
          });
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
    /** 请求后端协作式取消（POST /api/generate/{id}/cancel）。
     * 后端命中检查点后会推 error 事件（cancelled: true），由 SSE handler
     * 静默回 idle；这里不直接动 status，避免和事件流赛跑。
     * 端点对已结束/未知 job 返回 200 {ok:false}（无副作用）；真正的网络异常
     * 才落到 catch。 */
    async cancelJob(): Promise<void> {
      if (!this.jobId) {
        this.cancel();
        return;
      }
      const sidecar = useSidecar();
      try {
        await sidecar.client.post(`/api/generate/${this.jobId}/cancel`);
      } catch {
        /* 网络异常 —— 事件流自会收尾 */
      }
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
    /**
     * 把一个 slot（block）里所有 picks 整体重新随机。后端只提供单
     * pick 粒度的 reroll，所以这里串行调 N 次 —— numbered_list 这种
     * 3 picks 的 block 会有 3 次往返，但 UX 上"重随这个 slot"是一个
     * 原子操作，loading 在外层组件统一管。
     *
     * 找不到 block 或 block 没有可重随的 picks（文字块）时返回 false，
     * 调用方应当先用 isRerollableKind() 过滤按钮显示。
     */
    async rerollSlot(blockId: string): Promise<boolean> {
      if (!this.lastJobId || !this.plan) return false;
      // 在 plan.results 里递归找到对应 block，拿 picks 长度
      const findBlock = (rs: any[]): any | null => {
        for (const r of rs) {
          if (r.block_id === blockId) return r;
          if (Array.isArray(r.children) && r.children.length) {
            const found = findBlock(r.children);
            if (found) return found;
          }
        }
        return null;
      };
      const block = findBlock(this.plan.results ?? []);
      const pickCount = Array.isArray(block?.picks) ? block.picks.length : 0;
      if (pickCount === 0) return false;
      // 循环串行重随；只要任何一次成功就算成功。NoCandidates（409）的
      // 单 pick 失败不阻断后续 picks —— 池子枯竭是常态，能换几个换几个。
      let anyOk = false;
      let lastErr: Error | null = null;
      for (let i = 0; i < pickCount; i++) {
        try {
          const ok = await this.rerollPick(blockId, i);
          if (ok) anyOk = true;
        } catch (e: any) {
          lastErr = e instanceof Error ? e : new Error(String(e));
        }
      }
      if (!anyOk && lastErr) throw lastErr;
      return anyOk;
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
        // 历史索引镜像的 frontmatter 需要"哪个模板"——直接透传当前模板 id，
        // 后端 aggregation_service 读 `template` 字段渲染首页"最近文档"
        // 的「模板」列。
        template_name: this.lastRequest.template_id ?? null,
      });
      this.documentPath = resp.data.document ?? this.documentPath;
      this.format = resp.data.format ?? this.format;
      return resp.data;
    },
    /** 事实核对放行重核 + 导出（接 Plan 3 门禁）。released* 为用户勾选放行的项。
     * ok=true → 已导出，清 factcheck；ok=false → 更新剩余 violations。
     * 用 lastJobId（SSE 收尾会把 jobId 清空，lastJobId 仍在）。无任务 / 网络
     * 异常时返回 {ok:false, error}，从不抛。*/
    async resolveFactcheck(
      finalText: string, releasedNumbers: number[], releasedCerts: string[],
    ): Promise<{ ok: boolean; violations?: FactcheckViolation[]; error?: string }> {
      if (!this.lastJobId) return { ok: false, error: "无可核对的任务" };
      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post(`/api/generate/${this.lastJobId}/export`, {
          final_text: finalText,
          released_numbers: releasedNumbers,
          released_certs: releasedCerts,
        });
        if (resp.data.ok) {
          this.finalText = finalText;
          this.documentPath = resp.data.document ?? this.documentPath;
          this.format = resp.data.format ?? this.format;
          this.factcheck = null;
          return { ok: true };
        }
        this.factcheck = { blocked: true, violations: resp.data.violations ?? [] };
        return { ok: false, violations: resp.data.violations ?? [] };
      } catch (e: any) {
        return { ok: false, error: e?.response?.data?.detail ?? e?.message ?? String(e) };
      }
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
