# Phase 4+ 一揽子升级（设计稿）

- 日期：2026-07-01
- 范围：路线图 §6「后续升级（Phase 4+）」中的 4 项 + 各期 spec「留给后续」的 3 项，共 **7 项实现** + **1 项 design-only**（一键平台分发）。
- 用户拍板（2026-07-01）：批量选优默认 1 篇只评分（候选 opt-in 2-3）；LLM 契约默认保守、可全局/单次切激进；反馈学习先只记录、排序开关默认关；横评入口 = 创作台「横评」模式。
- 原则沿用总纲：接地优先、复用现有抽象、vault 是事实中心、**全部新能力 opt-in 或软提醒、零回归**。

## 交付切分（4 个 PR，顺序递进）

| PR | 分支 | 内容 | 风险 |
|---|---|---|---|
| A | `claude/phase4-vault-perf` | §1 增量索引 + §2 长文分块 | 低（纯基建，行为不变） |
| B | `claude/phase4-contract-scoring` | §3 激进契约+完整性 + §4 评分+批量升级 | 中（批量链路升级，全 opt-in） |
| C | `claude/phase4-comparison` | §5 横评 | 中（新生成模式，独立旁路） |
| D | `claude/phase4-feedback-facts` | §6 反馈闭环 + §7 事实传导 | 低-中（新持久层，静默采集） |

本设计稿随 PR-A 提交；后续 PR 引用本稿。

---

## 1. 增量/缓存 vault 索引

### 1.1 现状与问题

- `scan_vault(root)`（scanner.py:56）每次 `rglob("*.md")` 全量解析；库 230 篇尚可，扩库后每次生成都全量重扫（roadmap §4.4 已点名）。
- 生成链路两处**绕过** `vault_service` 缓存直调 `scan_vault`：generate_service.py:186（takeoff）、:325（finalize）；atomize_service.py:57 每次拆条也全量 `scan()`。
- `vault_service` 现状 = 模块级全局 `_index` + `scan()/cached()/invalidate()` 三函数，无失效判定。

### 1.2 方案

新增 `csm_core/vault/index_cache.py`：

```python
@dataclass
class _Entry:
    mtime_ns: int
    size: int
    note: ParsedNote
    warnings: list[str]          # 该文件的解析警告（缓存后可重聚合）

class IncrementalIndexer:
    def __init__(self) -> None:
        self._root: Path | None = None
        self._files: dict[Path, _Entry] = {}

    def refresh(self, root: Path) -> VaultIndex:
        """stat 巡走全库：新增/变更(mtime_ns 或 size 变)重解析，删除剔除，
        其余复用缓存 ParsedNote。root 变更 → 整体重建。
        返回按 path 排序重建的 VaultIndex（与 scan_vault 输出顺序一致）。"""

    def reset(self) -> None: ...
```

- 巡走用 `(st_mtime_ns, st_size)` 双键判变——共享盘 mtime 粒度粗时 size 兜底。
- `scan_vault` 保持纯全量函数不动（csm_core 公共 API 不破坏）；从 scanner 抽出 `parse_one(path) -> tuple[ParsedNote | None, list[str]]` 供两者共用（scan_vault 行为字节级不变）。
- 警告语义：`VaultIndex.warnings` = 各文件缓存警告按 path 序重聚合，与全量扫结果一致。

`vault_service` 改造（sidecar）：

```python
def get(root: Path) -> VaultIndex:      # 新：统一入口（增量快路径）
    if not load().vault_incremental:    # 配置关 → 退回全量
        return scan(root)
    try:
        return _indexer.refresh(root)
    except Exception:                    # 任何异常 fail-open 回全量
        logger.warning(...); return scan(root)

def scan(root) -> VaultIndex            # 语义改为：强制全量（reset + refresh）
def cached() -> VaultIndex | None       # 不变
def invalidate() -> None                # 语义 = _indexer.reset() + _index=None
```

调用点切换：

| 调用点 | 现状 | 改为 |
|---|---|---|
| generate_service.py:186（takeoff） | `scan_vault(vault_root)` | `vault_service.get(vault_root)` |
| generate_service.py:325（finalize） | `scan_vault(vault_root)` | `vault_service.get(vault_root)` |
| atomize_service.py:57 | `vault_service.scan(root)` | `vault_service.get(root)` |
| assembler_service.py:87-89 兜底 | `cached() or scan()` | `cached() or get()` |
| vault_writer_service.py:41 | `scan(_root())` | `get(_root())` |
| lifespan.py:249 启动扫 | `scan(root)` | `get(root)`（首扫等价全量） |
| routes/vault.py:43 `POST /api/vault/scan` | `scan(root)` | 不变（「重建索引」= 强制全量语义） |

- `vault_writer_service` 写盘后的 `invalidate()` **保留**（写后强制全量，安全带；写入低频，代价可接受）。
- csm_core 内部直调（title/generator.py:346、pipeline.py:53）不在 sidecar 进程内共享缓存，**本期不动**（CLI 旁路，低频）。

配置：`AppConfig.vault_incremental: bool = True`（平铺字段，随 export_format 风格）。

### 1.3 测试

- tmp_path 合成 vault：首扫全解析 → 触改 1 文件（重写内容改 mtime）→ 仅该文件重解析（monkeypatch parse_one 计数）；新增/删除文件同断言；root 切换整体重建。
- 一致性：任意操作序列后 `refresh()` 输出与 `scan_vault()` 全量输出**逐字段相等**（notes 顺序、by_id、warnings）。
- 配置关/异常 fail-open 回全量。
- 真实库只读回归 `@skipif`：增量首扫 == 全量扫。

---

## 2. AI 拆条长文分块

### 2.1 现状

atomize_service.py:54 `_MAX_INPUT = 8000` 硬截断 + warning（v1 明确「长文分块留后续」）。

### 2.2 方案

**切分（csm_core 纯函数）** `csm_core/vault/chunking.py`：

```python
class ChunkResult(BaseModel):
    chunks: list[str]
    truncated: bool          # 超 cap 截尾
    dropped_chars: int

def split_for_atomize(text: str, *, max_chars: int = 8000, cap: int = 8) -> ChunkResult
```

- 切点优先级：markdown 标题行（`^#{1,6} `）> 空行段界 > 句界（`。！？!?\n`）；**绝不切断句子**；贪心装填至 `max_chars`。
- 超过 `cap` 块（默认 6.4 万字）截尾并置 `truncated=True`。

**端点（无状态）**：`POST /api/vault/atomize/split {text}` → `ChunkResult`。现有 `POST /api/vault/atomize` **零改动**（单块 ≤8000 由构造保证；服务端截断保留作直调防线）。

**前端驱动逐块循环**（materials store + AtomizePanel）：

- `atomizeText` 升级：文本 >8000 → 先 split → 顺序逐块调 `/api/vault/atomize` → 合并 atoms；store 新状态 `chunkProgress: {current, total} | null`；块间可取消（`chunkCancel` 标志）。
- 面板显示「分块 i/N 拆条中…」；`truncated=True` → warn toast 报截尾字数。
- 合并去重：key = `rel_folder + 归一化正文前 80 字`（去空白标点）；重复丢弃并计数入 toast。

*舍弃的替代*：服务端单调用内循环——无进度、无取消、长文撞 HTTP 超时。

### 2.3 测试

- chunking 纯函数：句界不破断言（任意 chunk 结尾 ∈ 句界/标题界/文末）、贪心装填、cap 截尾、空文/短文单块、幂等（join(chunks) + dropped == 原文）。
- split 路由 3 测（正常/空 422 或空报告/超长截尾）。
- 前端 store：多块顺序调用、进度状态、取消中断、去重合并（vitest，mock client 逐块返回）。

---

## 3. 激进版 LLM 契约 + 完整性警告

### 3.1 现状

- 保守契约钉死在 prompts.py:42-53：「保留所有信息点…不删减关键信息点」——Phase 2a 拍板保守版，激进版因「漏型号参数静默风险」留后续。
- 本期把「静默」风险显性化：**允许删减 + 完整性反向核对**。

### 3.2 方案

**配置与请求**：

```python
class ContractConfig(BaseModel):
    mode: Literal["conservative", "aggressive"] = "conservative"
# AppConfig.contract: ContractConfig = Field(default_factory=ContractConfig)
```

- `GenerateBody.contract_mode: Literal["conservative","aggressive"] | None = None`（None=用全局配置）；BatchRequest 同字段；横评请求同字段。
- 前端：设置卡「生成契约」（默认档下拉）+ Hero 高级区单次覆盖开关（默认跟随全局）。

**prompt 措辞**（PromptInputs 加 `contract_mode: str = "conservative"`，build_prompt 分支）：

- 激进 + 标题/角度：「请按上面【写作角度】组织成文：可取舍删减次要或重复的信息点、让篇幅更精炼；但主推型号的参数、认证与标题承诺的卖点必须完整保留；不新增虚构事实，不改动任何数字、单位、认证。」
- 激进无角度：「请按**精炼模式**重写：可删减次要或重复内容、合并冗余段落；但所有型号参数、认证与核心卖点必须完整保留；不新增虚构事实，不改动任何数字、单位、认证。」
- 保守分支措辞**逐字节不动**（零回归）。`build_refine_prompt`（链 step1+）不动——已是保事实措辞。

**完整性核对** `csm_core/factcheck/completeness.py`：

```python
class MissingFact(BaseModel):
    kind: Literal["number", "cert"]
    token: str               # 初稿原文 token，如 "250AW"
    value: float | None      # 归一值（万展开），cert=None
    sentence: str            # 初稿所在句（定位）

class CompletenessReport(BaseModel):
    checked: bool            # False = 保守模式/无主推 scope，未核
    missing: list[MissingFact] = []

def check_completeness(draft: str, final_text: str, scopes: list[ModelScope]) -> CompletenessReport
```

- required = **初稿里出现过的主推（role=主推）型号 spec 数字/认证**：`extract_number_mentions(draft)` ∩ 主推 specs numbers 并集（万-展开对称，复用 whitelist.normalize_numbers 语义）；certs 同理。
- presence：`extract_number_mentions(final_text)` 归一集合 + `extract_certs(final_text)`。
- 竞品参数被删**不算缺失**（激进契约允许取舍竞品内容）。

**接线**：`finalize_draft` 链跑完后，`contract_mode == "aggressive"` 时核对，报告挂进 `bus.finish(..., completeness={"checked":…, "missing":[…]})`。**软提醒不拦导出**（编造方向已有 factcheck 硬门禁；缺失方向影响营销力非合规）。

**前端**：article store 加 `completeness` state（done 事件收、submit/finalize reset）；质检卡第 8 项「完整性」（保守/未核显「—」，激进 0 缺失 ok、有缺失 warn + 数量）；点开小面板（复用 Dialog）列缺失 token + 初稿句，提示「可回成稿手动补回或重新润色」。

### 3.3 测试

- prompts：保守分支快照钉死（字节级）；激进两分支措辞断言。
- completeness：命中/漏检/万对称/竞品删除不报/无主推 scope 不核/certs 各 1-2 测。
- finalize 接线：激进 mock 链输出删参数 → done 带 missing；保守 → checked=False。
- 前端 store + 质检卡 render 测。

---

## 4. 批量出稿 + 自动评分选优

### 4.1 评分引擎（确定性，零 LLM 成本）

`csm_core/scoring/`：

```python
# model.py
class ScorePart(BaseModel):
    key: str; label: str; points: float   # 负值=扣分
    detail: str
class ScoreReport(BaseModel):
    total: float                           # 0-100
    parts: list[ScorePart]

# ai_flavor.py — AI 味启发式（全确定性正则/词表）
# score.py
class ScoringConfig(BaseModel):            # 挂 AppConfig.scoring
    enabled: bool = True
    extra_ai_words: list[str] = Field(default_factory=list)

def score_article(text: str, *, lint_report: LintReport,
                  factcheck_violations: int = 0,
                  completeness_missing: int = 0,
                  config: ScoringConfig | None = None) -> ScoreReport
```

扣分项（v1，各有单项上限防过罚）：

| key | 信号 | 依据 |
|---|---|---|
| lint | 禁区命中按类加权（判断类 4 分/处、机械类 2 分/处，上限 30） | 复用 LintReport |
| ai_connectives | 套话连接词密度（首先/其次/再者/综上所述/总的来说/值得一提的是/不难发现/众所周知 等 ~20 词，每千字加权，上限 15） | humanizer 特征 |
| ai_triplet | 「首先…其次…最后」三段式命中（8 分/次，上限 16） | 同上 |
| ai_parallel | 否定排比「不是…而是…」「不仅…更…」密度（上限 10） | 同上 |
| ai_summary | 段首「总之/综上」万能总结句（4 分/段，上限 12） | 同上 |
| monotony | 句长方差过低 + 段落长度过均匀（上限 12） | 同质化信号 |
| factcheck | 违规数 ×6（上限 18） | 传入 |
| completeness | 缺失数 ×4（上限 12） | 传入 |

端点：`POST /api/score {text, factcheck_violations?, completeness_missing?}` → ScoreReport（服务端自跑 lint，config 隔离同 lint_service）。

**单篇接线**：article store 在 runLint 完成后自动 `runScore`（fail-open null）；质检卡加「综合评分」项（≥80 ok / 60-79 warn / <60 alert，tooltip 列扣分明细 top3）。

### 4.2 批量链路升级（历史欠账 + 选优）

现状 batch_service.py:237-285 每关键词 = `assemble_plan → compose_draft → build_prompt(单 skill) → complete → export`——**Phase 1 之前的老路径**（无注入/无链/无核对）。评分选优要有意义必须先升级链路：

每 item × 候选 k 的新流水线（复用既有件，不走 bus/SSE 的 finalize_draft 包装）：

```
plan_k   = assemble_plan(..., seed = seed + k*1000)
draft_k  = compose_draft(plan_k)
scopes   = resolve_scopes(...)                    # cfg.brand_memory.inject 开时
facts    = render_brand_facts(scopes)
chain    = run_chain(job_id=f"{batch_job}:{idx}:{k}", steps, draft_k, ...,
                     brand_facts=facts, contract_mode=…)   # steps 来自 skill_chain
fc_n     = len(check_facts(final, build_whitelist(scopes, [draft_k])).violations)  # 计数不拦
comp_n   = len(check_completeness(...).missing)   # 激进时
lint     = build_report(final, rules)
score_k  = score_article(final, lint_report=lint, factcheck_violations=fc_n,
                         completeness_missing=comp_n)
```

- 取最高分候选导出；落选稿存 `batch-{id}/candidates/{index}-{keyword}-c{k}.md` 备查。
- `BatchRequest` 新增：`candidates: int = 1`（钳 1-3）、`skill_chain: list[str] | None = None`（None 退化 `[skill_id]` 单步链——**与今天单 skill 行为等价**）、`contract_mode`。
- `item_finished` 事件增：`score: float`、`score_parts: [...]`（top3）、`candidate_scores: [float]`、`factcheck_violations: int`。`done` 增 `total_cost`（逐 item 链成本求和，沿用 pricing 估算）。
- 兼容：`candidates=1` + 单 skill + inject 关 = 今天成本结构（1 次 LLM/篇）+ 免费评分。

**前端 BatchView**：候选数 FormSelect（1/2/3，默认 1，旁注「×N 费用」）、结果表加「评分」列（<60 标红 Pill）、行展开显示扣分 top3 与候选分。

### 4.3 测试

- scoring 纯函数：每信号 1-2 测（干净人稿 ≥80 fixture、AI 味稿 <70 fixture、单项上限、extra_ai_words 生效）。
- batch：mock LLM 下 candidates=2 → 2 次链、导出高分者、落选稿落 candidates/；candidates=1 单链零回归（导出路径/事件 shape 兼容旧前端字段）；inject 开注入 facts；factcheck 违规计数不拦。
- 路由/前端 store/View 各最小集。

---

## 5. 横评自动化

### 5.1 方案

**入口**：创作台 Hero 加「常规 | 横评」segmented 切换。横评模式表单：型号多选 2-4（数据源 `GET /api/brand-memory` 列表，主推/竞品分组）、可选 标题/语调/skill 链/契约档；**不选模板**（横评有自己的确定性骨架）。takeoff → router query `{mode:"comparison", models:"A,B,C", tone?, title?, skill_chain?}` → ArticleView init 分支调 `article.submitComparison(...)`。

**请求与作业**：`POST /api/generate/comparison`：

```python
class ComparisonBody(BaseModel):
    models: list[str]                    # 2-4，registry 全名（CEWEYDS18）
    keyword: str = ""                    # 可选，用于开篇语境/导出命名
    title: str | None = None
    tone: str | None = None              # 复用 angle 语调词表
    skill_chain: list[str] | None = None
    contract_mode: ... | None = None
    draft_only: bool = True              # 默认走两步交互流
```

`generate_service.submit_comparison` → `_run_comparison_job`（复用 bus/SSE/stage 事件）：

- stage 扫库：`vault_service.get` + registry；未识别型号 / 有效型号 <2 → error 事件（中文原因）。
- stage 组稿：逐型号 `resolve_memory`（role 按 own_brands）组 scopes → `compose_comparison_draft` → assembly 事件 `{draft, comparison:{models}}`（plan=null）。
- 横评元数据缓存 `{job_id: {models, tone, keyword}}`（generate_service 内 LRU，同 plan cache 容量）；`_finalize_job` 先查横评缓存命中 → scopes 直接由 models 重解析（新鲜 index），跳过 plan 路径；其余（链/factcheck/导出/completeness）**与常规 finalize 共用同一段代码**。

**确定性骨架** `csm_core/comparison/compose.py`：

```python
def compose_comparison_draft(scopes: list[ModelScope], *, keyword: str, title: str | None) -> str
```

段落结构（全部来自 memory 对象，零 LLM）：

1. 开篇引言（关键词句 + 参评型号点名）；
2. `## 参数对照` —— spec 字段并集 × 型号列 markdown 表（缺失/占位「—」；字段序：数字型在前按并集首现序）；
3. `## 各型号亮点` —— 每型号：卖点话术（scripts 维度 × 1 变体，cap 3 维）+ 认证行；
4. `## 实测对比` —— 共有测试主题（`find_section_for_topic` 归一标题求交）逐主题各型号摘要（每型号截 ≤200 字）；无共有主题则省略本节；
5. `## 总结` —— 主推型号 endorsements + 事实性优势句（仅陈列主推独有/领先的 spec 字段，措辞中性）。

**对比指令块**（经 angle_directive 通道注入，横评 directive 与语调合并成一段文本）：「这是一篇多型号横评…基于给定事实客观对比，不得使用贬损性措辞；结论段自然突出 {主推型号} 的事实性优势；对比表中的参数一律照抄不得改写。」

**事实白名单**：`build_whitelist(scopes 全体, source_texts=[draft, title, brand_facts])`——N 型号并集天然成立；factcheck/lint/评分/导出全走既有链路，**ArticleView 质检卡零改动可用**。

**前端适配**：plan=null 时组装 tab 直接显示骨架文本（现有 draft tab 已可）；reroll 区随 !plan 隐藏（现状已如此）；「整篇润色」按钮 lastJobId 通路不变。

### 5.2 测试

- compose 纯函数：2/3/4 型号表对齐、占位「—」、共有测试求交、无测试省节、主推总结只列事实领先项（合成 memory fixtures）。
- 服务：未知型号/​<2 有效型号 error；横评缓存命中 finalize 走 models 路径；draft_only 两步流事件 shape。
- 前端：Hero 模式切换 render、query 组装、store submitComparison、ArticleView init 分支（镜像 finalize spec 的测法）。

---

## 6. 反馈学习闭环

### 6.1 持久层（monitor.db 迁移 v9，沿用既有迁移链）

新模块 `csm_core/feedback/storage.py`（模式仿 mining/geo 挂进版本链）：

```sql
CREATE TABLE creation_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT UNIQUE NOT NULL,
  mode TEXT NOT NULL DEFAULT 'normal',        -- normal | comparison | batch
  keyword TEXT, template_id TEXT, title TEXT,
  angle_json TEXT, skill_chain_json TEXT, models_json TEXT,
  contract_mode TEXT,
  document_path TEXT, format TEXT,
  edit_ratio REAL,                            -- 1 - SequenceMatcher(链成稿, 导出稿).ratio()；缓存 miss 为 NULL
  lint_unresolved INTEGER DEFAULT 0,
  factcheck_blocked INTEGER DEFAULT 0,
  score REAL, score_json TEXT,
  created_at TEXT NOT NULL, exported_at TEXT NOT NULL
);
CREATE TABLE creation_note_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER NOT NULL REFERENCES creation_records(id) ON DELETE CASCADE,
  note_id TEXT NOT NULL, variant_index INTEGER, block_id TEXT
);
CREATE INDEX idx_note_usage_note ON creation_note_usage(note_id);
CREATE TABLE fact_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER NOT NULL REFERENCES creation_records(id) ON DELETE CASCADE,
  model TEXT NOT NULL, fingerprint TEXT NOT NULL, specs_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_fact_snap_model ON fact_snapshots(model, created_at DESC);
CREATE TABLE model_fingerprints (                -- §7 全局基线
  model TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
  specs_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
```

### 6.2 采集（默认开，静默，fail-open）

配置：

```python
class FeedbackConfig(BaseModel):
    record: bool = True
    rank: bool = False
    min_samples: int = 5
    alpha: float = 0.5          # 排序权重强度
```

- `ExportBody` 加 `job_id: str | None`；前端 `exportArticle` 带上 `lastJobId`。
- 导出路由成功后 `feedback_service.record_export(job_id, body, result)`（try/except 全吞 + log，**绝不影响导出**）：
  - 请求参数：generate_service 在 submit/submit_comparison 时 stash `{job_id: 请求快照}`（LRU 50）；
  - note 用量：assembler_service 缓存 plan → picks（note_id/variant_index/block_id）；横评/缓存 miss → 跳过；
  - edit_ratio：chain 缓存 `final_text` vs 导出 `final_text`（difflib.SequenceMatcher.ratio）；
  - 事实快照：finalize 时 `feedback_service.stash_scopes(job_id, [(model, fingerprint, specs_json)])`（不重解析、无漂移），导出时落库；
  - score：前端质检卡已算 → `ExportBody.score/score_json` 可选带上（没有则 NULL）。
- factcheck 放行导出口（`POST /api/generate/{id}/export`）同样采集。
- 纯前端 clientDownload 路径（txt/无 lastRequest）：不采集（v1 边界，量小且多为兜底导出）。

### 6.3 排序应用（rank 开关，默认关）

- `feedback_service.get_note_weights() -> dict[str, float]`：按 note_id 聚合——样本数 ≥ min_samples 时 `keep_score = 平均(1 - edit_ratio)`，权重 = `clamp(1 + alpha * (keep_score - 0.5) * 2, 0.5, 1.5)`；样本不足 → 不出现在 dict。
- `assemble_plan` 增可选参 `note_weights: dict[str, float] | None = None` → 采样器候选加权（`random.Random(seed).choices(weights=…)`，**同种子仍确定可复现**；None = 今天行为，零回归）。
- generate_service 仅在 `cfg.feedback.rank` 时加载权重传入。v1 只做 note 级（变体级数据太稀）。

### 6.4 呈现

- `GET /api/feedback/stats` → `{notes: [{note_id, uses, avg_edit_ratio, avg_score, keep_score}] top50, angles: [{audience, sellpoints, tone, uses, avg_score, avg_edit_ratio}] top20}`。
- 素材库新 tab「使用反馈」：两张简表（素材表现 / 角度组合表现）+ 空态文案「导出文章后这里会积累使用统计」。
- 设置卡「反馈学习」：record / rank 两开关 + min_samples。

### 6.5 测试

- storage 迁移 v9 幂等 + 表结构；record_export 全链（stash 命中/miss、edit_ratio、fail-open 吞异常）；get_note_weights 聚合/样本门槛/钳位。
- assemble_plan 带权重同种子确定性 + None 零回归（快照）。
- 路由/前端最小集；**所有测试 tmp DB**（tmp_path init_db），config 隔离铁律照旧。

---

## 7. 事实更新传导

### 7.1 指纹

`csm_core/brand_memory/fingerprint.py`：

```python
def spec_fingerprint(memory: BrandModelMemory) -> tuple[str, str]:
    """返回 (sha256hex, canonical_specs_json)。
    canonical = {"specs": sorted [(field, raw)] 非占位对, "certs": sorted}；
    与注入/白名单无关的字段（scripts/tests/endorsements）不参与——只传导参数与认证变更。"""
```

### 7.2 全局检测（「vault 改了 → 提示」）

- 时机：lifespan 启动扫完成后 + `POST /api/vault/scan`（重建索引）后。
- `fact_service.detect_changes(index, registry) -> list[ModelChange]`：逐 registry 型号 `resolve_memory` → 指纹 vs `model_fingerprints` 基线 → 变更收集 `{model, changed: [{field, old, new}], detected_at}`（diff canonical json）→ 更新基线。首次建线不报变更。
- 前端获知：`GET /api/facts/changes`（返回并清空 pending 队列）；App 启动 sidecar 就绪后拉一次 + 重建索引响应直接携带 → `useNotifications().push("N 个型号参数已更新", …)`；素材库型号列表行加 Pill「参数已更新」（session 级显示）。

### 7.3 历史标记（「文章过期 → 可重生成」）

- `GET /api/recent` 每行增强：按 `document_path` 关联 `creation_records` → 有记录且任一 `fact_snapshots.fingerprint != model_fingerprints 当前值` → `facts_stale: true` + `stale_models: [...]` + `record: {keyword, template_id, angle_json, skill_chain_json, mode, models_json, contract_mode}`。
- RecentHistoryView：stale 行 Pill(warn)「参数已变更」，hover 列出变更字段（新端点 `GET /api/facts/diff?model=X` 按需取 diff）；「重新生成」按钮 → 用 record 参数预填 router query（常规→Hero 同款 query；横评→comparison query）跳创作流。
- 边界：只传导 vault → 文章方向；「外部参数变了提示改 vault」无法自动，不做。无 creation_record 的旧文章不标（无快照可比）。

### 7.4 测试

- fingerprint：占位/顺序/certs 参与、scripts 不参与、稳定性。
- detect_changes：首建不报、变更报 diff、基线更新、registry 缺型号跳过。
- /api/recent 增强：有/无记录、stale 判定、shape 兼容旧前端字段。
- 前端：badge render + 重新生成 query 组装。

---

## 8. 一键平台分发（design-only，本期不实现）

**目标**：成稿一键转 小红书 / 知乎 / 公众号 三种平台风格并送达对应工作流。

**路线**（复用已有件，无新框架）：

1. **风格转换 = `role:platform` skill 链 pass**（Phase 2b 已有 `role:platform` + `小红书适配.md` 种子）：补 `知乎适配.md`、`公众号适配.md` 两个种子 skill（措辞规范参考 wechat/xhs converter 的风格约定：公众号正式排版讲究、知乎论证向、小红书生活化）；导出面板加「转平台风格」下拉 → 对成稿追加单 pass `chain_service.rerun` 式调用，产出平台稿（不覆盖原成稿，另存副本）。
2. **小红书送达**：平台稿直接建 XHS 草稿（/xhs 模块已有草稿箱与 `xhs_custom_assets` 表）——`POST /api/xhs/drafts` 写入标题+正文，用户去 XHS 编辑器微调贴纸/话题后人工发布。**不做自动发布**（平台风控红线）。
3. **知乎/公众号送达**：v1 仅复制到剪贴板 + 导出 md 副本（两平台无本地编辑器模块）；后续可评估公众号草稿 API。
4. **门禁沿用**：平台稿仍过 lint（各平台 extra 词表可配，如小红书放开 emoji——`disabled_categories` 每平台覆盖）。

**为什么现在不做**：XHS 编辑器 P0-P4 刚交付完、真机验收沉淀中；先让 §3-§4 的契约/评分稳定，平台稿质量才有保障。预计单独一轮（1 PR：2 种子 skill + 转换 pass 接线 + XHS 草稿打通 + lint 平台覆盖）。

---

## 9. 全局非目标（本期明确不做）

- LLM-judge 评分（评分全确定性；judge 成本高且不可复现）。
- 变体级反馈权重（数据稀疏，先 note 级）。
- 反馈数据跨机同步/导出。
- 横评 >4 型号、横评模板化（骨架固定 v1）。
- 分块并行 LLM 调用（顺序即可，可取消更重要）。
- vault 索引落盘持久化（进程内足够）。
- 自动发布任何平台（分发章节亦然）。

## 10. 验收

1. **索引**：改 1 篇笔记后生成，日志仅重解析 1 文件；「重建索引」仍全量；关配置退回今天。
2. **分块**：粘 3 万字长文 → 分 4 块逐块拆条、进度可见、可取消、合并去重；8000 内行为不变。
3. **契约**：默认生成与今天逐字节同 prompt；切激进 → 成稿更精炼；删掉主推参数 → 质检卡「完整性」warn + 面板列缺失。
4. **评分**：单篇质检卡出综合分；批量结果表有分、低分标红；candidates=2 时导出高分稿、落选稿在 candidates/。
5. **横评**：选 3 型号起飞 → 骨架含对齐参数表/亮点/实测/总结 → 润色后 factcheck/lint 正常工作 → 导出成功。
6. **反馈**：导出后 creation_records 落一行（含 edit_ratio/用量/快照）；素材库「使用反馈」出统计；rank 开后同种子采样仍可复现。
7. **传导**：改 vault 某型号参数 → 重建索引 → 通知「1 个型号参数已更新」+ 素材库徽章；历史页对应文章标「参数已变更」+ 一键重新生成预填。

## 11. 实现纪律（沿用历轮）

- TDD + 子代理驱动 + 逐单元两段审查 + 最终综合审查。
- config 隔离铁律：sidecar 测试一律 monkeypatch `config_service.load`。
- 共享盘红线：任何测试禁写 `D:\家电组共享\DATA`；写盘测试全走 tmp_path；真实库只读回归 `@skipif`。
- vue-tsc 必跑；字面量 union fixture 显式标注（CSM#144 教训）。
- 前端新门禁面板 proceed 一律重入 onExportClick（PR#148 教训）——本期完整性面板为纯信息展示无 proceed，不涉。
- DB 迁移测试用 tmp_path init_db，不碰真实 monitor.db。
