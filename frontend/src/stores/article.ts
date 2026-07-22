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

// rerun 流的 teardown 句柄（独立于 generate/finalize 的 this.stop）。Pinia state
// 不宜放函数，用模块级变量存。
let _rerunStop: (() => void) | null = null;
function _teardownRerun() {
  if (_rerunStop) { try { _rerunStop(); } catch { /* ignore */ } _rerunStop = null; }
}

/** 每次请求的选材意图（人群/卖点/语调），镜像后端 csm_core.angle.model.Angle。
 * 全可空：audience/tone 为 null、sellpoints 为 [] ⇔「不传角度」= 今天行为。 */
export interface Angle {
  audience: string | null;
  sellpoints: string[];
  tone: string | null;
}

export interface GenerateRequest {
  keyword: string;
  template_id: string;
  skill_id?: string | null;
  seed?: number;
  draft_only?: boolean;
  core_keyword?: string | null;
  provider?: string | null;
  model?: string | null;
  // Phase 2a 角度组装 —— 标题领衔 + 角度（人群/卖点/语调）。不传 = 今天行为。
  title?: string | null;
  angle?: Angle | null;
  // Phase 2b skill 链多-pass —— 按 role 顺序的 skill id 列表（人设→去AI味→平台）。
  // 不传 / 空 = 退回单 skill_id（零回归）。
  skill_chain?: string[] | null;
  // Phase 4+ 成文契约档单次覆盖。不传 = 用全局 cfg.contract.mode。
  contract_mode?: "conservative" | "aggressive";
  // 结构版本指定 {版本组 id: 版本名}。不传 = 按种子随机抽。
  // 「重新随机」会带上当前版本以锁住结构。
  version_overrides?: Record<string, string> | null;
}

/** 横评（多型号对比）提交意图 —— POST /api/generate/comparison 的 body 形。
 * 一次横评产出**一篇**对比文章（非多候选），后端确定性从品牌记忆拼骨架，
 * 前端复用单篇 store 流（_subscribe / draftText / plan=null / finalize）。 */
export interface ComparisonRequest {
  models: string[];
  keyword?: string;
  title?: string | null;
  tone?: string | null;
  skill_chain?: string[] | null;
  contract_mode?: "conservative" | "aggressive";
}

/** 链上单 pass 的预览数据（镜像后端 chain_service.ChainPass.to_dict）。
 * SSE `pass` 事件逐个推；`done` 事件带完整 `passes` 数组覆盖。 */
export interface ChainPass {
  index: number;
  role: string;
  skill_id: string | null;
  skill_name: string;
  output: string;
  input_chars: number;
  output_chars: number;
  // 链成本（Task A/B）—— 每 pass 的 token 计量（本地 CJK 估算，非真实分词）。
  // 可选：后端 to_dict 必带，但前端只消费 cost 汇总（ChainCost），per-pass token
  // 暂未用于渲染；设可选让 mock/测试 fixture 不必逐个填（将来要展示再用）。
  input_tokens?: number;
  output_tokens?: number;
}

/** 链成本摘要（镜像后端 pricing.chain_cost）。cost=null = 未知 model 无价。 */
export interface ChainCost {
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
  currency: string;
}

/** 角度受控词表（GET /api/angle/taxonomy 的响应，picker 数据源）。
 * 后端单一来源，前端只读缓存。 */
export interface AngleTaxonomy {
  tones: Array<{ key: string; hint: string }>;
  dimensions: Array<{ key: string; label: string }>;
  audiences: string[];
  presets: Array<{
    name: string;
    template_id: string | null;
    audience: string | null;
    sellpoints: string[];
    tone: string | null;
  }>;
}

export type LintCategory = "meta_speak" | "absolute" | "traffic" | "emoji" | "dash" | "quote";
export interface LintHit {
  category: LintCategory;
  text: string; start: number; end: number;
  sentence: string; fixable: boolean; suggestion: string;
}
const lintKey = (h: LintHit) => `${h.category}:${h.start}:${h.text}`;

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

/** 完整性缺失项（镜像 csm_core.factcheck.completeness.MissingFact）。 */
export interface MissingFact {
  kind: "number" | "cert";
  token: string;
  value: number | null;
  sentence: string;
}
export interface ScorePart { key: string; label: string; points: number; detail: string }
export interface ScoreReport { total: number; parts: ScorePart[] }

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
  // 角度受控词表 —— GET /api/angle/taxonomy 拉一次后缓存（picker 复用）。
  angleTaxonomy: AngleTaxonomy | null;
  // Phase 2b skill 链逐 pass 输出 —— SSE `pass` 事件逐个 push，`done`
  // 带完整 `passes` 时整体覆盖。submit 时清空。无链（单 skill 旧路径）→ [].
  passes: ChainPass[];
  // 链成本摘要 —— SSE `done` / rerun 响应带 `cost` 时存这里，驱动成稿区
  // 「≈X tokens · ≈¥Y」成本行。无 cost（旧路径 / 未知 model 无价）→ null。
  // submit / finalize 起新链时清回 null。
  cost: ChainCost | null;
  // 整篇润色（finalize）SSE 进行中为 true，驱动 ArticleView 进度卡显示
  // 「润色中」而非「组装中」。POST 失败 / done / error / cancel 都清回 false。
  // 起飞（submit）不算润色，所以 submit 的 reset 块里也清成 false。
  isFinalizing: boolean;
  // 正在重跑的 pass index —— 流式重跑（rerunPass）进行中存该 pass index，
  // 驱动 pass 卡的 loading / 取消按钮 + 互斥（同时只跑一个）。POST 失败 /
  // SSE done / error 都清回 null。从 ArticleView 本地 ref 上提到 store，
  // 因为流式下 store rerunPass 早返回（订阅后即 await 结束），本地 finally
  // 会过早清掉 loading 态。
  rerunningIndex: number | null;
  // 禁区 lint 门禁 —— 成稿出炉自动扫，结果存这里（{hits, fixed_text}）。
  // null=未扫 / fail-open。hits 命中放行后存 key 串到 lintReleased。
  lint: { hits: LintHit[]; fixed_text: string } | null;
  lintReleased: string[];
  // Phase 4+: 激进契约完整性反向核对（软警告）。null=保守/未核/fail-open。
  completeness: { checked: boolean; missing: MissingFact[] } | null;
  // Phase 4+: 成稿确定性评分（禁区+AI味+核对，0-100）。null=未评/scoring 关/fail-open。
  score: ScoreReport | null;
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
    angleTaxonomy: null,
    passes: [],
    cost: null,
    isFinalizing: false,
    rerunningIndex: null,
    lint: null,
    lintReleased: [],
    completeness: null,
    score: null,
  }),
  getters: {
    progress(state): number {
      if (state.status === "done") return 1;
      if (state.stageIndex < 0) return 0;
      return Math.min(1, (state.stageIndex + 1) / STAGES.length);
    },
    stages: () => STAGES,
    isRunning: (state) => state.status === "running",
    // 链成本 —— 调用次数 = pass 数；总字数 = Σ 每 pass 输出字数。
    callCount: (state) => state.passes.length,
    totalChars: (state) =>
      state.passes.reduce((sum, p) => sum + (p.output_chars ?? 0), 0),
    // token 合计 —— cost 摘要里的 input+output（无 cost → 0）。
    tokenTotal: (state) =>
      state.cost ? state.cost.input_tokens + state.cost.output_tokens : 0,
    // 禁区 lint 门禁 —— true=有未放行命中，软拦导出。
    lintBlocking: (state) =>
      !!state.lint?.hits && state.lint.hits.some((h) => !state.lintReleased.includes(lintKey(h))),
    lintUnresolved: (state) =>
      state.lint?.hits ? state.lint.hits.filter((h) => !state.lintReleased.includes(lintKey(h))).length : 0,
  },
  actions: {
    async runLint(text: string): Promise<void> {
      if (!text.trim()) { this.lint = null; this.lintReleased = []; return; }
      try {
        const r = await useSidecar().client.post("/api/lint", { text });
        // 只接受形如 {hits[], fixed_text} 的 lint 报告 —— 非该形状（端点异常返回、
        // 或测试里通用 mock 串味）一律视为无结果（fail-open），避免毒化 lint 让
        // lintBlocking 求值时 state.lint.hits 为 undefined 崩。snake_case 零映射。
        const d = r.data;
        this.lint = d && Array.isArray(d.hits)
          ? { hits: d.hits, fixed_text: typeof d.fixed_text === "string" ? d.fixed_text : "" }
          : null;
        this.lintReleased = [];
      } catch {
        this.lint = null;            // fail-open：lint 基建故障不拦导出
      }
    },
    async autofixLint(): Promise<void> {
      if (!this.lint) return;
      // 应用上一次扫描的 fixed_text —— 若用户在上次 lint 之后又手改了成稿，
      // 那些改动会被覆盖。LintPanel 的「重新检查」按当前成稿重扫再修。
      this.finalText = this.lint.fixed_text;
      return this.runLint(this.finalText);
    },
    toggleLintRelease(h: LintHit): void {
      const k = lintKey(h);
      const i = this.lintReleased.indexOf(k);
      if (i >= 0) this.lintReleased.splice(i, 1);
      else this.lintReleased.push(k);
    },
    async runScore(text: string): Promise<void> {
      if (!text.trim()) { this.score = null; return; }
      try {
        const r = await useSidecar().client.post("/api/score", {
          text,
          factcheck_violations: this.factcheck?.violations.length ?? 0,
          completeness_missing: this.completeness?.missing.length ?? 0,
        });
        const d = r.data;
        // scoring 关（total:null）或形状不对 → null（fail-open）
        this.score = d && typeof d.total === "number" && Array.isArray(d.parts)
          ? { total: d.total, parts: d.parts }
          : null;
      } catch {
        this.score = null;
      }
    },
    async submit(req: GenerateRequest): Promise<void> {
      this._teardown();
      _teardownRerun();          // 起新生成 —— 放弃在跑的 rerun 流
      this.rerunningIndex = null;
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
      this.passes = [];
      this.cost = null; // 起新链 —— 清掉上一轮成本摘要
      this.isFinalizing = false; // 起飞不是润色 —— 清掉残留的润色标志
      this.lint = null; this.lintReleased = []; // 起新生成 —— 清掉上轮 lint
      this.completeness = null; this.score = null; // 起新生成 —— 清掉上轮完整性/评分

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

      this._subscribe(this.jobId!);
    },
    /** 横评提交 —— 镜像 submit 的 reset + POST /api/generate/comparison + 复用
     * _subscribe（横评是一篇文章，事件 shape 与单篇完全一致：assembly plan=null +
     * draft 骨架、done、error）。lastRequest 存成 GenerateRequest 形，让既有
     * finalize() 从 lastRequest 取 keyword/title/skill_chain 拼 body 时无需改动；
     * 横评专属的 models/tone 由后端横评缓存兜住（finalize 命中缓存走 models 分支）。 */
    async submitComparison(req: ComparisonRequest): Promise<void> {
      this._teardown();
      _teardownRerun();
      this.rerunningIndex = null;
      // finalize() 从 lastRequest 取 keyword/title/skill_chain 拼 finalize body；
      // 横评专属的 models/tone 存后端缓存，前端 lastRequest 只需兼容形。
      this.lastRequest = {
        keyword: req.keyword ?? "型号对比",
        template_id: "__comparison__",
        title: req.title ?? null,
        skill_chain: req.skill_chain ?? null,
        contract_mode: req.contract_mode,
      } as GenerateRequest;
      this.status = "running";
      this.error = null;
      this.currentStage = null;
      this.stageIndex = -1;
      this.finalText = "";
      this.draftText = "";
      this.documentPath = null;
      this.title = req.keyword ?? "型号对比";
      this.plan = null;
      this.template = null;
      this.factcheck = null;
      this.passes = [];
      this.cost = null;
      this.isFinalizing = false;
      this.lint = null; this.lintReleased = [];
      this.completeness = null; this.score = null;

      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post("/api/generate/comparison", {
          models: req.models,
          keyword: req.keyword ?? "",
          title: req.title ?? null,
          tone: req.tone ?? null,
          skill_chain: req.skill_chain ?? null,
          ...(req.contract_mode ? { contract_mode: req.contract_mode } : {}),
          draft_only: true,
        });
        this.jobId = resp.data.job_id;
        this.lastJobId = resp.data.job_id;
      } catch (e: any) {
        this.status = "error";
        this.error = e?.response?.data?.detail ?? e?.message ?? String(e);
        return;
      }
      this._subscribe(this.jobId!);
    },
    /** 共享 SSE 订阅 —— submit（起飞）和 finalize（整篇润色）都复用同一套
     * stage/assembly/pass/done/error handler。订阅 `/api/events/{jobId}` 并把
     * teardown 句柄存进 this.stop（_teardown 会关）。两条路径走同一份事件
     * 解析，所以链状态 / factcheck / 重跑此 pass 在起飞和润色下行为一致。 */
    _subscribe(jobId: string) {
      this.stop = subscribe(`/api/events/${jobId}`, {
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
        // Phase 2b skill 链 —— 每跑完一个 pass 后端推一条，逐个 push 让
        // 成稿区可以增量显示链进度。done 会带完整 passes 再覆盖一次。
        pass: (d: any) => {
          this.passes.push(d as ChainPass);
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
          // 链模式下 done 带完整 passes（权威全量）—— 覆盖 SSE 增量推送的
          // 部分列表。单 skill 旧路径无 passes 字段，保持 [] 不动（零回归）。
          if (Array.isArray(d.passes)) this.passes = d.passes as ChainPass[];
          // 链成本摘要 —— 后端在 done 带 cost（含未知 model 的 cost=null）。
          // 旧路径 / 无链不带 cost 字段，保持上一轮值不动（submit 已清成 null）。
          if (d.cost) this.cost = d.cost as ChainCost;
          // 生成被 Plan 3 事实核对硬门禁拦下时，done 事件带
          // factcheck.{blocked, violations} —— 存下来给审查面板；未拦 → null。
          this.factcheck =
            d.factcheck && d.factcheck.blocked
              ? { blocked: true, violations: d.factcheck.violations ?? [] }
              : null;
          // Phase 4+: 激进契约的完整性软警告（保守/未核 → null）。
          this.completeness =
            d.completeness && d.completeness.checked
              ? { checked: true, missing: d.completeness.missing ?? [] }
              : null;
          this.stageIndex = STAGES.length;
          this.status = "done";
          useNotifications().push("文章生成完成", {
            body: this.title,
            tone: "success",
            category: "article_success",
          });
          // 整篇润色成稿出炉 → 自动跑禁区 lint + 评分（draft_only 起飞 final_text 空，不触发）。
          if (this.finalText.trim()) {
            void this.runLint(this.finalText);
            void this.runScore(this.finalText);
          }
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
    /** 拉角度受控词表（picker 数据源），缓存一次。失败静默 —— picker
     * 会显示空选项，用户仍可手填标题。重复调用直接返回缓存。 */
    async fetchAngleTaxonomy(): Promise<void> {
      if (this.angleTaxonomy) return;
      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.get("/api/angle/taxonomy");
        this.angleTaxonomy = resp.data as AngleTaxonomy;
      } catch {
        /* 静默 —— picker 走空词表兜底 */
      }
    },
    /** Re-run the last request — useful for "重新随机" buttons.
     *
     * 默认**锁住当前结构版本**：把这一篇抽中的 version_choices 原样传回去，
     * 只换素材不换结构。否则 2 个版本下用户点一次「重新随机」有一半概率
     * 整篇换成另一套结构——他想要的通常只是换个说法。
     * 换版本走 rerunWithVersion()。 */
    async rerun(versionOverrides?: Record<string, string> | null): Promise<void> {
      if (!this.lastRequest) return;
      // Bump seed by 1 so the assembler re-samples instead of giving the
      // exact same draft back.
      const locked =
        versionOverrides === null
          ? undefined
          : (versionOverrides ?? this.plan?.version_choices ?? undefined);
      const next: GenerateRequest = {
        ...this.lastRequest,
        seed: (this.lastRequest.seed ?? 0) + 1,
      };
      if (locked && Object.keys(locked).length) {
        next.version_overrides = locked;
      } else {
        // 必须显式擦除：lastRequest 里存着上一次重随写进去的锁，只是「不再
        // 添加」的话它会被展开带出去，「换个版本」就永远换不掉了。
        delete next.version_overrides;
      }
      await this.submit(next);
    },
    /** 显式换结构版本。传 null = 放开锁、让种子重新抽。 */
    async rerunWithVersion(groupId: string, option: string | null): Promise<void> {
      if (option === null) return this.rerun(null);
      const current = { ...(this.plan?.version_choices ?? {}) };
      current[groupId] = option;
      await this.rerun(current);
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
    /** 整篇润色 = 在用户审过的初稿（draftText）上跑「注入+角度+链」成稿。
     * 复用 takeoff 的 lastJobId 重开同 id 的 SSE 流（链状态/factcheck/重跑此
     * pass 自动同源）。轻 reset：保留 draftText（链输入）/plan/lastRequest。
     * 守卫：未起飞（无 lastJobId/lastRequest）或初稿为空 → 直接 return（demo
     * 模式由 ArticleView 处理，不调本函数）。从不抛。 */
    async finalize(): Promise<void> {
      if (!this.lastJobId || !this.lastRequest || !this.draftText.trim()) return;
      this._teardown();
      _teardownRerun();          // 进入整篇润色 —— 放弃在跑的 rerun 流
      this.rerunningIndex = null;
      this.isFinalizing = true; // 进入润色 —— 进度卡据此显示「润色中」
      this.status = "running";
      this.error = null;
      this.currentStage = null;
      this.stageIndex = -1;

      const sidecar = useSidecar();
      const req = this.lastRequest;
      try {
        const resp = await sidecar.client.post(
          `/api/generate/${this.lastJobId}/finalize`,
          {
            draft: this.draftText,
            keyword: req.keyword,
            title: req.title ?? null,
            angle: req.angle ?? null,
            skill_id: req.skill_id ?? null,
            skill_chain: req.skill_chain ?? null,
            provider: req.provider ?? null,
            model: req.model ?? null,
            // takeoff 是 draft_only（不跑 LLM），真正的润色在这一步 —— 必须带上
            // per-article 契约档覆盖，否则后端回退全局、用户选的激进/保守被忽略。
            contract_mode: req.contract_mode ?? null,
          },
        );
        this.jobId = resp.data.job_id;
      } catch (e: any) {
        // POST 失败（如 404 plan cache miss）：保留旧成稿/链预览不清空，
        // 只回错误态。isFinalizing 复位。
        this.isFinalizing = false;
        this.status = "error";
        this.error = e?.response?.data?.detail ?? e?.message ?? String(e);
        return;
      }
      // POST 成功才清旧成稿，准备接收新链输出。
      this.finalText = "";
      this.passes = [];
      this.factcheck = null;
      this.cost = null; // 起新链 —— 清掉上一轮成本摘要
      this.lint = null; this.lintReleased = []; // 起新润色 —— 清掉上轮 lint
      this.completeness = null; this.score = null; // 起新润色 —— 清掉上轮完整性/评分
      this._subscribe(this.jobId!);
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
        // Phase 4+ 反馈采集（§6）：关联 job + 质检卡已算的分数/未决禁区。
        // 后端 record_export 纯落库、不回传、fail-open。
        job_id: this.lastJobId ?? null,
        score: this.score?.total ?? null,
        score_json: this.score ? JSON.stringify(this.score) : null,
        lint_unresolved: this.lintUnresolved ?? 0,
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
    /** 重跑链上第 `index` 个 pass —— 异步流式（POST→202→订阅 SSE）。后端从该
     * pass 级联其后所有 pass，逐 pass 经 SSE `pass` 实时替换 passes[index]，
     * `done` 覆盖全量 + cost。轻量订阅（不碰 status/通知/tab）。从不抛。 */
    async rerunPass(index: number): Promise<void> {
      if (!this.lastJobId) return;
      _teardownRerun();
      this.rerunningIndex = index;
      const sidecar = useSidecar();
      let jobId: string;
      try {
        const resp = await sidecar.client.post("/api/chain/rerun", {
          job_id: this.lastJobId, pass_index: index,
        });
        jobId = resp.data.job_id;
      } catch {
        this.rerunningIndex = null;  // 404/400/网络 静默（同今天从不抛）
        return;
      }
      _rerunStop = subscribe(`/api/events/${jobId}`, {
        pass: (d: any) => { this.passes[d.index] = d as ChainPass; },
        done: (d: any) => {
          if (Array.isArray(d.passes)) this.passes = d.passes as ChainPass[];
          if (d.cost) this.cost = d.cost as ChainCost;
          if (typeof d.final_text === "string") this.finalText = d.final_text;
          this.rerunningIndex = null;
          _teardownRerun();
          // 重跑改了成稿要重扫禁区 lint + 评分。
          if (this.finalText.trim()) {
            void this.runLint(this.finalText);
            void this.runScore(this.finalText);
          }
        },
        error: () => { this.rerunningIndex = null; _teardownRerun(); },  // 含 cancelled，静默
      });
    },
    /** 取消进行中的重跑（复用 generate 的协作式取消端点，对 _live 里的同 job 生效）。
     * 从不抛；真正收尾由 SSE error(cancelled) → 上面 error handler 清 rerunningIndex。 */
    async cancelRerun(): Promise<void> {
      if (this.lastJobId == null || this.rerunningIndex == null) return;
      const sidecar = useSidecar();
      try { await sidecar.client.post(`/api/generate/${this.lastJobId}/cancel`); }
      catch { /* 网络异常 —— 事件流自会收尾 */ }
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
      // 任何收尾（done / error / cancel）都清润色标志 —— finalize 的
      // SSE done/error handler 调 _teardown，故润色结束时 isFinalizing 自动归 false。
      this.isFinalizing = false;
    },
  },
});
